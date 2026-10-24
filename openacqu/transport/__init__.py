"""I2C / SPI transport abstractions and adapters."""

from openacqu.transport.base import I2CBus, I2CDevice, SpiBus, SpiDevice
from openacqu.transport.fake import FakeI2CBus, FakeI2CDevice, FakeSpiBus, FakeSpiDevice
from openacqu.transport.mcp2221 import MCP2221Bus, USB_PID, USB_VID, open_mcp2221_bus

__all__ = [
    "I2CBus",
    "I2CDevice",
    "SpiBus",
    "SpiDevice",
    "FakeI2CBus",
    "FakeI2CDevice",
    "FakeSpiBus",
    "FakeSpiDevice",
    "MCP2221Bus",
    "USB_PID",
    "USB_VID",
    "open_mcp2221_bus",
]
