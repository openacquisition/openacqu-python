"""onsemi FXL6408 8-bit I2C GPIO expander (read-only product number).

On Open Acquisition boards the expander straps encode an 8-bit product
number. Software only needs to read that value; outputs are never driven.
"""

from __future__ import annotations

from openacqu.transport.base import I2CBus, I2CDevice

# ADDR pin tied to GND on the reference schematic → 7-bit address 0x43.
DEFAULT_ADDRESS = 0x43

# Input Status register (real-time pin levels). Default direction is input.
_INPUT_STATUS = 0x0F


class FXL6408:
    """Read-only view of the FXL6408 used for product identification."""

    def __init__(self, bus: I2CBus, address: int = DEFAULT_ADDRESS) -> None:
        self._address = address
        self._dev: I2CDevice = bus.device(address, reg_bytes=1)

    @property
    def address(self) -> int:
        return self._address

    def read_inputs(self) -> int:
        """Return the 8-bit Input Status register (GPIO7..GPIO0)."""
        return self._dev.read_register(_INPUT_STATUS, length=1)[0]

    @property
    def product_number(self) -> int:
        """Product number strapped on the GPIO expander inputs."""
        return self.read_inputs()
