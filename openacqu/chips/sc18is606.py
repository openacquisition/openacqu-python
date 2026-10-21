"""NXP SC18IS606 I2C-to-SPI bridge.

The bridge is an I2C target that drives an SPI controller with up to three
chip-selects. Open Acquisition uses it so SPI-only AFEs (e.g. LMP91200) can
stay on the MCP2221A HID/I2C core without switching to MCP2222.

I2C address (7-bit) is ``0b0101_A2A1A0`` latched from pins A2..A0 at reset.
With A2/A1/A0 grounded the address is ``0x28`` (8-bit write address ``0x50``).
That does **not** collide with the 24AA025E48 EEPROM at 7-bit ``0x50``.

Protocol (simplified):

* Write ``[Function ID] + payload`` to the bridge
* While an SPI transfer runs the bridge NACKs its address
* After completion, I2C-read the buffer (no Function ID) to get MISO bytes
* Optional ``0xF1`` clears the INT pin
"""

from __future__ import annotations

import time
from enum import IntEnum

from openacqu.transport.base import I2CBus, I2CDevice, SpiDevice

# A2=A1=A0=0 → 0b0101000
DEFAULT_ADDRESS = 0x28
BUFFER_MAX = 1024

_FID_CONFIG = 0xF0
_FID_CLEAR_INT = 0xF1
_FID_IDLE = 0xF2
_FID_VERSION = 0xFE


class SpiMode(IntEnum):
    """SPI clock polarity / phase (SC18IS606 MODE1:MODE0)."""

    MODE0 = 0b00  # CPOL=0, CPHA=0
    MODE1 = 0b01  # CPOL=0, CPHA=1
    MODE2 = 0b10  # CPOL=1, CPHA=0
    MODE3 = 0b11  # CPOL=1, CPHA=1


class SpiClock(IntEnum):
    """SPI bit rate (SC18IS606 F1:F0)."""

    KHZ_1875 = 0b00
    KHZ_455 = 0b01
    KHZ_115 = 0b10
    KHZ_58 = 0b11


class SC18IS606:
    """Low-level driver for the SC18IS606 bridge on an :class:`I2CBus`."""

    def __init__(self, bus: I2CBus, address: int = DEFAULT_ADDRESS) -> None:
        self._address = address
        self._bus = bus
        self._dev: I2CDevice = bus.device(address, reg_bytes=1)
        self._config_byte = 0x00

    @property
    def address(self) -> int:
        return self._address

    @property
    def config_byte(self) -> int:
        """Last value written by :meth:`configure_spi` (local cache)."""
        return self._config_byte

    def configure_spi(
        self,
        *,
        mode: SpiMode | int = SpiMode.MODE3,
        clock: SpiClock | int = SpiClock.KHZ_115,
        lsb_first: bool = False,
    ) -> int:
        """Program SPI mode, bit order, and clock. Returns the config byte."""
        mode_i = int(mode) & 0b11
        clock_i = int(clock) & 0b11
        order = 0x20 if lsb_first else 0x00
        config = order | (mode_i << 2) | clock_i
        self._command(_FID_CONFIG, bytes([config]))
        self._config_byte = config
        return config

    def clear_interrupt(self) -> None:
        """Clear the INT pin after an SPI transfer (optional when polling)."""
        self._command(_FID_CLEAR_INT, b"")

    def idle(self) -> None:
        """Enter low-power idle; exits on next addressed I2C transaction."""
        self._command(_FID_IDLE, b"")

    def read_version(self) -> bytes:
        """Read chip version string into the buffer and return it."""
        self._command(_FID_VERSION, b"")
        self._wait_ready()
        # Datasheet does not fix the length; read a short window.
        return self._dev.read(16).rstrip(b"\x00")

    def spi_transfer(
        self,
        tx: bytes | list[int],
        *,
        chip_select: int = 0,
        timeout_s: float = 1.0,
        clear_int: bool = True,
    ) -> bytes:
        """Run one SPI full-duplex transfer on ``chip_select`` (0, 1, or 2).

        Returns the MISO bytes captured into the bridge buffer (same length as
        ``tx``).
        """
        payload = bytes(tx)
        if not payload:
            raise ValueError("SPI transfer requires at least one byte")
        if len(payload) > BUFFER_MAX:
            raise ValueError(f"SPI payload exceeds {BUFFER_MAX}-byte buffer")
        fid = _spi_function_id(chip_select)
        self._command(fid, payload)
        self._wait_ready(timeout_s=timeout_s)
        if clear_int:
            self.clear_interrupt()
        return self._dev.read(len(payload))

    def as_spi_bus(self) -> "SC18IS606SpiBus":
        """Return an :class:`SpiBus` view over this bridge."""
        return SC18IS606SpiBus(self)

    def _command(self, function_id: int, payload: bytes) -> None:
        self._dev.write(bytes([function_id & 0xFF]) + payload)

    def _wait_ready(self, *, timeout_s: float = 1.0, poll_s: float = 0.001) -> None:
        """Poll until the bridge ACKs again (SPI transaction finished)."""
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        ack = getattr(self._bus, "i2c_ack", None)
        if not callable(ack):
            # Fake / minimal buses: no NACK-while-busy behaviour to wait on.
            return
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                if ack(self._address):
                    return
            except Exception:
                pass
            time.sleep(poll_s)
        raise TimeoutError(
            f"SC18IS606 at 0x{self._address:02X} did not become ready "
            f"within {timeout_s:.3f}s"
        )


class SC18IS606SpiDevice:
    """:class:`SpiDevice` bound to one SC18IS606 chip-select."""

    def __init__(self, bridge: SC18IS606, chip_select: int) -> None:
        self._bridge = bridge
        self._cs = chip_select

    @property
    def chip_select(self) -> int:
        return self._cs

    def transfer(self, data: bytes | list[int]) -> bytes:
        return self._bridge.spi_transfer(data, chip_select=self._cs)


class SC18IS606SpiBus:
    """:class:`SpiBus` adapter over an :class:`SC18IS606` instance."""

    def __init__(self, bridge: SC18IS606) -> None:
        self._bridge = bridge

    @property
    def bridge(self) -> SC18IS606:
        return self._bridge

    def device(self, chip_select: int = 0) -> SpiDevice:
        if chip_select not in (0, 1, 2):
            raise ValueError("chip_select must be 0, 1, or 2")
        return SC18IS606SpiDevice(self._bridge, chip_select)


def _spi_function_id(chip_select: int) -> int:
    if chip_select not in (0, 1, 2):
        raise ValueError("chip_select must be 0, 1, or 2")
    # Function ID 01h..07h: bits [2:0] = CS2, CS1, CS0 (any combination allowed).
    return 1 << chip_select
