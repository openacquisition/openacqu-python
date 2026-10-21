"""Unit tests for ProbePh1 composition (fake I2C, no hardware)."""

from __future__ import annotations

from openacqu import ProbePh1, ProductNumber
from openacqu.chips.lmp91200 import PgaGain, VcmLevel
from openacqu.chips.sc18is606 import DEFAULT_ADDRESS as BRIDGE_ADDR
from openacqu.chips.fxl6408 import DEFAULT_ADDRESS as FXL_ADDR
from openacqu.transport.fake import FakeI2CBus
from openacqu.transport.fake_sc18is606 import FakeSC18IS606


def _ph_bus() -> tuple[FakeI2CBus, FakeSC18IS606]:
    bus = FakeI2CBus()
    bus.memory(FXL_ADDR)[0x0F] = ProductNumber.PH
    fake = FakeSC18IS606()
    bus.install(BRIDGE_ADDR, fake)
    return bus, fake


def test_probe_ph1_configures_bridge_and_afe() -> None:
    bus, fake = _ph_bus()
    probe = ProbePh1(bus)
    assert probe.bridge.address == BRIDGE_ADDR
    assert fake.config_byte == 0x0E  # Mode3 + 115 kHz
    probe.afe.configure_ph(pga=PgaGain.GAIN_10, vcm=VcmLevel.VREF_1_4)
    assert probe.afe.config == 0x0E00  # PGA + VCM 1/4
    assert fake.spi_transfers[-1][0] == 0x01  # CS0
    assert fake.spi_transfers[-1][1] == b"\x0e\x00"


def test_probe_ph1_check_product() -> None:
    bus, _ = _ph_bus()
    ProbePh1(bus, check_product=True)

    bus.memory(FXL_ADDR)[0x0F] = 0x01
    try:
        ProbePh1(bus, check_product=True)
        raise AssertionError("expected LookupError")
    except LookupError as exc:
        assert "0x02" in str(exc)
