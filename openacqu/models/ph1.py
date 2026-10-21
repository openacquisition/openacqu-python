"""ProbePh1 — pH probe model (AFE config over SC18IS606; ADC TBD)."""

from __future__ import annotations

from openacqu.chips.lmp91200 import LMP91200
from openacqu.chips.sc18is606 import (
    DEFAULT_ADDRESS as SC18IS606_ADDRESS,
    SC18IS606,
    SpiClock,
    SpiMode,
)
from openacqu.models.base import Probe
from openacqu.product import ProductNumber
from openacqu.transport.base import I2CBus
from openacqu.transport.mcp2221 import DEFAULT_SETTLE_S, open_mcp2221_bus


def _keepalive_interval(keepalive: bool | float) -> float | None:
    if keepalive is False:
        return None
    if keepalive is True:
        return 1.0
    interval = float(keepalive)
    if interval <= 0:
        raise ValueError("keepalive interval must be > 0")
    return interval


class ProbePh1(Probe):
    """pH probe: core peripherals + SC18IS606 + LMP91200 configuration.

    Product number on the GPIO expander is ``0x02``.

    Analog measurement (``VOUT``) is **not** included yet — choose MCP2221A
    ADC vs an external I2C ADC before wiring that path.

    Parameters
    ----------
    bus:
        Optional I2C bus. When omitted, the first MCP2221/MCP2221A is opened.
    bridge_address:
        7-bit I2C address of the SC18IS606 (default ``0x28`` with A2..A0 low).
    afe_chip_select:
        SC18IS606 CS index wired to LMP91200 CSB (0, 1, or 2).
    configure_bridge:
        When true (default), program the bridge for SPI Mode 3 / 115 kHz / MSB.
    check_product:
        When true, verify the GPIO expander product number is ``0x02``.
    keepalive / settle_s / ready_timeout_s:
        Same MCP2221 session semantics as :class:`~openacqu.models.temp1.ProbeTemp1`.
    """

    EXPECTED_PRODUCT = ProductNumber.PH

    def __init__(
        self,
        bus: I2CBus | None = None,
        *,
        bridge_address: int = SC18IS606_ADDRESS,
        afe_chip_select: int = 0,
        configure_bridge: bool = True,
        check_product: bool = False,
        keepalive: bool | float = False,
        settle_s: float = DEFAULT_SETTLE_S,
        ready_timeout_s: float = 2.0,
    ) -> None:
        owned_bus = bus is None
        if bus is None:
            bus = open_mcp2221_bus(
                keepalive_s=_keepalive_interval(keepalive),
                settle_s=settle_s,
                ready_address=bridge_address,
                ready_timeout_s=ready_timeout_s,
            )
        elif keepalive:
            start = getattr(bus, "start_keepalive", None)
            if callable(start):
                start(_keepalive_interval(keepalive) or 1.0)
            ensure = getattr(bus, "ensure_active", None)
            if callable(ensure):
                ensure(settle_s=settle_s)
            wait = getattr(bus, "wait_for_i2c", None)
            if callable(wait):
                wait(bridge_address, timeout_s=ready_timeout_s)
        try:
            super().__init__(bus)
            self.bridge = SC18IS606(self.bus, address=bridge_address)
            if configure_bridge:
                self.bridge.configure_spi(mode=SpiMode.MODE3, clock=SpiClock.KHZ_115)
            self.spi = self.bridge.as_spi_bus()
            self.afe = LMP91200(self.spi.device(afe_chip_select))
            if check_product:
                self.require_product()
        except Exception:
            if owned_bus:
                close = getattr(bus, "close", None)
                if callable(close):
                    close()
            raise
