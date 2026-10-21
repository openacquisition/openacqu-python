"""EasyMCP2221-backed I2C bus adapter."""

from __future__ import annotations

from typing import Any

from openacqu.transport.base import I2CDevice


class MCP2221Device:
    """Thin wrapper around EasyMCP2221 ``I2C_Slave``."""

    def __init__(self, slave: Any) -> None:
        self._slave = slave

    def read_register(self, register: int, length: int = 1) -> bytes:
        data = self._slave.read_register(register, length=length)
        return bytes(data)

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        self._slave.write_register(register, list(data))


class MCP2221Bus:
    """I2CBus adapter over an EasyMCP2221 ``Device`` instance."""

    def __init__(self, device: Any) -> None:
        self._device = device

    @property
    def raw(self) -> Any:
        """Underlying EasyMCP2221 device (GPIO/ADC/DAC later)."""
        return self._device

    def device(self, address: int, *, reg_bytes: int = 1) -> I2CDevice:
        slave = self._device.I2C_Slave(address, reg_bytes=reg_bytes)
        return MCP2221Device(slave)


def open_mcp2221_bus() -> MCP2221Bus:
    """Open the first available MCP2221/MCP2221A and return an I2C bus."""
    import EasyMCP2221

    return MCP2221Bus(EasyMCP2221.Device())
