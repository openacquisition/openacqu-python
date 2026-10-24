"""Tests for MCP2221Bus keep-alive, close, and I2C ready wait (no hardware)."""

from __future__ import annotations

import time

import pytest

from openacqu.cli import main
from openacqu.transport.mcp2221 import MCP2221Bus


class _FakeSlave:
    def __init__(self, present: bool) -> None:
        self._present = present

    def is_present(self) -> bool:
        return self._present


class _FakeDevice:
    def __init__(self, *, present_after: int = 0) -> None:
        self.gpio_reads = 0
        self.closed = False
        self.hidhandler = self
        self._acks = 0
        self._present_after = present_after
        self.i2c_probes: list[int] = []

    def GPIO_read(self) -> dict:
        self.gpio_reads += 1
        return {"GP0": 0}

    def read_flash_info(self) -> dict:
        return {"USB Manufacturer": "Microchip", "USB Product": "MCP2221"}

    def I2C_Slave(self, address: int, reg_bytes: int = 1, force: bool = False):
        self.i2c_probes.append(address)
        self._acks += 1
        present = self._acks > self._present_after
        return _FakeSlave(present)

    def close(self) -> None:
        self.closed = True

    def __str__(self) -> str:
        return "FakeMCP2221"


def test_ping_and_usb_status() -> None:
    device = _FakeDevice()
    bus = MCP2221Bus(device)
    bus.ping()
    assert device.gpio_reads == 1
    status = bus.usb_status()
    assert status["vid"] == "0x04D8"
    assert status["pid"] == "0x00DD"
    assert status["handle_open"] is True
    assert status["keepalive_active"] is False
    assert status["flash"]["USB Product"] == "MCP2221"
    assert "USBCFG" in status["usbcfg_note"]


def test_keepalive_thread_pings() -> None:
    device = _FakeDevice()
    bus = MCP2221Bus(device, keepalive_s=0.05)
    try:
        assert bus.keepalive_active is True
        time.sleep(0.18)
        assert device.gpio_reads >= 2
    finally:
        bus.close()
    assert bus.keepalive_active is False
    assert device.closed is True


def test_close_releases_and_is_idempotent() -> None:
    device = _FakeDevice()
    bus = MCP2221Bus(device)
    bus.close()
    bus.close()
    assert device.closed is True
    with pytest.raises(RuntimeError, match="closed"):
        bus.ping()


def test_context_manager_closes() -> None:
    device = _FakeDevice()
    with MCP2221Bus(device) as bus:
        bus.ping()
    assert device.closed is True


def test_wait_for_i2c_retries_until_ack() -> None:
    device = _FakeDevice(present_after=2)
    bus = MCP2221Bus(device)
    bus.wait_for_i2c(0x67, timeout_s=1.0, poll_s=0.01)
    assert device.i2c_probes.count(0x67) >= 3


def test_wait_for_i2c_timeout() -> None:
    device = _FakeDevice(present_after=10_000)
    bus = MCP2221Bus(device)
    with pytest.raises(TimeoutError, match="no I2C ACK"):
        bus.wait_for_i2c(0x67, timeout_s=0.05, poll_s=0.01)


def test_ensure_active_settles(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    device = _FakeDevice()
    bus = MCP2221Bus(device)
    bus.ensure_active(settle_s=0.12)
    assert device.gpio_reads == 1
    assert sleeps == [0.12]


def test_cli_usb(capsys) -> None:
    device = _FakeDevice()
    bus = MCP2221Bus(device)
    assert main(["usb"], bus=bus) == 0
    out = capsys.readouterr().out
    assert "vid: 0x04D8" in out
    assert "handle_open: True" in out
    assert "USBCFG" in out


_CMD_READ_FLASH = 0xB0
_CMD_WRITE_FLASH = 0xB1


class _FlashDevice(_FakeDevice):
    """Minimal flash image. Byte 0 is factory CDCSEC (USBCFG active-low)."""

    def __init__(self) -> None:
        super().__init__()
        self.chip = [0x7C, 0x12, 0xE0, 0xC4, 0xD8, 0x04, 0xDD, 0x00, 0x00, 0x32]
        self.writes: list[list[int]] = []

    def send_cmd(self, buf: list[int]) -> list[int]:
        if buf[0] == _CMD_READ_FLASH and buf[1] == 0x00:
            return [0xB0, 0x00, len(self.chip), 0, *self.chip]
        if buf[0] == _CMD_WRITE_FLASH and buf[1] == 0x00:
            data = list(buf[2:])
            self.writes.append(data)
            self.chip = data[:10]
            return [0xB1, 0x00]
        raise AssertionError(f"unexpected flash command {buf!r}")


def test_usbcfg_active_level_reads_factory_active_low() -> None:
    bus = MCP2221Bus(_FlashDevice())
    assert bus.usbcfg_active_level() == "low"


def test_flash_usbcfg_changes_only_inactive_bit() -> None:
    device = _FlashDevice()
    bus = MCP2221Bus(device)
    original = list(device.chip)

    assert bus.flash_usbcfg_active_level("high") == "high"
    assert device.chip[0] == 0x78
    assert device.chip[1:] == original[1:]
    assert device.writes[-1][10:] == [0] * 8
    assert bus.usbcfg_active_level() == "high"

    assert bus.flash_usbcfg_active_level("low") == "low"
    assert device.chip[0] == 0x7C
    assert device.chip[1:] == original[1:]


def test_flash_usbcfg_refuses_protected_chip() -> None:
    device = _FlashDevice()
    device.chip[0] = 0x7D  # protection bits set
    bus = MCP2221Bus(device)
    with pytest.raises(RuntimeError, match="protected"):
        bus.flash_usbcfg_active_level("high")
    assert device.writes == []


class _PinDevice(_FakeDevice):
    def __init__(self) -> None:
        super().__init__()
        self.pin_calls: list[dict] = []
        self.saved = False

    def set_pin_function(self, **kwargs: object) -> None:
        self.pin_calls.append(kwargs)

    def save_config(self) -> None:
        self.saved = True


def test_force_gp2_gpio_sets_sram_output() -> None:
    device = _PinDevice()
    bus = MCP2221Bus(device)
    assert bus.force_gp2_gpio("high") == "high"
    assert bus.force_gp2_gpio("low") == "low"
    assert device.pin_calls == [
        {"gp2": "GPIO_OUT", "out2": True},
        {"gp2": "GPIO_OUT", "out2": False},
    ]
    assert device.saved is False


def test_force_gp2_gpio_rejects_unknown_level() -> None:
    bus = MCP2221Bus(_PinDevice())
    with pytest.raises(ValueError, match="high or low"):
        bus.force_gp2_gpio("on")


def test_cli_usb_gp2(capsys) -> None:
    device = _PinDevice()
    bus = MCP2221Bus(device)
    assert main(["usb", "gp2"], bus=bus) == 0
    assert capsys.readouterr().out == (
        "gp2: high\nfunction: GPIO_OUT\npersists until reset or unplug\n"
    )
    assert device.pin_calls == [{"gp2": "GPIO_OUT", "out2": True}]
    assert device.saved is False

    assert main(["usb", "gp2", "low"], bus=bus) == 0
    assert device.pin_calls[-1] == {"gp2": "GPIO_OUT", "out2": False}
    assert "gp2: low" in capsys.readouterr().out


def test_cli_usb_usbcfg_read_and_flash(capsys) -> None:
    bus = MCP2221Bus(_FlashDevice())
    assert main(["usb", "usbcfg"], bus=bus) == 0
    assert capsys.readouterr().out == "active: low\nUSBCFGINST: 1\n"

    assert main(["usb", "usbcfg", "high"], bus=bus) == 0
    out = capsys.readouterr().out
    assert "active: high" in out
    assert "USBCFGINST: 0" in out
    assert "re-enumerate" in out
    assert bus.usbcfg_active_level() == "high"
