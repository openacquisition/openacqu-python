"""Microchip MCP9600 thermocouple EMF-to-temperature converter."""

from __future__ import annotations

from enum import IntEnum

from openacqu.transport.base import I2CBus, I2CDevice

# Default ADDR-pin configuration used on ProbeTemp1 hardware.
DEFAULT_ADDRESS = 0x67


class ThermocoupleType(IntEnum):
    """Thermocouple types supported by the MCP9600 SENSOR_CONFIG register."""

    K = 0x0
    J = 0x1
    T = 0x2
    N = 0x3
    S = 0x4
    E = 0x5
    B = 0x6
    R = 0x7


class MCP9600:
    """Register-level driver for the MCP9600.

    Talks only to an :class:`~openacqu.transport.base.I2CBus`; it does not open
    USB itself. That keeps the driver unit-testable with ``FakeI2CBus``.
    """

    HOT_JUNC_TEMP = (0x00, 2)
    JUNC_TEMP_DELTA = (0x01, 2)
    COLD_JUNC_TEMP = (0x02, 2)
    RAW_ADC_DATA = (0x03, 3)
    STATUS = (0x04, 1)
    SENSOR_CONFIG = (0x05, 1)
    DEVICE_CONFIG = (0x06, 1)
    ALERT_CONFIG_BASE = (0x08, 1)
    ALERT_HYST_BASE = (0x0C, 1)
    ALERT_LIMIT_BASE = (0x10, 2)
    DEVICE_ID_REV = (0x20, 2)

    # Backwards-compatible alias used by earlier POC code / examples.
    TcType = ThermocoupleType

    def __init__(self, bus: I2CBus, address: int = DEFAULT_ADDRESS) -> None:
        self._address = address
        self._dev: I2CDevice = bus.device(address, reg_bytes=1)

    @property
    def address(self) -> int:
        return self._address

    def _read_register(self, register: tuple[int, int]) -> bytes:
        return self._dev.read_register(register[0], length=register[1])

    def _write_register(self, register: tuple[int, int], data: bytes) -> None:
        if len(data) != register[1]:
            raise ValueError(
                f"register 0x{register[0]:02X} expects {register[1]} byte(s), got {len(data)}"
            )
        self._dev.write_register(register[0], data)

    @staticmethod
    def decode_temperature(raw: bytes) -> float:
        """Decode a 2-byte MCP9600 temperature register to °C.

        Values are 16-bit two's complement with 0.0625 °C (1/16) resolution.
        """
        if len(raw) != 2:
            raise ValueError("temperature register must be 2 bytes")
        return int.from_bytes(raw, byteorder="big", signed=True) / 16.0

    @property
    def hot_junction_c(self) -> float:
        """Hot-junction temperature in °C."""
        return self.decode_temperature(self._read_register(self.HOT_JUNC_TEMP))

    # Alias matching the earlier POC attribute name.
    @property
    def temp_hj(self) -> float:
        return self.hot_junction_c

    @property
    def cold_junction_c(self) -> float:
        """Cold-junction (ambient) temperature in °C."""
        return self.decode_temperature(self._read_register(self.COLD_JUNC_TEMP))

    @property
    def thermocouple_type(self) -> ThermocoupleType:
        register = self._read_register(self.SENSOR_CONFIG)[0]
        return ThermocoupleType((register & 0x70) >> 4)

    @thermocouple_type.setter
    def thermocouple_type(self, tctype: ThermocoupleType) -> None:
        if not isinstance(tctype, ThermocoupleType):
            raise TypeError("thermocouple_type must be a ThermocoupleType")
        sensor_config = self._read_register(self.SENSOR_CONFIG)[0]
        # Preserve filter bits [2:0]; replace thermocouple type bits [6:4].
        sensor_config = (sensor_config & 0x07) | (int(tctype) << 4)
        self._write_register(self.SENSOR_CONFIG, bytes([sensor_config]))

    @property
    def filter_coefficient(self) -> int:
        """Digital filter coefficient (0 = off … 7 = max)."""
        return self._read_register(self.SENSOR_CONFIG)[0] & 0x07

    @filter_coefficient.setter
    def filter_coefficient(self, filter_coef: int) -> None:
        if not isinstance(filter_coef, int) or not 0 <= filter_coef <= 7:
            raise ValueError("filter_coefficient must be an int in 0..7")
        sensor_config = self._read_register(self.SENSOR_CONFIG)[0]
        sensor_config = (sensor_config & 0xF8) | filter_coef
        self._write_register(self.SENSOR_CONFIG, bytes([sensor_config]))
