"""Tests for named-color → LED PWM resolution."""

from __future__ import annotations

import pytest

from openacqu.colors import (
    INDICATOR_COLORS,
    PROBE_RGB_PROFILE,
    UNITY_PROFILE,
    LedColorProfile,
    PerceptualMode,
    brightness_to_scale,
    indicator_pwm,
    indicator_sequence,
    lightness_to_luminance,
    named_colors,
    parse_color,
    resolve_to_pwm,
    srgb_to_linear,
)
from openacqu.transport.fake import FakeI2CBus
from openacqu.chips.lp5817 import LP5817


def test_parse_css_name_and_hex() -> None:
    assert parse_color("red") == (255, 0, 0)
    assert parse_color("#00ff00") == (0, 255, 0)
    assert parse_color("#00f") == (0, 0, 255)
    assert parse_color((1, 2, 3)) == (1, 2, 3)


def test_named_colors_includes_css3_basics() -> None:
    names = named_colors()
    assert "orange" in names
    assert "steelblue" in names
    assert len(names) >= 140


def test_unity_profile_full_red() -> None:
    # Linear decode of sRGB 255 is 1.0 → PWM 255 with unity gains.
    assert resolve_to_pwm("red", profile=UNITY_PROFILE) == (255, 0, 0)


def test_probe_profile_attenuates_green_vs_blue() -> None:
    # Green Iv is much higher than blue; gain should suppress green PWM.
    r, g, b = resolve_to_pwm("white", brightness=1.0, profile=PROBE_RGB_PROFILE)
    assert b == 255
    assert g < r < b
    assert g < 80  # ~230/950 of full scale


def test_cie_lstar_half_brightness_darker_than_linear() -> None:
    linear_half = brightness_to_scale(0.5, PerceptualMode.NONE)
    lstar_half = brightness_to_scale(0.5, PerceptualMode.CIE_LSTAR)
    gamma_half = brightness_to_scale(0.5, PerceptualMode.GAMMA_22)
    assert linear_half == 0.5
    assert lstar_half < 0.5
    assert gamma_half < 0.5
    assert abs(lightness_to_luminance(1.0) - 1.0) < 1e-9


def test_srgb_to_linear_endpoints() -> None:
    assert srgb_to_linear(0.0) == 0.0
    assert abs(srgb_to_linear(1.0) - 1.0) < 1e-9


def test_lp5817_set_color() -> None:
    bus = FakeI2CBus()
    led = LP5817(bus, color_profile=UNITY_PROFILE)
    assert led.set_color("blue", brightness=1.0) == (0, 0, 255)
    assert led.get_pwm() == (0, 0, 255)
    led.set_color("#ff0000", brightness=0.0)
    assert led.get_pwm() == (0, 0, 0)


def test_indicator_sequence_rotates_and_keeps_every_color() -> None:
    assert [name for name, _color in indicator_sequence()] == [
        "red",
        "yellow",
        "green",
        "blue",
        "magenta",
        "white",
    ]
    assert indicator_sequence()[2] == ("green", "#00ff00")
    assert indicator_sequence()[1] == ("yellow", "#ffff00")
    assert indicator_sequence()[4] == ("magenta", "#ff00ff")
    rotated = indicator_sequence("Blue")
    assert rotated[0][0] == "blue"
    assert [name for name, _color in rotated] == [
        "blue",
        "magenta",
        "white",
        "red",
        "yellow",
        "green",
    ]
    assert len(rotated) == len(INDICATOR_COLORS)
    with pytest.raises(ValueError, match="unknown indicator color"):
        indicator_sequence("pink")


def test_indicator_colors_match_luminance() -> None:
    """Each indicator's gain-adjusted drive sums to the same luminous intensity."""
    totals: list[float] = []
    gains = (
        PROBE_RGB_PROFILE.red_gain,
        PROBE_RGB_PROFILE.green_gain,
        PROBE_RGB_PROFILE.blue_gain,
    )
    for name, _color in INDICATOR_COLORS:
        pwm = indicator_pwm(name, profile=PROBE_RGB_PROFILE)
        totals.append(sum(channel / 255.0 / gain for channel, gain in zip(pwm, gains, strict=True)))
    assert max(totals) - min(totals) < 0.03
    # Primaries are the reference level, so red is unchanged by the match.
    assert indicator_pwm("red") == resolve_to_pwm("#ff0000")
    # White used to be about 3x a primary. The matched level is about 1x.
    assert sum(indicator_pwm("white")) < sum(resolve_to_pwm("#ffffff")) / 2


def test_unknown_color_raises() -> None:
    with pytest.raises(ValueError, match="unknown color name"):
        parse_color("not-a-real-color")


def test_profile_rejects_negative_gain() -> None:
    with pytest.raises(ValueError):
        LedColorProfile(red_gain=-0.1)
