"""Transport protocols used by chip drivers and probe models."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class I2CDevice(Protocol):
    """Register-oriented view of a single I2C slave."""

    def read_register(self, register: int, length: int = 1) -> bytes:
        """Read ``length`` bytes starting at ``register``."""

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        """Write ``data`` starting at ``register``."""

    def write(self, data: bytes | list[int]) -> None:
        """Write raw bytes to the slave (no register address prefix)."""

    def read(self, length: int = 1) -> bytes:
        """Read raw bytes from the slave (no register address prefix)."""


@runtime_checkable
class I2CBus(Protocol):
    """Factory for per-address I2C slave handles."""

    def device(self, address: int, *, reg_bytes: int = 1) -> I2CDevice:
        """Return a device handle for ``address``."""


@runtime_checkable
class SpiDevice(Protocol):
    """Full-duplex SPI target selected by chip-select."""

    def transfer(self, data: bytes | list[int]) -> bytes:
        """Clock ``data`` out and return the same number of bytes clocked in."""


@runtime_checkable
class SpiBus(Protocol):
    """Factory for per-chip-select SPI device handles."""

    def device(self, chip_select: int = 0) -> SpiDevice:
        """Return a device handle for ``chip_select`` (0-based index)."""
