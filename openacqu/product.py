"""Product numbers encoded on the FXL6408 GPIO expander."""

from __future__ import annotations

from enum import IntEnum


class ProductNumber(IntEnum):
    """8-bit product identity read from the GPIO expander Input Status."""

    TEMPERATURE = 0x01
    PH = 0x02
