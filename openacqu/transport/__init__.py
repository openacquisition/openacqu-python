"""I2C transport abstractions and adapters."""

from openacqu.transport.base import I2CBus, I2CDevice
from openacqu.transport.fake import FakeI2CBus, FakeI2CDevice
from openacqu.transport.mcp2221 import MCP2221Bus, open_mcp2221_bus

__all__ = [
    "I2CBus",
    "I2CDevice",
    "FakeI2CBus",
    "FakeI2CDevice",
    "MCP2221Bus",
    "open_mcp2221_bus",
]
