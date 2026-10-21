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
