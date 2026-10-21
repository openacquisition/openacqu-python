"""ProbeTemp1 — thermocouple temperature probe model."""

from __future__ import annotations

from openacqu.chips.mcp9600 import DEFAULT_ADDRESS, MCP9600
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
    keepalive:
        When opening a real MCP2221 bus: ``True`` enables a 1.0 s HID keep-alive,
        or pass a positive interval in seconds.
    settle_s:
        Post-open delay after HID resume for a USBCFG-gated load switch.
    ready_timeout_s:
        How long to wait for the MCP9600 to ACK after open/resume.
    """

    EXPECTED_PRODUCT = ProductNumber.TEMPERATURE

    def __init__(
        self,
        bus: I2CBus | None = None,
        *,
        mcp9600_address: int = DEFAULT_ADDRESS,
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
                ready_address=mcp9600_address,
                ready_timeout_s=ready_timeout_s,
            )
        elif keepalive:
            start = getattr(bus, "start_keepalive", None)
            if callable(start):
                start(_keepalive_interval(keepalive) or 1.0)
            # Injected real bus: still give the switched rail a chance.
            ensure = getattr(bus, "ensure_active", None)
            if callable(ensure):
                ensure(settle_s=settle_s)
            wait = getattr(bus, "wait_for_i2c", None)
            if callable(wait):
                wait(mcp9600_address, timeout_s=ready_timeout_s)
        try:
            super().__init__(bus)
            self.thermocouple = MCP9600(self.bus, address=mcp9600_address)
            if check_product:
                self.require_product()
        except Exception:
            if owned_bus:
                close = getattr(bus, "close", None)
                if callable(close):
                    close()
            raise

    @property
    def temperature_c(self) -> float:
        """Hot-junction temperature in °C (common-case convenience)."""
        return self.thermocouple.hot_junction_c
