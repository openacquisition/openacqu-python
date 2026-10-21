"""Shared probe model base with core I2C peripherals."""

from __future__ import annotations

from types import TracebackType
from typing import TypeVar

from openacqu.chips.eeprom_24aa025e48 import EEPROM24AA025E48
from openacqu.chips.fxl6408 import FXL6408
from openacqu.chips.lp5817 import LP5817
from openacqu.product import ProductNumber
from openacqu.transport.base import I2CBus

ProbeT = TypeVar("ProbeT", bound="Probe")


class Probe:
    """Base class for product models.

    Every Open Acquisition probe shares:

    * MCP2221A USB↔I2C bridge (injected as ``bus``)
    * LP5817 RGB LED driver
    * 24AA025E48 EEPROM (EUI-48 + user storage)
    * FXL6408 GPIO expander encoding the product number (read-only)

    Prefer ``with ProbeTemp1() as probe:`` so the HID handle is released even
    if the script exits early (important when USBCFG gates peripheral power).
    """

    #: Subclasses set this to the product number they expect on the expander.
    EXPECTED_PRODUCT: ProductNumber | int | None = None

    def __init__(self, bus: I2CBus) -> None:
        self._bus = bus
        self._closed = False
        self.led = LP5817(bus)
        self.eeprom = EEPROM24AA025E48(bus)
        self.gpio_expander = FXL6408(bus)

    @property
    def bus(self) -> I2CBus:
        """I2C bus used by this probe."""
        return self._bus

    @property
    def product_number(self) -> int:
        """8-bit product number from the GPIO expander (read-only)."""
        return self.gpio_expander.product_number

    def require_product(self, expected: ProductNumber | int | None = None) -> int:
        """Read the product number and raise if it does not match ``expected``.

        When ``expected`` is omitted, uses the subclass ``EXPECTED_PRODUCT``.
        """
        if expected is None:
            expected = self.EXPECTED_PRODUCT
        if expected is None:
            raise ValueError("no expected product number provided")
        actual = self.product_number
        if actual != int(expected):
            raise LookupError(
                f"product number mismatch: expected 0x{int(expected):02X}, "
                f"found 0x{actual:02X}"
            )
        return actual

    def close(self) -> None:
        """Release transport resources if the bus supports it."""
        if self._closed:
            return
        self._closed = True
        close = getattr(self._bus, "close", None)
        if callable(close):
            close()

    def __enter__(self: ProbeT) -> ProbeT:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
