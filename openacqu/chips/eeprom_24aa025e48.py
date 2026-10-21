"""Microchip 24AA025E48 I2C EEPROM with factory EUI-48 node address.

Reference schematic ties A0 and A1 to GND (SOT-23 A2 is absent / must be 0),
so the 7-bit I2C address is 0x50. EUI-48 lives at addresses 0xFA..0xFF.
"""

from __future__ import annotations

from openacqu.transport.base import I2CBus, I2CDevice

DEFAULT_ADDRESS = 0x50
EUI48_OFFSET = 0xFA
EUI48_LENGTH = 6
USER_MEMORY_SIZE = 0x80  # writable user area; upper block holds EUI / protect


class EEPROM24AA025E48:
    """Minimal EEPROM helper: user read/write + factory EUI-48."""

    def __init__(self, bus: I2CBus, address: int = DEFAULT_ADDRESS) -> None:
        self._address = address
        self._dev: I2CDevice = bus.device(address, reg_bytes=1)

    @property
    def address(self) -> int:
        return self._address

    def read(self, offset: int, length: int) -> bytes:
        """Read ``length`` bytes starting at EEPROM ``offset``."""
        if offset < 0 or length < 1:
            raise ValueError("offset must be >= 0 and length >= 1")
        return self._dev.read_register(offset, length=length)

    def write(self, offset: int, data: bytes | list[int]) -> None:
        """Write bytes starting at EEPROM ``offset``.

        The 24AA025E48 has an 8-byte page; callers should keep writes within a
        page (or split) when talking to real hardware. ``FakeI2CBus`` accepts
        any contiguous write.
        """
        payload = bytes(data)
        if offset < 0 or not payload:
            raise ValueError("offset must be >= 0 and data must be non-empty")
        self._dev.write_register(offset, payload)

    @property
    def eui48(self) -> bytes:
        """Factory-programmed 6-byte EUI-48 node address."""
        return self.read(EUI48_OFFSET, EUI48_LENGTH)

    @property
    def eui48_str(self) -> str:
        """EUI-48 formatted as ``AA-BB-CC-DD-EE-FF``."""
        return "-".join(f"{b:02X}" for b in self.eui48)
