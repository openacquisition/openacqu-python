"""CLI tests using FakeI2CBus (no hardware)."""

from __future__ import annotations

from openacqu.chips.eeprom_24aa025e48 import EUI48_OFFSET, USER_MEMORY_SIZE, EEPROM24AA025E48
from openacqu.chips.lp5817 import LP5817
from openacqu.colors import INDICATOR_COLORS, indicator_pwm
from openacqu.chips.fxl6408 import DEFAULT_ADDRESS as FXL_ADDR
from openacqu.chips.mcp9600 import EXPECTED_DEVICE_ID
from openacqu.chips.sc18is606 import DEFAULT_ADDRESS as BRIDGE_ADDR
from openacqu.cli import main
from openacqu.product import ProductNumber
from openacqu.transport.fake import FakeI2CBus
from openacqu.transport.fake_sc18is606 import FakeSC18IS606


def _bus_with_temp_probe() -> FakeI2CBus:
    bus = FakeI2CBus()
    bus.memory(FXL_ADDR)[0x0F] = ProductNumber.TEMPERATURE
    bus.memory(0x50)[EUI48_OFFSET : EUI48_OFFSET + 6] = bytes(
        [0x00, 0x04, 0xA3, 0x11, 0x22, 0x33]
    )
    mcp = bus.memory(0x67)
    mcp[0x00:0x02] = bytes([0x01, 0x00])  # 16.0 °C hot
    mcp[0x02:0x04] = bytes([0x00, 0x40])  # 4.0 °C cold
    mcp[0x04] = 0x40  # TH_UPDATE
    mcp[0x05] = 0x00  # type K, filter 0
    mcp[0x06] = 0x00  # 18-bit ADC
    mcp[0x20:0x22] = bytes([EXPECTED_DEVICE_ID, 0x10])
    return bus


def test_cli_product_and_eui48(capsys) -> None:
    bus = _bus_with_temp_probe()
    assert main(["product"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "0x01"

    assert main(["eui48"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "00-04-A3-11-22-33"


def test_cli_temp_read_status_type_filter_resolution(capsys) -> None:
    bus = _bus_with_temp_probe()

    assert main(["temp", "read", "--no-wait"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "16.0000"

    assert main(["temp", "cold"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "4.0000"

    assert main(["temp", "status"], bus=bus) == 0
    assert "ready=True" in capsys.readouterr().out

    assert main(["temp", "type"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "K"
    assert main(["temp", "type", "T"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "T"

    assert main(["temp", "filter", "3"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "3"

    assert main(["temp", "resolution", "16"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "16"
    assert main(["temp", "resolution"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "16"


def test_cli_led_and_identify(capsys) -> None:
    bus = _bus_with_temp_probe()
    assert main(["led", "set", "1", "2", "3"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "1 2 3"
    assert main(["led", "get"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "1 2 3"
    assert main(["led", "color", "red", "--brightness", "1"], bus=bus) == 0
    out = capsys.readouterr().out.strip()
    assert out.startswith("red -> ")
    assert main(["led", "off"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "off"

    assert main(["temp", "identify"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "0x40 0x10 (1.0)"


def test_cli_led_cycle_dwells_and_ends_off(capsys, monkeypatch) -> None:
    sleeps: list[float] = []
    calls: list[tuple] = []
    monkeypatch.setattr("openacqu.cli.time.sleep", lambda seconds: sleeps.append(seconds))
    original_set = LP5817.set_pwm
    original_off = LP5817.off

    def set_pwm(self, red, green, blue):
        calls.append(("pwm", (red, green, blue)))
        return original_set(self, red, green, blue)

    def off(self):
        calls.append(("off",))
        return original_off(self)

    monkeypatch.setattr(LP5817, "set_pwm", set_pwm)
    monkeypatch.setattr(LP5817, "off", off)
    bus = _bus_with_temp_probe()
    assert main(["led", "cycle", "--dwell", "0.25"], bus=bus) == 0
    assert calls[0] == ("off",)
    assert calls[-2] == ("off",)
    assert [item[1] for item in calls if item[0] == "pwm" and item[1] != (0, 0, 0)] == [
        indicator_pwm(name) for name, _color in INDICATOR_COLORS
    ]
    assert sleeps == [0.25] * (len(INDICATOR_COLORS) + 2)
    assert bus.memory(0x2D)[0x18:0x1B] == bytes([0, 0, 0])
    out = capsys.readouterr().out
    assert out.startswith("off\n")
    assert "green #00ff00 ->" in out
    assert out.endswith("off\n")


def test_cli_led_cycle_start_and_bad_dwell(capsys, monkeypatch) -> None:
    calls: list[tuple[int, int, int]] = []
    monkeypatch.setattr("openacqu.cli.time.sleep", lambda _seconds: None)
    original_set = LP5817.set_pwm

    def set_pwm(self, red, green, blue):
        calls.append((red, green, blue))
        return original_set(self, red, green, blue)

    monkeypatch.setattr(LP5817, "set_pwm", set_pwm)
    bus = _bus_with_temp_probe()
    assert main(["led", "cycle", "--start", "blue", "--dwell", "0.1"], bus=bus) == 0
    names = [name for name, _color in INDICATOR_COLORS]
    index = names.index("blue")
    rotated = names[index:] + names[:index]
    shown = [pwm for pwm in calls if pwm != (0, 0, 0)]
    assert shown[0] == indicator_pwm("blue")
    assert shown == [indicator_pwm(name) for name in rotated]
    capsys.readouterr()
    assert main(["led", "cycle", "--start", "pink"], bus=bus) == 1
    assert "unknown indicator color" in capsys.readouterr().err
    assert main(["led", "cycle", "--dwell", "0"], bus=bus) == 1


def test_cli_eeprom_stress_refuses_without_yes(capsys, monkeypatch) -> None:
    monkeypatch.setattr(EEPROM24AA025E48, "write_cycle_s", 0)
    bus = _bus_with_temp_probe()
    bus.memory(0x50)[0x10] = 0x5A
    assert main(["eeprom", "stress"], bus=bus) == 1
    assert bus.memory(0x50)[0x10] == 0x5A
    captured = capsys.readouterr()
    assert "will be erased" in captured.out
    assert "without --yes" in captured.err


def test_cli_eeprom_stress_yes(capsys, monkeypatch) -> None:
    monkeypatch.setattr(EEPROM24AA025E48, "write_cycle_s", 0)
    bus = _bus_with_temp_probe()
    eui = bytes(bus.memory(0x50)[EUI48_OFFSET : EUI48_OFFSET + 6])
    assert main(["eeprom", "stress", "--yes", "--seed", "1"], bus=bus) == 0
    assert bus.memory(0x50)[:USER_MEMORY_SIZE] == bytes([0xFF]) * USER_MEMORY_SIZE
    assert bytes(bus.memory(0x50)[EUI48_OFFSET : EUI48_OFFSET + 6]) == eui
    out = capsys.readouterr().out
    assert "will be erased" in out
    assert "seed:  1" in out
    assert "passed:" in out
    assert "eui48 unchanged: 00-04-A3-11-22-33" in out


def test_cli_eeprom_read_write(capsys) -> None:
    bus = _bus_with_temp_probe()
    assert main(["eeprom", "write", "0x10", "aabb"], bus=bus) == 0
    capsys.readouterr()
    assert main(["eeprom", "read", "0x10", "2"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "aa bb"


def test_cli_info(capsys) -> None:
    bus = _bus_with_temp_probe()
    assert main(["info"], bus=bus) == 0
    out = capsys.readouterr().out
    assert "product:     0x01 (TEMPERATURE)" in out
    assert "eui48:       00-04-A3-11-22-33" in out
    assert "mcp9600 id:  0x40" in out


def test_cli_check_product_mismatch() -> None:
    bus = _bus_with_temp_probe()
    bus.memory(FXL_ADDR)[0x0F] = 0x99
    assert main(["--check-product", "product"], bus=bus) == 1


def _bus_with_ph_probe() -> FakeI2CBus:
    bus = FakeI2CBus()
    bus.memory(FXL_ADDR)[0x0F] = ProductNumber.PH
    bus.memory(0x50)[EUI48_OFFSET : EUI48_OFFSET + 6] = bytes(
        [0x00, 0x04, 0xA3, 0xAA, 0xBB, 0xCC]
    )
    bus.install(BRIDGE_ADDR, FakeSC18IS606())
    return bus


def test_cli_ph_configure_and_fields(capsys) -> None:
    bus = _bus_with_ph_probe()

    assert main(["ph", "configure"], bus=bus) == 0
    out = capsys.readouterr().out
    assert "config:  0x0000" in out
    assert "pga:     5 V/V" in out

    # Each CLI invocation opens a fresh probe; setters report the value written.
    assert main(["ph", "pga", "10"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "10"
    assert main(["ph", "vcm", "3/4"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "3/4"
    assert main(["ph", "vocm", "gnd"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "gnd"
    assert main(["ph", "diag", "on"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "on"
    assert main(["ph", "write", "0x0A00"], bus=bus) == 0
    assert capsys.readouterr().out.strip() == "0x0A00"

    assert main(["ph", "bridge"], bus=bus) == 0
    assert "0x28" in capsys.readouterr().out

    assert main(["ph", "info"], bus=bus) == 0
    info = capsys.readouterr().out
    assert "bridge:        0x28" in info
    assert "adc:           not configured" in info
