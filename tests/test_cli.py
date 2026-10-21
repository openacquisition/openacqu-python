"""CLI tests using FakeI2CBus (no hardware)."""

from __future__ import annotations

from openacqu.chips.eeprom_24aa025e48 import EUI48_OFFSET
from openacqu.chips.fxl6408 import DEFAULT_ADDRESS as FXL_ADDR
from openacqu.chips.mcp9600 import EXPECTED_DEVICE_ID
from openacqu.cli import main
from openacqu.product import ProductNumber
from openacqu.transport.fake import FakeI2CBus


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
