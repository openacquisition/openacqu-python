"""SC18IS606 simulator for FakeI2CBus unit tests."""

from __future__ import annotations


class FakeSC18IS606:
    """Minimal SC18IS606 command endpoint for cloud tests.

    Implements the I2CDevice surface used by :class:`~openacqu.chips.sc18is606.SC18IS606`:
    raw ``write`` / ``read`` (register methods are unused by the bridge driver).
    """

    def __init__(self) -> None:
        self.config_byte = 0x00
        self.spi_transfers: list[tuple[int, bytes]] = []  # (cs_mask, tx)
        self._buffer = b""
        self.version = b"SC18IS606-fake"
        self.commands: list[bytes] = []

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        # Treat register as Function ID for callers that use write_register.
        self.write(bytes([register & 0xFF]) + bytes(data))

    def read_register(self, register: int, length: int = 1) -> bytes:
        raise NotImplementedError("SC18IS606 uses raw read(), not read_register")

    def write(self, data: bytes | list[int]) -> None:
        payload = bytes(data)
        if not payload:
            raise ValueError("empty I2C write")
        self.commands.append(payload)
        fid = payload[0]
        body = payload[1:]
        if fid == 0xF0:
            self.config_byte = body[0] if body else 0
        elif fid == 0xF1:
            # Clear INT only; data buffer remains readable.
            pass
        elif fid == 0xF2:
            pass
        elif fid == 0xFE:
            self._buffer = self.version
        elif 0x01 <= fid <= 0x07:
            # Full-duplex echo (good enough for LMP91200 verify path).
            self.spi_transfers.append((fid & 0x07, body))
            self._buffer = body
        else:
            pass

    def read(self, length: int = 1) -> bytes:
        if length < 1:
            raise ValueError("length must be >= 1")
        if len(self._buffer) >= length:
            out = self._buffer[:length]
        else:
            out = self._buffer + bytes(length - len(self._buffer))
        return out
