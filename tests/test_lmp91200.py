"""Unit tests for LMP91200 AFE config driver (fake SPI, no hardware)."""

from __future__ import annotations

import pytest

from openacqu.chips.lmp91200 import LMP91200, MeasMode, PgaGain, VcmLevel, VocmSelect
from openacqu.transport.fake import FakeSpiBus


def test_default_config_and_configure_ph() -> None:
    bus = FakeSpiBus()
    afe = LMP91200(bus.device(0))
    assert afe.config == 0x0000
    afe.configure_ph()
    assert afe.config == 0x0000
    assert afe.meas_mode is MeasMode.PH
    assert afe.pga is PgaGain.GAIN_5
    assert afe.vcm is VcmLevel.VREF_1_2
    assert afe.vocm is VocmSelect.VOCM
    assert afe.diag_en is False
    assert bus.device(0).transfers[-1] == b"\x00\x00"


def test_pga_10_and_vcm_3_4() -> None:
    bus = FakeSpiBus()
    afe = LMP91200(bus.device(0))
    afe.configure_ph(pga=PgaGain.GAIN_10, vcm=VcmLevel.VREF_3_4)
    # D11=1, D10:D8=010 → 0b0000_1010_0000_0000 = 0x0A00
    assert afe.config == 0x0A00
    assert bus.device(0).transfers[-1] == b"\x0a\x00"


def test_field_setters_preserve_other_bits() -> None:
    bus = FakeSpiBus()
    afe = LMP91200(bus.device(0))
    afe.pga = PgaGain.GAIN_10
    afe.vcm = VcmLevel.VREF_7_8
    afe.vocm = VocmSelect.GND
    afe.diag_en = True
    # D11=1, VCM=011, VOCM=1, DIAG=1 → 0b0000_1011_1100_0000 = 0x0BC0
    assert afe.config == 0x0BC0


def test_verify_echo_success_and_failure() -> None:
    bus = FakeSpiBus()
    spi = bus.device(0)
    afe = LMP91200(spi)

    # FakeSpiDevice echoes MOSI by default → verify passes.
    afe.write_config(0x0800, verify=True)
    assert afe.config == 0x0800
    assert spi.transfers[-1] == b"\x08\x00\x08\x00"

    spi.rx_queue[:] = b"\x08\x00\xff\xff"
    with pytest.raises(IOError, match="verify failed"):
        afe.write_config(0x0800, verify=True)


def test_read_config_uses_echo() -> None:
    bus = FakeSpiBus()
    spi = bus.device(0)
    afe = LMP91200(spi)
    afe.write_config(0x0040)
    # Stage echo of a different word in the second half.
    spi.rx_queue[:] = b"\x00\x00\x00\x40"
    assert afe.read_config() == 0x0040
