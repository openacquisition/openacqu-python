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


def resolve_to_pwm(
    color: str | Iterable[int],
    *,
    brightness: float = 1.0,
    profile: LedColorProfile = DEFAULT_PROFILE,
) -> tuple[int, int, int]:
    """Resolve a named/hex/RGB color to 8-bit LED PWM using ``profile``."""
    r_s, g_s, b_s = parse_color(color)
    scale = brightness_to_scale(brightness, profile.perceptual)
    gains = (profile.red_gain, profile.green_gain, profile.blue_gain)

    pwm: list[int] = []
    for srgb8, gain in zip((r_s, g_s, b_s), gains, strict=True):
        linear = srgb_to_linear(srgb8 / 255.0) * gain * scale
        pwm.append(max(0, min(255, int(round(linear * 255.0)))))
    return pwm[0], pwm[1], pwm[2]
