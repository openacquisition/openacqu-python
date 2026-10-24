"""Named colors → LED PWM helpers.

Pipeline (intentionally layered):

1. Resolve a CSS/HTML color name (or hex) to **sRGB** via ``webcolors``.
2. Decode sRGB to **linear light**.
3. Apply per-channel **gains** (LED luminous-intensity white balance).
4. Scale by **brightness**, optionally through CIE L* or γ=2.2 so dimming
   tracks perceived brightness rather than raw flux.
5. Quantize to 8-bit PWM (flux ∝ duty for constant-current PWM sinks).

The name table itself is not modified for eye/LED physics — corrections live
in :class:`LedColorProfile`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import webcolors

# Würth 150141M173100 typical Iv @ 20 mA (mcd): R=270, G=950, B=230.
# Gains normalize to the weakest channel (blue) so equal sRGB channels
# approximate equal luminous intensity contribution.
_IV_R_MCD = 270.0
_IV_G_MCD = 950.0
_IV_B_MCD = 230.0
_IV_MIN = min(_IV_R_MCD, _IV_G_MCD, _IV_B_MCD)


class PerceptualMode(str, Enum):
    """How ``brightness`` maps to linear luminance before PWM."""

    NONE = "none"  # brightness is linear flux scale
    CIE_LSTAR = "cie_lstar"  # brightness is CIE L* lightness 0..1
    GAMMA_22 = "gamma22"  # brightness ** 2.2 approximation


@dataclass(frozen=True)
class LedColorProfile:
    """LED-specific transform applied after sRGB resolution."""

    red_gain: float = 1.0
    green_gain: float = 1.0
    blue_gain: float = 1.0
    perceptual: PerceptualMode = PerceptualMode.CIE_LSTAR

    def __post_init__(self) -> None:
        for name, value in (
            ("red_gain", self.red_gain),
            ("green_gain", self.green_gain),
            ("blue_gain", self.blue_gain),
        ):
            if value < 0:
                raise ValueError(f"{name} must be >= 0")
        if not isinstance(self.perceptual, PerceptualMode):
            object.__setattr__(self, "perceptual", PerceptualMode(self.perceptual))


# No LED/eye correction — sRGB decoded to linear, then to PWM.
UNITY_PROFILE = LedColorProfile(
    red_gain=1.0,
    green_gain=1.0,
    blue_gain=1.0,
    perceptual=PerceptualMode.NONE,
)

# Default for the probe RGB LED (Würth 150141M173100) + CIE L* dimming.
PROBE_RGB_PROFILE = LedColorProfile(
    red_gain=_IV_MIN / _IV_R_MCD,
    green_gain=_IV_MIN / _IV_G_MCD,
    blue_gain=_IV_MIN / _IV_B_MCD,
    perceptual=PerceptualMode.CIE_LSTAR,
)

DEFAULT_PROFILE = PROBE_RGB_PROFILE

# Indicator hues, in cycle order. Green is full-scale #00ff00 (CSS "green" is
# #008000 and comes out very dim).
INDICATOR_COLORS: tuple[tuple[str, str], ...] = (
    ("red", "#ff0000"),
    ("yellow", "#ffff00"),
    ("green", "#00ff00"),
    ("blue", "#0000ff"),
    ("magenta", "#ff00ff"),
    ("white", "#ffffff"),
)


def indicator_sequence(start: str | None = None) -> tuple[tuple[str, str], ...]:
    """Return :data:`INDICATOR_COLORS`, rotated so ``start`` is first.

    ``start`` is a palette name. The default sequence begins at red. Every
    color is still included once.
    """
    if start is None:
        return INDICATOR_COLORS
    key = start.strip().lower()
    names = [name for name, _color in INDICATOR_COLORS]
    try:
        index = names.index(key)
    except ValueError as exc:
        raise ValueError(
            f"unknown indicator color {start!r}; choose from {', '.join(names)}"
        ) from exc
    return INDICATOR_COLORS[index:] + INDICATOR_COLORS[:index]


def named_colors() -> list[str]:
    """CSS3 color names supported by ``webcolors`` (lowercase, sorted)."""
    return sorted(webcolors.names(spec=webcolors.CSS3))


def parse_color(color: str | Iterable[int]) -> tuple[int, int, int]:
    """Parse a CSS name, ``#rrggbb`` / ``#rgb``, or an RGB iterable to 0–255 sRGB."""
    if isinstance(color, str):
        text = color.strip()
        if text.startswith("#"):
            rgb = webcolors.hex_to_rgb(text)
            return int(rgb.red), int(rgb.green), int(rgb.blue)
        try:
            rgb = webcolors.name_to_rgb(text, spec=webcolors.CSS3)
        except ValueError as exc:
            raise ValueError(f"unknown color name {color!r}") from exc
        return int(rgb.red), int(rgb.green), int(rgb.blue)

    values = list(color)
    if len(values) != 3:
        raise ValueError("RGB color must have three components")
    out: list[int] = []
    for name, value in zip(("red", "green", "blue"), values, strict=True):
        if not isinstance(value, int) or not 0 <= value <= 255:
            raise ValueError(f"{name} must be an int in 0..255")
        out.append(value)
    return out[0], out[1], out[2]


def srgb_to_linear(component: float) -> float:
    """Decode one sRGB channel in 0..1 to linear light (IEC 61966-2-1)."""
    if component <= 0.04045:
        return component / 12.92
    return ((component + 0.055) / 1.055) ** 2.4


def lightness_to_luminance(lightness: float) -> float:
    """Map CIE L* lightness in 0..1 to relative luminance Y in 0..1."""
    if not 0.0 <= lightness <= 1.0:
        raise ValueError("lightness must be in 0..1")
    l_star = lightness * 100.0
    if l_star > 8.0:
        return ((l_star + 16.0) / 116.0) ** 3
    return l_star / 903.3


def brightness_to_scale(brightness: float, mode: PerceptualMode) -> float:
    """Convert a 0..1 brightness knob to a linear luminance scale factor."""
    if not 0.0 <= brightness <= 1.0:
        raise ValueError("brightness must be in 0..1")
    if mode is PerceptualMode.NONE:
        return brightness
    if mode is PerceptualMode.GAMMA_22:
        return brightness**2.2
    if mode is PerceptualMode.CIE_LSTAR:
        return lightness_to_luminance(brightness)
    raise ValueError(f"unsupported perceptual mode: {mode!r}")


def _linear_srgb(color: str) -> tuple[float, float, float]:
    red, green, blue = parse_color(color)
    return (
        srgb_to_linear(red / 255.0),
        srgb_to_linear(green / 255.0),
        srgb_to_linear(blue / 255.0),
    )


def _pwm_from_linear(
    linear: tuple[float, float, float],
    *,
    brightness: float,
    profile: LedColorProfile,
) -> tuple[int, int, int]:
    """Apply LED gains and the brightness scale, then quantize to PWM."""
    scale = brightness_to_scale(brightness, profile.perceptual)
    gains = (profile.red_gain, profile.green_gain, profile.blue_gain)
    pwm: list[int] = []
    for channel, gain in zip(linear, gains, strict=True):
        level = channel * gain * scale * 255.0
        pwm.append(max(0, min(255, int(round(level)))))
    return pwm[0], pwm[1], pwm[2]


def resolve_to_pwm(
    color: str | Iterable[int],
    *,
    brightness: float = 1.0,
    profile: LedColorProfile = DEFAULT_PROFILE,
) -> tuple[int, int, int]:
    """Resolve a named/hex/RGB color to 8-bit LED PWM using ``profile``."""
    if isinstance(color, str):
        linear = _linear_srgb(color)
    else:
        red, green, blue = parse_color(color)
        linear = (
            srgb_to_linear(red / 255.0),
            srgb_to_linear(green / 255.0),
            srgb_to_linear(blue / 255.0),
        )
    return _pwm_from_linear(linear, brightness=brightness, profile=profile)


def _indicator_linear() -> dict[str, tuple[float, float, float]]:
    """Scale each indicator so the sum of its linear channels matches a primary.

    After the LED gains, luminous intensity is proportional to that sum: the
    gains cancel the per-die mcd, and the mcd figures already include the
    photopic eye response. Primaries sum to 1 and are left alone. White sums
    to 3 and is scaled by 1/3. Chromaticity is preserved.
    """
    raw = {name: _linear_srgb(color) for name, color in INDICATOR_COLORS}
    target = min(sum(channels) for channels in raw.values())
    return {
        name: tuple(channel * target / sum(channels) for channel in channels)
        for name, channels in raw.items()
    }


_INDICATOR_LINEAR = _indicator_linear()


def indicator_pwm(
    name: str,
    *,
    brightness: float = 1.0,
    profile: LedColorProfile = DEFAULT_PROFILE,
) -> tuple[int, int, int]:
    """PWM for one indicator color, matched in luminance to the others."""
    key = name.strip().lower()
    try:
        linear = _INDICATOR_LINEAR[key]
    except KeyError as exc:
        names = ", ".join(color_name for color_name, _color in INDICATOR_COLORS)
        raise ValueError(f"unknown indicator color {name!r}; choose from {names}") from exc
    return _pwm_from_linear(linear, brightness=brightness, profile=profile)
