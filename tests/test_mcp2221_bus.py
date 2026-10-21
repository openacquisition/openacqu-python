"""Tests for MCP2221Bus keep-alive and USB diagnostics (no hardware)."""

from __future__ import annotations

import time

from openacqu.cli import main
from openacqu.transport.mcp2221 import MCP2221Bus


class _FakeDevice:
    def __init__(self) -> None:
        self.gpio_reads = 0
        self.closed = False

    def GPIO_read(self) -> dict:
        self.gpio_reads += 1
        return {"GP0": 0}

    def read_flash_info(self) -> dict:
        return {"USB Manufacturer": "Microchip", "USB Product": "MCP2221"}

    def I2C_Slave(self, address: int, reg_bytes: int = 1):
        raise AssertionError("not used in these tests")

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


def test_cli_usb(capsys) -> None:
    device = _FakeDevice()
    bus = MCP2221Bus(device)
    assert main(["usb"], bus=bus) == 0
    out = capsys.readouterr().out
    assert "vid: 0x04D8" in out
    assert "handle_open: True" in out
    assert "USBCFG" in out
