"""Texas Instruments LP5817 3-channel I2C RGB LED driver.

Schematic mapping (common-anode RGB LED):
  OUT0 → LED_R, OUT1 → LED_G, OUT2 → LED_B

The part answers at two 7-bit addresses. This driver uses the independent
address. The broadcast address is shared with the LP5814, LP5815, and LP5816
and is recorded here so a bus scan can name it.
"""

from __future__ import annotations

from collections.abc import Iterable

from openacqu.colors import DEFAULT_PROFILE, LedColorProfile, resolve_to_pwm
from openacqu.transport.base import I2CBus, I2CDevice

DEFAULT_ADDRESS = 0x2D
# Family broadcast address (LP5814/LP5815/LP5816/LP5817). Not used by this driver.
BROADCAST_ADDRESS = 0x34

_CHIP_EN = 0x00
_DEV_CONFIG0 = 0x01
_DEV_CONFIG1 = 0x02
_UPDATE_CMD = 0x0F
_OUT0_DC = 0x14
_OUT1_DC = 0x15
_OUT2_DC = 0x16
_OUT0_PWM = 0x18
_OUT1_PWM = 0x19
_OUT2_PWM = 0x1A

_UPDATE_MAGIC = 0x55
_CHIP_EN_BIT = 0x01
_ALL_OUTPUTS_EN = 0x07  # OUT2|OUT1|OUT0


class LP5817:
    """RGB LED driver with a small high-level color API."""

    def __init__(
        self,
        bus: I2CBus,
        address: int = DEFAULT_ADDRESS,
        *,
        color_profile: LedColorProfile = DEFAULT_PROFILE,
    ) -> None:
        self._address = address
        self._dev: I2CDevice = bus.device(address, reg_bytes=1)
        self._initialized = False
        self.color_profile = color_profile

    @property
    def address(self) -> int:
        return self._address

    def _write(self, register: int, value: int) -> None:
        self._dev.write_register(register, bytes([value & 0xFF]))

    def _read(self, register: int) -> int:
        return self._dev.read_register(register, length=1)[0]

    def update(self) -> None:
        """Latch DEV_CONFIG* changes (required while CHIP_EN=1)."""
        self._write(_UPDATE_CMD, _UPDATE_MAGIC)

    def enable(self, on: bool = True) -> None:
        """Enable or disable the device (CHIP_EN)."""
        self._write(_CHIP_EN, _CHIP_EN_BIT if on else 0x00)

    def initialize(self, *, max_current_51ma: bool = False, dot_current: int = 0xFF) -> None:
        """Power up outputs and set full-scale dot current on all channels.

        Safe to call more than once. PWM starts at 0 (LED off).
        """
        if not 0 <= dot_current <= 0xFF:
            raise ValueError("dot_current must be in 0..255")
        self.enable(True)
        self._write(_DEV_CONFIG0, 0x01 if max_current_51ma else 0x00)
        self._write(_DEV_CONFIG1, _ALL_OUTPUTS_EN)
        self.update()
        for reg in (_OUT0_DC, _OUT1_DC, _OUT2_DC):
            self._write(reg, dot_current)
        for reg in (_OUT0_PWM, _OUT1_PWM, _OUT2_PWM):
            self._write(reg, 0x00)
        self._initialized = True

    def _ensure_init(self) -> None:
        if not self._initialized:
            self.initialize()

    def set_pwm(self, red: int, green: int, blue: int) -> None:
        """Set per-channel 8-bit PWM (OUT0=R, OUT1=G, OUT2=B)."""
        for name, value in (("red", red), ("green", green), ("blue", blue)):
            if not isinstance(value, int) or not 0 <= value <= 255:
                raise ValueError(f"{name} must be an int in 0..255")
        self._ensure_init()
        self._write(_OUT0_PWM, red)
        self._write(_OUT1_PWM, green)
        self._write(_OUT2_PWM, blue)

    def set_rgb(self, red: int, green: int, blue: int) -> None:
        """Set raw PWM (no named-color / perceptual transform)."""
        self.set_pwm(red, green, blue)

    def set_color(
        self,
        color: str | Iterable[int],
        *,
        brightness: float = 1.0,
        profile: LedColorProfile | None = None,
    ) -> tuple[int, int, int]:
        """Set LED from a CSS name, ``#rrggbb``, or RGB triple.

        Applies :attr:`color_profile` (LED gains + perceptual brightness)
        unless ``profile`` is passed. Returns the PWM triple written.
        """
        pwm = resolve_to_pwm(
            color,
            brightness=brightness,
            profile=profile if profile is not None else self.color_profile,
        )
        self.set_pwm(*pwm)
        return pwm

    def off(self) -> None:
        """Turn all channels off (PWM = 0)."""
        self.set_pwm(0, 0, 0)

    def get_pwm(self) -> tuple[int, int, int]:
        """Return current (red, green, blue) PWM values."""
        return (
            self._read(_OUT0_PWM),
            self._read(_OUT1_PWM),
            self._read(_OUT2_PWM),
        )
