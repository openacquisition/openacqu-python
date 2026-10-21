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


@runtime_checkable
class I2CBus(Protocol):
    """Factory for per-address I2C slave handles."""

    def device(self, address: int, *, reg_bytes: int = 1) -> I2CDevice:
        """Return a device handle for ``address``."""
