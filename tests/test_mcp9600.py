"""Unit tests for the MCP9600 driver (fake I2C, no hardware)."""

from __future__ import annotations

import pytest

from openacqu.chips.mcp9600 import MCP9600, ThermocoupleType
from openacqu.transport.fake import FakeI2CBus


def _sensor(bus: FakeI2CBus, address: int = 0x67) -> tuple[MCP9600, bytearray]:
    memory = bus.memory(address)
    return MCP9600(bus, address=address), memory


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (bytes([0x00, 0x00]), 0.0),
        (bytes([0x00, 0x10]), 1.0),  # 16 / 16
        (bytes([0x05, 0xA0]), 90.0),  # datasheet-style positive example-ish
        (bytes([0xFF, 0xFF]), -0.0625),
        (bytes([0xFF, 0xF0]), -1.0),
        (bytes([0xF6, 0x00]), -160.0),
    ],
)
def test_decode_temperature(raw: bytes, expected: float) -> None:
    assert MCP9600.decode_temperature(raw) == expected


def test_hot_junction_reads_register() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x00:0x02] = bytes([0x00, 0x20])  # 2.0 °C
    assert chip.hot_junction_c == 2.0
    assert chip.temp_hj == 2.0


def test_thermocouple_type_roundtrip() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x05] = 0x00  # type K, filter 0
    assert chip.thermocouple_type is ThermocoupleType.K

    chip.thermocouple_type = ThermocoupleType.T
    assert memory[0x05] == (ThermocoupleType.T << 4)
    assert chip.thermocouple_type is ThermocoupleType.T


def test_thermocouple_type_preserves_filter_bits() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x05] = 0x05  # type K, filter 5
    chip.thermocouple_type = ThermocoupleType.J
    assert memory[0x05] == ((ThermocoupleType.J << 4) | 0x05)


def test_filter_coefficient_roundtrip() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x05] = ThermocoupleType.K << 4
    chip.filter_coefficient = 7
    assert memory[0x05] == ((ThermocoupleType.K << 4) | 0x07)
    assert chip.filter_coefficient == 7


def test_filter_coefficient_rejects_out_of_range() -> None:
    bus = FakeI2CBus()
    chip, _ = _sensor(bus)
    with pytest.raises(ValueError):
        chip.filter_coefficient = 8


def test_thermocouple_type_rejects_non_enum() -> None:
    bus = FakeI2CBus()
    chip, _ = _sensor(bus)
    with pytest.raises(TypeError):
        chip.thermocouple_type = 0  # type: ignore[assignment]
