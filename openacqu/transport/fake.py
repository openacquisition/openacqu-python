"""In-memory I2C bus for unit tests (no hardware required)."""

from __future__ import annotations


class FakeI2CDevice:
    """Simple register map backed by a mutable bytearray."""

    def __init__(self, memory: bytearray, *, default: int = 0x00) -> None:
        self._memory = memory
        self._default = default & 0xFF

    def read_register(self, register: int, length: int = 1) -> bytes:
        if length < 1:
            raise ValueError("length must be >= 1")
        end = register + length
        if end > len(self._memory):
            self._memory.extend(bytes([self._default]) * (end - len(self._memory)))
        return bytes(self._memory[register:end])

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        payload = bytes(data)
        end = register + len(payload)
        if end > len(self._memory):
            self._memory.extend(bytes([self._default]) * (end - len(self._memory)))
        self._memory[register:end] = payload


class FakeI2CBus:
    """Fake bus that hands out per-address register maps."""

    def __init__(self, *, default: int = 0x00, size: int = 256) -> None:
        self._default = default & 0xFF
        self._size = size
        self._devices: dict[int, bytearray] = {}

    def memory(self, address: int) -> bytearray:
        """Return the mutable register map for ``address`` (for test setup)."""
        if address not in self._devices:
            self._devices[address] = bytearray([self._default] * self._size)
        return self._devices[address]

    def device(self, address: int, *, reg_bytes: int = 1) -> FakeI2CDevice:
        if reg_bytes != 1:
            raise NotImplementedError("FakeI2CBus currently supports reg_bytes=1 only")
        return FakeI2CDevice(self.memory(address), default=self._default)

    def close(self) -> None:
        """No-op for API parity with :class:`~openacqu.transport.mcp2221.MCP2221Bus`."""
