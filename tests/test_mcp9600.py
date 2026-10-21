"""Unit tests for the MCP9600 driver (fake I2C, no hardware)."""

from __future__ import annotations

import pytest

from openacqu.chips.mcp9600 import (
    EXPECTED_DEVICE_ID,
    AdcResolution,
    MCP9600,
    ThermocoupleType,
)
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


def test_status_temperature_ready_and_clear() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x04] = 0x40  # TH_UPDATE
    assert chip.temperature_ready is True
    chip.clear_temperature_ready()
    assert memory[0x04] == 0x00
    assert chip.temperature_ready is False


def test_open_circuit_flag() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x04] = 0x10
    assert chip.open_circuit is True
    memory[0x04] = 0x00
    assert chip.open_circuit is False


def test_wait_for_temperature_succeeds_when_ready() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)

    # After clear, immediately present a new conversion for the next poll.
    class AutoReady:
        def __init__(self, mem: bytearray) -> None:
            self._mem = mem
            self._cleared = False

        def read_register(self, register: int, length: int = 1) -> bytes:
            if register == 0x04 and self._cleared:
                self._mem[0x04] = 0x40
            return bytes(self._mem[register : register + length])

        def write_register(self, register: int, data: bytes | list[int]) -> None:
            payload = bytes(data)
            self._mem[register : register + len(payload)] = payload
            if register == 0x04 and (payload[0] & 0x40) == 0:
                self._cleared = True

    chip._dev = AutoReady(memory)  # type: ignore[method-assign]
    memory[0x04] = 0x40
    memory[0x00:0x02] = bytes([0x00, 0x10])  # 1.0 °C
    assert chip.read_hot_junction_c(wait=True, timeout_s=0.2) == 1.0


def test_wait_for_temperature_timeout() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x04] = 0x00
    with pytest.raises(TimeoutError):
        chip.wait_for_temperature(timeout_s=0.05, poll_s=0.01)


def test_adc_resolution_roundtrip() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x06] = 0x00
    assert chip.adc_resolution is AdcResolution.BITS_18
    chip.adc_resolution = AdcResolution.BITS_12
    assert memory[0x06] == (AdcResolution.BITS_12 << 5)
    assert chip.adc_resolution is AdcResolution.BITS_12


def test_adc_resolution_preserves_other_bits() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x06] = 0x1C  # burst samples + shutdown nibble-ish lower bits
    chip.adc_resolution = AdcResolution.BITS_16
    assert memory[0x06] == (0x1C | (AdcResolution.BITS_16 << 5))


def test_device_id_and_identify() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x20:0x22] = bytes([EXPECTED_DEVICE_ID, 0x10])
    assert chip.device_id == 0x40
    assert chip.revision == 0x10
    assert chip.revision_str == "1.0"
    assert chip.identify() == (0x40, 0x10)


def test_identify_rejects_wrong_id() -> None:
    bus = FakeI2CBus()
    chip, memory = _sensor(bus)
    memory[0x20:0x22] = bytes([0x41, 0x10])  # MCP9601 ID
    with pytest.raises(LookupError, match="unexpected MCP9600 device ID"):
        chip.identify()
