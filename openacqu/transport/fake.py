"""In-memory I2C / SPI buses for unit tests (no hardware required)."""

from __future__ import annotations


class FakeI2CDevice:
    """Simple register map backed by a mutable bytearray.

    Also supports raw :meth:`write` / :meth:`read` for command-style chips
    (e.g. SC18IS606). Raw writes are stored in ``last_write``; raw reads return
    ``rx_queue`` (consumed) or zeros.
    """

    def __init__(self, memory: bytearray, *, default: int = 0x00) -> None:
        self._memory = memory
        self._default = default & 0xFF
        self.last_write: bytes = b""
        self.writes: list[bytes] = []
        self.rx_queue: bytearray = bytearray()

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

    def write(self, data: bytes | list[int]) -> None:
        payload = bytes(data)
        self.last_write = payload
        self.writes.append(payload)

    def read(self, length: int = 1) -> bytes:
        if length < 1:
            raise ValueError("length must be >= 1")
        if len(self.rx_queue) >= length:
            out = bytes(self.rx_queue[:length])
            del self.rx_queue[:length]
            return out
        # Pad with zeros when the test did not stage a response.
        out = bytes(self.rx_queue) + bytes(length - len(self.rx_queue))
        self.rx_queue.clear()
        return out[:length]


class FakeI2CBus:
    """Fake bus that hands out per-address register maps."""

    def __init__(self, *, default: int = 0x00, size: int = 256) -> None:
        self._default = default & 0xFF
        self._size = size
        self._devices: dict[int, bytearray] = {}
        self._handles: dict[int, FakeI2CDevice] = {}
        self._endpoints: dict[int, object] = {}

    def memory(self, address: int) -> bytearray:
        """Return the mutable register map for ``address`` (for test setup)."""
        if address not in self._devices:
            self._devices[address] = bytearray([self._default] * self._size)
        return self._devices[address]

    def install(self, address: int, endpoint: object) -> None:
        """Install a custom endpoint (must implement the I2CDevice methods used)."""
        self._endpoints[address] = endpoint

    def handle(self, address: int) -> FakeI2CDevice:
        """Return the FakeI2CDevice for ``address`` (creates if needed)."""
        return self.device(address)  # type: ignore[return-value]

    def device(self, address: int, *, reg_bytes: int = 1) -> FakeI2CDevice:
        if address in self._endpoints:
            return self._endpoints[address]  # type: ignore[return-value]
        if reg_bytes != 1:
            raise NotImplementedError("FakeI2CBus currently supports reg_bytes=1 only")
        if address not in self._handles:
            self._handles[address] = FakeI2CDevice(
                self.memory(address), default=self._default
            )
        return self._handles[address]

    def close(self) -> None:
        """No-op for API parity with :class:`~openacqu.transport.mcp2221.MCP2221Bus`."""


class FakeSpiDevice:
    """SPI target that echoes MOSI (or returns a staged MISO queue)."""

    def __init__(self) -> None:
        self.transfers: list[bytes] = []
        self.rx_queue: bytearray = bytearray()

    def transfer(self, data: bytes | list[int]) -> bytes:
        payload = bytes(data)
        self.transfers.append(payload)
        if self.rx_queue:
            needed = len(payload)
            if len(self.rx_queue) < needed:
                self.rx_queue.extend(bytes(needed - len(self.rx_queue)))
            out = bytes(self.rx_queue[:needed])
            del self.rx_queue[:needed]
            return out
        return payload


class FakeSpiBus:
    """In-memory SPI bus for unit tests."""

    def __init__(self) -> None:
        self._devices: dict[int, FakeSpiDevice] = {}

    def device(self, chip_select: int = 0) -> FakeSpiDevice:
        if chip_select not in self._devices:
            self._devices[chip_select] = FakeSpiDevice()
        return self._devices[chip_select]
