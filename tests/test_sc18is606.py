"""Unit tests for SC18IS606 I2C-to-SPI bridge (fake I2C, no hardware)."""

from __future__ import annotations

import pytest

from openacqu.chips.sc18is606 import (
    DEFAULT_ADDRESS,
    SC18IS606,
    SpiClock,
    SpiMode,
)
from openacqu.transport.fake import FakeI2CBus
from openacqu.transport.fake_sc18is606 import FakeSC18IS606


def _bridge() -> tuple[SC18IS606, FakeSC18IS606, FakeI2CBus]:
    bus = FakeI2CBus()
    fake = FakeSC18IS606()
    bus.install(DEFAULT_ADDRESS, fake)
    return SC18IS606(bus), fake, bus


def test_configure_spi_mode3_115khz() -> None:
    chip, fake, _ = _bridge()
    config = chip.configure_spi(mode=SpiMode.MODE3, clock=SpiClock.KHZ_115)
    # ORDER=0, MODE=11, F=10 → 0b0000_1110
    assert config == 0x0E
    assert fake.config_byte == 0x0E
    assert fake.commands[0] == bytes([0xF0, 0x0E])


def test_configure_spi_lsb_and_mode0() -> None:
    chip, fake, _ = _bridge()
    config = chip.configure_spi(
        mode=SpiMode.MODE0, clock=SpiClock.KHZ_1875, lsb_first=True
    )
    assert config == 0x20
    assert fake.commands[0] == bytes([0xF0, 0x20])


def test_spi_transfer_cs0_and_echo() -> None:
    chip, fake, _ = _bridge()
    rx = chip.spi_transfer(b"\x12\x34", chip_select=0)
    assert rx == b"\x12\x34"
    assert fake.spi_transfers == [(0x01, b"\x12\x34")]
    # clear interrupt follows transfer
    assert fake.commands[-1] == bytes([0xF1])


def test_spi_transfer_cs1_and_cs2() -> None:
    chip, fake, _ = _bridge()
    chip.spi_transfer(b"\xaa", chip_select=1, clear_int=False)
    chip.spi_transfer(b"\xbb", chip_select=2, clear_int=False)
    assert fake.spi_transfers == [(0x02, b"\xaa"), (0x04, b"\xbb")]


def test_spi_transfer_rejects_bad_cs_and_empty() -> None:
    chip, _, _ = _bridge()
    with pytest.raises(ValueError):
        chip.spi_transfer(b"\x00", chip_select=3)
    with pytest.raises(ValueError):
        chip.spi_transfer(b"")


def test_as_spi_bus_device() -> None:
    chip, fake, _ = _bridge()
    spi = chip.as_spi_bus().device(0)
    assert spi.transfer(b"\xde\xad") == b"\xde\xad"
    assert fake.spi_transfers[-1] == (0x01, b"\xde\xad")
