"""Unit tests for shared core peripherals (fake I2C, no hardware)."""

from __future__ import annotations

import pytest

from openacqu import ProbeTemp1, ProductNumber
from openacqu.chips.eeprom_24aa025e48 import EUI48_OFFSET, EEPROM24AA025E48
from openacqu.chips.fxl6408 import DEFAULT_ADDRESS as FXL_ADDR
from openacqu.chips.fxl6408 import FXL6408
from openacqu.chips.lp5817 import LP5817
from openacqu.transport.fake import FakeI2CBus


def test_fxl6408_reads_product_number() -> None:
    bus = FakeI2CBus()
    # Input Status register 0x0F; GPIO0 high → product 0x01
    bus.memory(FXL_ADDR)[0x0F] = ProductNumber.TEMPERATURE
    chip = FXL6408(bus)
    assert chip.product_number == 0x01
    assert chip.read_inputs() == 0x01


def test_eeprom_eui48_and_user_read_write() -> None:
    bus = FakeI2CBus()
    mem = bus.memory(0x50)
    mem[EUI48_OFFSET : EUI48_OFFSET + 6] = bytes([0x00, 0x04, 0xA3, 0x12, 0x34, 0x56])
    eeprom = EEPROM24AA025E48(bus)
    assert eeprom.eui48 == bytes([0x00, 0x04, 0xA3, 0x12, 0x34, 0x56])
    assert eeprom.eui48_str == "00-04-A3-12-34-56"

    eeprom.write(0x10, b"hi")
    assert eeprom.read(0x10, 2) == b"hi"


def test_lp5817_set_rgb() -> None:
    bus = FakeI2CBus()
    led = LP5817(bus)
    led.set_rgb(10, 20, 30)
    mem = bus.memory(0x2D)
    assert mem[0x00] == 0x01  # CHIP_EN
    assert mem[0x02] == 0x07  # all outputs enabled
    assert mem[0x0F] == 0x55  # update latched during init
    assert mem[0x18:0x1B] == bytes([10, 20, 30])
    assert led.get_pwm() == (10, 20, 30)
    led.off()
    assert led.get_pwm() == (0, 0, 0)


def test_probe_exposes_core_and_checks_product() -> None:
    bus = FakeI2CBus()
    bus.memory(FXL_ADDR)[0x0F] = ProductNumber.TEMPERATURE
    bus.memory(0x50)[EUI48_OFFSET : EUI48_OFFSET + 6] = bytes(range(6))

    probe = ProbeTemp1(bus, check_product=True)
    assert probe.product_number == 0x01
    assert probe.require_product() == 0x01
    assert probe.eeprom.eui48 == bytes(range(6))
    probe.led.set_rgb(1, 2, 3)
    assert probe.led.get_pwm() == (1, 2, 3)


def test_probe_product_mismatch() -> None:
    bus = FakeI2CBus()
    bus.memory(FXL_ADDR)[0x0F] = 0x99
    with pytest.raises(LookupError, match="product number mismatch"):
        ProbeTemp1(bus, check_product=True)
