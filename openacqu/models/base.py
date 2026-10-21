"""Shared probe model base.

All Open Acquisition models share an MCP2221A bridge plus core peripherals
(LED driver, EEPROM, GPIO expander used for hardware revision). Those
peripherals are stubbed here and will be enabled after the initial refactor.
"""

from __future__ import annotations

from openacqu.transport.base import I2CBus


class Probe:
    """Base class for product models.

    Subclasses receive an :class:`~openacqu.transport.base.I2CBus` and attach
    model-specific sensor drivers. Shared core peripherals will hang off this
    class once implemented.
    """

    def __init__(self, bus: I2CBus) -> None:
        self._bus = bus
        # Future core peripherals (not yet implemented):
        # self._led = ...
        # self._eeprom = ...
        # self._gpio_expander = ...

    @property
    def bus(self) -> I2CBus:
        """I2C bus used by this probe."""
        return self._bus

    def hardware_revision(self) -> int:
        """Read the hardware revision via the GPIO expander.

        Not implemented yet; reserved so model APIs can grow in one place.
        """
        raise NotImplementedError(
            "GPIO expander hardware-revision support is not implemented yet"
        )

    def close(self) -> None:
        """Release transport resources if the bus supports it."""
        close = getattr(self._bus, "close", None)
        if callable(close):
            close()
