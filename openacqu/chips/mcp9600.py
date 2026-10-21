"""Microchip MCP9600 thermocouple EMF-to-temperature converter.

Targets the MCP9600T-E/MX (and other MCP9600/L00/RL00 variants). Open-circuit
detection is via STATUS bit 4 (Input Range); the MCP9601's dedicated OC/SC
alert pins are not present on this part.
"""

from __future__ import annotations

import time
from enum import IntEnum

from openacqu.transport.base import I2CBus, I2CDevice

# Default ADDR-pin configuration used on ProbeTemp1 hardware.
DEFAULT_ADDRESS = 0x67
EXPECTED_DEVICE_ID = 0x40

_STATUS_BURST_COMPLETE = 0x80
_STATUS_TH_UPDATE = 0x40
_STATUS_INPUT_RANGE = 0x10  # open-circuit / out-of-range on MCP9600


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


class AdcResolution(IntEnum):
    """ADC measurement resolution (DEVICE_CONFIG bits 6:5)."""

    BITS_18 = 0b00  # ~320 ms conversion
    BITS_16 = 0b01  # ~80 ms
    BITS_14 = 0b10  # ~20 ms
    BITS_12 = 0b11  # ~5 ms


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

    # --- Temperature ---------------------------------------------------------

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

    # --- Status / data-ready / open-circuit ----------------------------------

    @property
    def status(self) -> int:
        """Raw STATUS register value."""
        return self._read_register(self.STATUS)[0]

    @property
    def temperature_ready(self) -> bool:
        """True when STATUS.TH_UPDATE indicates a fresh conversion."""
        return bool(self.status & _STATUS_TH_UPDATE)

    @property
    def open_circuit(self) -> bool:
        """True when STATUS input-range / open-circuit flag is set.

        On the MCP9600 this is STATUS bit 4 (Input Range). A disconnected
        thermocouple typically drives the EMF out of range and sets this bit.
        """
        return bool(self.status & _STATUS_INPUT_RANGE)

    def clear_temperature_ready(self) -> None:
        """Clear STATUS.TH_UPDATE so the next conversion can be polled."""
        status = self.status & ~_STATUS_TH_UPDATE
        self._write_register(self.STATUS, bytes([status]))

    def wait_for_temperature(self, *, timeout_s: float = 1.0, poll_s: float = 0.01) -> None:
        """Clear TH_UPDATE, then wait until the next conversion completes.

        Raises
        ------
        TimeoutError
            If ``timeout_s`` elapses before TH_UPDATE is set again.
        """
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if poll_s <= 0:
            raise ValueError("poll_s must be > 0")
        self.clear_temperature_ready()
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.temperature_ready:
                return
            time.sleep(poll_s)
        raise TimeoutError(
            f"MCP9600 temperature conversion not ready within {timeout_s:.3f}s"
        )

    def read_hot_junction_c(self, *, wait: bool = True, timeout_s: float = 1.0) -> float:
        """Read hot-junction °C, optionally waiting for a fresh conversion."""
        if wait:
            self.wait_for_temperature(timeout_s=timeout_s)
        return self.hot_junction_c

    # --- Sensor config -------------------------------------------------------

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

    # --- Device config / ADC resolution --------------------------------------

    @property
    def adc_resolution(self) -> AdcResolution:
        """ADC measurement resolution (18 / 16 / 14 / 12 bit)."""
        register = self._read_register(self.DEVICE_CONFIG)[0]
        return AdcResolution((register >> 5) & 0x03)

    @adc_resolution.setter
    def adc_resolution(self, resolution: AdcResolution) -> None:
        if not isinstance(resolution, AdcResolution):
            raise TypeError("adc_resolution must be an AdcResolution")
        config = self._read_register(self.DEVICE_CONFIG)[0]
        config = (config & 0x9F) | (int(resolution) << 5)
        self._write_register(self.DEVICE_CONFIG, bytes([config]))

    # --- Device ID / revision ------------------------------------------------

    def read_device_id_revision(self) -> tuple[int, int]:
        """Return ``(device_id, revision)`` from register 0x20.

        MCP9600 family device ID is ``0x40``. Revision high nibble = major,
        low nibble = minor (``0x10`` = rev 1.0).
        """
        raw = self._read_register(self.DEVICE_ID_REV)
        return raw[0], raw[1]

    @property
    def device_id(self) -> int:
        return self.read_device_id_revision()[0]

    @property
    def revision(self) -> int:
        return self.read_device_id_revision()[1]

    @property
    def revision_str(self) -> str:
        rev = self.revision
        return f"{(rev >> 4) & 0x0F}.{rev & 0x0F}"

    def identify(self, *, expected_id: int = EXPECTED_DEVICE_ID) -> tuple[int, int]:
        """Read ID/revision and raise if ``device_id`` is unexpected."""
        device_id, revision = self.read_device_id_revision()
        if device_id != expected_id:
            raise LookupError(
                f"unexpected MCP9600 device ID 0x{device_id:02X} "
                f"(expected 0x{expected_id:02X})"
            )
        return device_id, revision
