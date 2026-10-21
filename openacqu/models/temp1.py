"""ProbeTemp1 — thermocouple temperature probe model."""

from __future__ import annotations

from openacqu.chips.mcp9600 import DEFAULT_ADDRESS, MCP9600
from openacqu.models.base import Probe
from openacqu.product import ProductNumber
from openacqu.transport.base import I2CBus
from openacqu.transport.mcp2221 import open_mcp2221_bus


class ProbeTemp1(Probe):
    """Temperature probe built around an MCP9600 thermocouple converter.

    Product number on the GPIO expander is ``0x01``.

    Parameters
    ----------
    bus:
        Optional I2C bus. When omitted, the first MCP2221/MCP2221A is opened.
        Pass a ``FakeI2CBus`` (or any ``I2CBus``) in tests.
    mcp9600_address:
        7-bit I2C address of the MCP9600 (depends on ADDR pins; default 0x67).
    check_product:
        When true, verify the GPIO expander product number is ``0x01``.
    """

    EXPECTED_PRODUCT = ProductNumber.TEMPERATURE

    def __init__(
        self,
        bus: I2CBus | None = None,
        *,
        mcp9600_address: int = DEFAULT_ADDRESS,
        check_product: bool = False,
    ) -> None:
        super().__init__(bus if bus is not None else open_mcp2221_bus())
        self.thermocouple = MCP9600(self.bus, address=mcp9600_address)
        if check_product:
            self.require_product()

    @property
    def temperature_c(self) -> float:
        """Hot-junction temperature in °C (common-case convenience)."""
        return self.thermocouple.hot_junction_c
