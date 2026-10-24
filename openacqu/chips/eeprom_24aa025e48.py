"""Microchip 24AA025E48 I2C EEPROM with factory EUI-48 node address.

Reference schematic ties A0 and A1 to GND (SOT-23 A2 is absent / must be 0),
so the 7-bit I2C address is 0x50. EUI-48 lives at addresses 0xFA..0xFF.

The lower 128 bytes (0x00-0x7F) are the writable user area. The upper block
(0x80-0xFF), including the EUI-48, is permanently write-protected. Page writes
are 8 bytes and must not cross a page boundary. The write cycle is 5 ms max.
"""

from __future__ import annotations

import time

from openacqu.transport.base import I2CBus, I2CDevice

DEFAULT_ADDRESS = 0x50
EUI48_OFFSET = 0xFA
EUI48_LENGTH = 6
USER_MEMORY_SIZE = 0x80  # writable user area; upper block holds EUI / protect
PAGE_SIZE = 8
# Datasheet maximum byte/page write cycle (Twc).
WRITE_CYCLE_S = 0.005
_BLANK = 0xFF


class EEPROM24AA025E48:
    """Minimal EEPROM helper: user read/write + factory EUI-48."""

    #: Pause after each page program. Tests set this to 0.
    write_cycle_s = WRITE_CYCLE_S

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

        Writes must stay inside the user area. Payloads are split on 8-byte
        page boundaries, and each page is followed by a write-cycle wait.
        """
        payload = bytes(data)
        if offset < 0 or not payload:
            raise ValueError("offset must be >= 0 and data must be non-empty")
        end = offset + len(payload)
        if end > USER_MEMORY_SIZE:
            raise ValueError(
                "write must stay inside the user area 0x00-0x7F "
                "(0x80-0xFF, including the EUI-48, is permanently write-protected)"
            )
        pos = 0
        while pos < len(payload):
            addr = offset + pos
            room = PAGE_SIZE - (addr % PAGE_SIZE)
            chunk = payload[pos : pos + room]
            self._dev.write_register(addr, chunk)
            self._wait_write_cycle()
            pos += len(chunk)

    def erase_user(self) -> None:
        """Program the user area to the erased state (0xFF)."""
        self.write(0, bytes([_BLANK]) * USER_MEMORY_SIZE)

    def stress_user(self, pattern: bytes) -> None:
        """Erase, program ``pattern``, verify, erase, and verify the user area.

        ``pattern`` must be exactly :data:`USER_MEMORY_SIZE` bytes. The factory
        EUI-48 is read before and after and must be unchanged. A mismatch while
        checking ``pattern`` leaves that pattern in the user area. The passing
        path leaves the user area erased.
        """
        payload = bytes(pattern)
        if len(payload) != USER_MEMORY_SIZE:
            raise ValueError(f"pattern must be {USER_MEMORY_SIZE} bytes")
        eui = self.eui48
        self.erase_user()
        self._expect_user(bytes([_BLANK]) * USER_MEMORY_SIZE, "erase")
        self.write(0, payload)
        self._expect_user(payload, "data")
        self.erase_user()
        self._expect_user(bytes([_BLANK]) * USER_MEMORY_SIZE, "final erase")
        after = self.eui48
        if after != eui:
            raise ValueError(
                "EUI-48 changed from "
                f"{'-'.join(f'{b:02X}' for b in eui)} to "
                f"{'-'.join(f'{b:02X}' for b in after)}"
            )

    def _expect_user(self, expected: bytes, label: str) -> None:
        actual = self.read(0, len(expected))
        if actual == expected:
            return
        for index, (want, got) in enumerate(zip(expected, actual, strict=True)):
            if want != got:
                raise ValueError(
                    f"{label} mismatch at 0x{index:02X}: "
                    f"expected 0x{want:02X}, read 0x{got:02X}"
                )
        raise ValueError(f"{label} read {len(actual)} bytes, expected {len(expected)}")

    def _wait_write_cycle(self) -> None:
        if self.write_cycle_s > 0:
            time.sleep(self.write_cycle_s)

    @property
    def eui48(self) -> bytes:
        """Factory-programmed 6-byte EUI-48 node address."""
        return self.read(EUI48_OFFSET, EUI48_LENGTH)

    @property
    def eui48_str(self) -> str:
        """EUI-48 formatted as ``AA-BB-CC-DD-EE-FF``."""
        return "-".join(f"{b:02X}" for b in self.eui48)
