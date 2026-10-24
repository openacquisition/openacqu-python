"""Unit tests for ProbeTemp1 composition."""

from __future__ import annotations

from openacqu import ProbeTemp1
from openacqu.chips.mcp9600 import DEFAULT_ADDRESS, ThermocoupleType
from openacqu.transport.fake import FakeI2CBus


def test_probe_temp1_uses_injected_bus() -> None:
    bus = FakeI2CBus()
    memory = bus.memory(DEFAULT_ADDRESS)
    memory[0x00:0x02] = bytes([0x01, 0x00])  # 16.0 °C

    probe = ProbeTemp1(bus)
    assert probe.temperature_c == 16.0
    assert probe.thermocouple.hot_junction_c == 16.0


def test_probe_temp1_custom_address() -> None:
    bus = FakeI2CBus()
    memory = bus.memory(0x67)
    memory[0x00:0x02] = bytes([0x00, 0x40])  # 4.0 °C

    probe = ProbeTemp1(bus, mcp9600_address=0x67)
    assert probe.thermocouple.address == 0x67
    assert probe.temperature_c == 4.0


def test_configure_thermocouple_via_model() -> None:
    bus = FakeI2CBus()
    probe = ProbeTemp1(bus)
    bus.memory(DEFAULT_ADDRESS)[0x05] = 0x00
    probe.thermocouple.thermocouple_type = ThermocoupleType.N
    probe.thermocouple.filter_coefficient = 3
    assert bus.memory(DEFAULT_ADDRESS)[0x05] == ((ThermocoupleType.N << 4) | 0x03)
