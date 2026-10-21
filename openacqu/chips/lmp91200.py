"""TI LMP91200 pH sensor AFE — SPI configuration / control.

Important hardware note
-----------------------
TI datasheet **Rev E** removed SPI (and earlier Rev D removed the RTD/temp
path) from the *supported* feature set. Current orderable silicon may still
contain the SPI shift register, but TI no longer documents or guarantees it
(SPI reportedly fails at ≤ ~4 °C). This driver implements the **Rev D**
16-bit configuration register for bring-up and for boards that still wire
SDI/SCLK/CSB/SDO_DIAG.

Confirm your lot / datasheet revision before relying on SPI in production.
VOUT remains analog either way — measurement still needs an ADC (MCP2221A
built-in or external I2C), which is intentionally out of scope here.

SPI: Mode 3 (CPOL=1, CPHA=1), MSB first, 16-bit frame. Configuration latches
on the rising edge of CSB.
"""

from __future__ import annotations

from enum import IntEnum

from openacqu.transport.base import SpiDevice

# Configuration register bit fields (Rev D Table 1).
_MEAS_MODE = 1 << 15
_PGA = 1 << 11
_VCM_SHIFT = 8
_VCM_MASK = 0b111 << _VCM_SHIFT
_VOCM = 1 << 7
_DIAG_EN = 1 << 6


class MeasMode(IntEnum):
    """D15 — measurement path (Rev D; temp path unsupported on Rev E)."""

    PH = 0
    TEMP = 1


class PgaGain(IntEnum):
    """D11 — PGA gain."""

    GAIN_5 = 0  # 5 V/V (default)
    GAIN_10 = 1  # 10 V/V


class VcmLevel(IntEnum):
    """D10:D8 — common-mode as a fraction of VREF."""

    VREF_7_8 = 0b011
    VREF_3_4 = 0b010
    VREF_5_8 = 0b001
    VREF_1_2 = 0b000  # default (also 0b100)
    VREF_3_8 = 0b101
    VREF_1_4 = 0b110
    VREF_1_8 = 0b111


class VocmSelect(IntEnum):
    """D7 — VOUT referred to VOCM (differential) or GND (single-ended)."""

    VOCM = 0
    GND = 1


class LMP91200:
    """SPI configuration driver for the LMP91200 AFE.

    Talks only to an :class:`~openacqu.transport.base.SpiDevice` so it can be
    unit-tested with ``FakeSpiBus`` or driven through ``SC18IS606SpiBus``.
    """

    def __init__(self, spi: SpiDevice) -> None:
        self._spi = spi
        self._config = 0x0000  # power-on defaults per Rev D

    @property
    def config(self) -> int:
        """Last configuration word written (local cache, 16-bit)."""
        return self._config & 0xFFFF

    def write_config(self, word: int, *, verify: bool = False) -> int:
        """Write a full 16-bit configuration word.

        When ``verify`` is true, clocks 32 bits in one CS frame (word + word)
        and checks that the second 16 MISO bits echo the first write (shift
        register read-back). Returns the word that was programmed.
        """
        word &= 0xFFFF
        if verify:
            tx = word.to_bytes(2, "big") * 2
            rx = self._spi.transfer(tx)
            echoed = int.from_bytes(rx[2:4], "big")
            if echoed != word:
                raise IOError(
                    f"LMP91200 config verify failed: wrote 0x{word:04X}, "
                    f"echoed 0x{echoed:04X}"
                )
        else:
            self._spi.transfer(word.to_bytes(2, "big"))
        self._config = word
        return word

    def read_config(self) -> int:
        """Read back the shift-register contents via a double transfer.

        Sends the cached config twice under one CS so SDO_DIAG echoes the
        first word. Updates and returns the local cache from the echo.
        """
        tx = self._config.to_bytes(2, "big") * 2
        rx = self._spi.transfer(tx)
        word = int.from_bytes(rx[2:4], "big")
        self._config = word
        return word

    def apply(
        self,
        *,
        meas_mode: MeasMode | int | None = None,
        pga: PgaGain | int | None = None,
        vcm: VcmLevel | int | None = None,
        vocm: VocmSelect | int | None = None,
        diag_en: bool | None = None,
        verify: bool = False,
    ) -> int:
        """Update selected fields and write the configuration register."""
        word = self._config
        if meas_mode is not None:
            word = _set_bit(word, _MEAS_MODE, int(meas_mode) != 0)
        if pga is not None:
            word = _set_bit(word, _PGA, int(pga) != 0)
        if vcm is not None:
            word = (word & ~_VCM_MASK) | ((int(vcm) & 0b111) << _VCM_SHIFT)
        if vocm is not None:
            word = _set_bit(word, _VOCM, int(vocm) != 0)
        if diag_en is not None:
            word = _set_bit(word, _DIAG_EN, bool(diag_en))
        return self.write_config(word, verify=verify)

    @property
    def meas_mode(self) -> MeasMode:
        return MeasMode.TEMP if self._config & _MEAS_MODE else MeasMode.PH

    @meas_mode.setter
    def meas_mode(self, value: MeasMode | int) -> None:
        self.apply(meas_mode=value)

    @property
    def pga(self) -> PgaGain:
        return PgaGain.GAIN_10 if self._config & _PGA else PgaGain.GAIN_5

    @pga.setter
    def pga(self, value: PgaGain | int) -> None:
        self.apply(pga=value)

    @property
    def vcm(self) -> VcmLevel:
        code = (self._config & _VCM_MASK) >> _VCM_SHIFT
        try:
            return VcmLevel(code)
        except ValueError:
            # 0b100 is also 1/2 VREF per datasheet.
            if code == 0b100:
                return VcmLevel.VREF_1_2
            raise

    @vcm.setter
    def vcm(self, value: VcmLevel | int) -> None:
        self.apply(vcm=value)

    @property
    def vocm(self) -> VocmSelect:
        return VocmSelect.GND if self._config & _VOCM else VocmSelect.VOCM

    @vocm.setter
    def vocm(self, value: VocmSelect | int) -> None:
        self.apply(vocm=value)

    @property
    def diag_en(self) -> bool:
        return bool(self._config & _DIAG_EN)

    @diag_en.setter
    def diag_en(self, value: bool) -> None:
        self.apply(diag_en=value)

    def configure_ph(
        self,
        *,
        pga: PgaGain | int = PgaGain.GAIN_5,
        vcm: VcmLevel | int = VcmLevel.VREF_1_2,
        vocm: VocmSelect | int = VocmSelect.VOCM,
        diag_en: bool = False,
        verify: bool = False,
    ) -> int:
        """Convenience: pH measurement mode with common defaults."""
        return self.apply(
            meas_mode=MeasMode.PH,
            pga=pga,
            vcm=vcm,
            vocm=vocm,
            diag_en=diag_en,
            verify=verify,
        )


def _set_bit(word: int, mask: int, enabled: bool) -> int:
    return (word | mask) if enabled else (word & ~mask)
