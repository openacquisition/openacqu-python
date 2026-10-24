"""EasyMCP2221-backed I2C bus adapter.

USB / load-switch note
----------------------
MCP2221A GP2 factory-default function is ``USBCFG``. Per the datasheet that
pin is low at reset, goes high after USB configuration, then goes **low again
in USB Suspend** and high on Resume.

On Open Acquisition hardware, USBCFG often gates a load switch that powers
I2C sensors. So:

* Opening a HID handle should Resume the device → USBCFG high → rail on
* Closing / autosuspend → USBCFG low → sensors unpowered (I2C NAK)
* After open there can be a short delay before the switched rail is stable

EasyMCP2221 only closes the HID device in ``Device.__del__``. We explicitly
release ``hidhandler`` in :meth:`close` so scripts can open/close repeatedly
without relying on GC. See ``docs/usb.md``.
"""

from __future__ import annotations

import threading
import time
from types import TracebackType
from typing import Any

from openacqu.transport.base import I2CDevice

# Microchip MCP2221 / MCP2221A
USB_VID = 0x04D8
USB_PID = 0x00DD

# Read/Write Flash Data, chip-settings sub-command. The 10 setting bytes in a
# read response start at offset 4; a write sends those bytes followed by an
# 8-byte password (zeros when the chip is unprotected).
_CMD_READ_FLASH_DATA = 0xB0
_CMD_WRITE_FLASH_DATA = 0xB1
_FLASH_CHIP_SETTINGS = 0x00
_FLASH_SETTINGS_OFFSET = 4
_CHIP_SETTINGS_LEN = 10
_FLASH_PASSWORD_LEN = 8
# Chip-settings byte 0 bit 2 (USBCFGINST) is the pin level while USB is *not*
# configured. While the device is configured, the pin is driven to the opposite
# level. Active-low therefore stores 1; active-high stores 0.
_USBCFG_INACTIVE_BIT = 1 << 2

# Default pause after HID open/ping so a USBCFG-gated load switch can rise.
DEFAULT_SETTLE_S = 0.05


class MCP2221Device:
    """Thin wrapper around EasyMCP2221 ``I2C_Slave``."""

    def __init__(self, slave: Any) -> None:
        self._slave = slave

    def read_register(self, register: int, length: int = 1) -> bytes:
        data = self._slave.read_register(register, length=length)
        return bytes(data)

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        self._slave.write_register(register, list(data))

    def write(self, data: bytes | list[int]) -> None:
        self._slave.write(list(data))

    def read(self, length: int = 1) -> bytes:
        data = self._slave.read(length)
        return bytes(data)


class MCP2221Bus:
    """I2CBus adapter over an EasyMCP2221 ``Device`` instance."""

    def __init__(self, device: Any, *, keepalive_s: float | None = None) -> None:
        self._device = device
        self._keepalive_interval_s: float | None = None
        self._keepalive_stop = threading.Event()
        self._keepalive_thread: threading.Thread | None = None
        self._closed = False
        if keepalive_s is not None:
            self.start_keepalive(keepalive_s)

    @property
    def raw(self) -> Any:
        """Underlying EasyMCP2221 device (GPIO/ADC/DAC later)."""
        if self._closed or self._device is None:
            raise RuntimeError("MCP2221Bus is closed")
        return self._device

    @property
    def keepalive_active(self) -> bool:
        return self._keepalive_thread is not None and self._keepalive_thread.is_alive()

    def device(self, address: int, *, reg_bytes: int = 1) -> I2CDevice:
        slave = self.raw.I2C_Slave(address, reg_bytes=reg_bytes, force=True)
        return MCP2221Device(slave)

    def ping(self) -> None:
        """Issue a cheap HID transaction (Resume + discourage selective suspend)."""
        device = self.raw
        gpio_read = getattr(device, "GPIO_read", None)
        if callable(gpio_read):
            gpio_read()
            return
        read_flash = getattr(device, "read_flash_info", None)
        if callable(read_flash):
            read_flash()
            return
        str(device)

    def ensure_active(self, *, settle_s: float = DEFAULT_SETTLE_S) -> None:
        """Touch HID (host Resume) then wait for a USBCFG-gated rail to settle."""
        self.ping()
        if settle_s > 0:
            time.sleep(settle_s)

    def i2c_ack(self, address: int) -> bool:
        """Return True if a slave ACKs at ``address`` (1-byte read probe)."""
        device = self.raw
        try:
            # force=True: do not raise in I2C_Slave.__init__ when absent.
            slave = device.I2C_Slave(address, reg_bytes=1, force=True)
            return bool(slave.is_present())
        except Exception:
            return False

    def wait_for_i2c(
        self,
        address: int,
        *,
        timeout_s: float = 2.0,
        poll_s: float = 0.05,
    ) -> None:
        """Poll until ``address`` ACKs or raise ``TimeoutError``.

        Useful after open/resume while a USBCFG load switch powers sensors.
        """
        if timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        if poll_s <= 0:
            raise ValueError("poll_s must be > 0")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self.i2c_ack(address):
                return
            time.sleep(poll_s)
        raise TimeoutError(
            f"no I2C ACK from 0x{address:02X} within {timeout_s:.3f}s "
            "(device may still be suspended or USBCFG load-switch rail not up)"
        )

    def start_keepalive(self, interval_s: float = 1.0) -> None:
        """Start a background thread that periodically calls :meth:`ping`."""
        if interval_s <= 0:
            raise ValueError("keepalive interval_s must be > 0")
        self.stop_keepalive()
        self._keepalive_interval_s = interval_s
        self._keepalive_stop.clear()

        def _loop() -> None:
            while not self._keepalive_stop.wait(interval_s):
                try:
                    if not self._closed:
                        self.ping()
                except Exception:
                    pass

        self._keepalive_thread = threading.Thread(
            target=_loop,
            name="openacqu-mcp2221-keepalive",
            daemon=True,
        )
        self._keepalive_thread.start()

    def stop_keepalive(self) -> None:
        """Stop the background keep-alive thread if running."""
        self._keepalive_stop.set()
        thread = self._keepalive_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._keepalive_thread = None
        self._keepalive_interval_s = None

    def usb_status(self) -> dict[str, Any]:
        """Return diagnostic info for USB bring-up / USBCFG debugging."""
        status: dict[str, Any] = {
            "vid": f"0x{USB_VID:04X}",
            "pid": f"0x{USB_PID:04X}",
            "handle_open": not self._closed and self._device is not None,
            "keepalive_active": self.keepalive_active,
            "keepalive_interval_s": self._keepalive_interval_s,
            "usbcfg_note": (
                "GP2 function is USBCFG. The flashed active level is the pin "
                "level while USB is configured; the pin takes the opposite "
                "level when the device is not configured or is suspended. "
                "Read or program it with 'openacqu usb usbcfg'."
            ),
        }
        if self._closed or self._device is None:
            return status
        read_flash = getattr(self._device, "read_flash_info", None)
        if callable(read_flash):
            try:
                status["flash"] = read_flash()
            except Exception as exc:  # pragma: no cover - hardware-specific
                status["flash_error"] = str(exc)
        try:
            status["device"] = str(self._device)
        except Exception as exc:  # pragma: no cover
            status["device_error"] = str(exc)
        return status

    def force_gp2_gpio(self, level: str) -> str:
        """Drive GP2 as a GPIO output. SRAM only; lasts until reset or unplug.

        ``level`` is ``high`` or ``low``. This does not write flash, so the
        factory USBCFG function returns on the next power cycle.
        """
        if level not in ("high", "low"):
            raise ValueError("GP2 level must be high or low")
        self.raw.set_pin_function(gp2="GPIO_OUT", out2=level == "high")
        return level

    def usbcfg_active_level(self) -> str:
        """Return the flashed USBCFG level while USB is configured.

        Returns ``high`` or ``low``. This is the level stored in flash, which
        the MCP2221A applies on the next reset or re-enumeration.
        """
        cdcsec = self._read_chip_settings()[0]
        return "low" if cdcsec & _USBCFG_INACTIVE_BIT else "high"

    def flash_usbcfg_active_level(self, level: str) -> str:
        """Program the flashed USBCFG level used while USB is configured.

        ``level`` is ``high`` or ``low``. Only the USBCFGINST bit is
        changed; every other chip setting is written back unchanged. The new
        value is read back from flash. It takes effect after the MCP2221A is
        reset or the USB device is re-enumerated.
        """
        if level not in ("high", "low"):
            raise ValueError("USBCFG active level must be 'high' or 'low'")
        settings = self._read_chip_settings()
        cdcsec = settings[0]
        if cdcsec & 0b11:
            raise RuntimeError(
                "MCP2221A chip settings are protected; refusing to write flash"
            )
        if level == "low":
            cdcsec |= _USBCFG_INACTIVE_BIT
        else:
            cdcsec &= ~_USBCFG_INACTIVE_BIT & 0xFF
        settings[0] = cdcsec
        self._write_chip_settings(settings)
        actual = self.usbcfg_active_level()
        if actual != level:
            raise RuntimeError(
                f"USBCFG flash verify failed: requested {level}, read back {actual}"
            )
        return actual

    def _read_chip_settings(self) -> list[int]:
        """Return the 10 chip-settings bytes stored in flash."""
        response = self._flash_command([_CMD_READ_FLASH_DATA, _FLASH_CHIP_SETTINGS])
        end = _FLASH_SETTINGS_OFFSET + _CHIP_SETTINGS_LEN
        if len(response) < end:
            raise RuntimeError("MCP2221A chip-settings read was short")
        return list(response[_FLASH_SETTINGS_OFFSET:end])

    def _write_chip_settings(self, settings: list[int]) -> None:
        """Write chip settings plus a blank password (unprotected devices)."""
        if len(settings) != _CHIP_SETTINGS_LEN:
            raise ValueError(f"chip settings must be {_CHIP_SETTINGS_LEN} bytes")
        payload = list(settings) + [0] * _FLASH_PASSWORD_LEN
        self._flash_command([_CMD_WRITE_FLASH_DATA, _FLASH_CHIP_SETTINGS, *payload])

    def _flash_command(self, command: list[int]) -> list[int]:
        device = self.raw
        send = getattr(device, "send_cmd", None)
        if not callable(send):
            raise TypeError("MCP2221 device does not support flash access")
        response = list(send(command))
        if len(response) < 2 or response[1] != 0:
            raise RuntimeError("MCP2221A flash command failed")
        return response

    def close(self) -> None:
        """Stop keep-alive and explicitly release the HID handle.

        EasyMCP2221 only closes ``hidhandler`` in ``Device.__del__``. Calling
        this makes repeated script runs deterministic without waiting for GC.
        """
        if self._closed:
            return
        self.stop_keepalive()
        self._closed = True
        device = self._device
        self._device = None
        if device is None:
            return
        # Prefer an explicit close() if a future EasyMCP2221 adds one.
        close = getattr(device, "close", None)
        if callable(close):
            try:
                close()
                return
            except Exception:
                pass
        # Mirror EasyMCP2221.Device.__del__
        hidhandler = getattr(device, "hidhandler", None)
        if hidhandler is not None:
            try:
                hidhandler.close()
            except Exception:
                pass
            try:
                delattr(device, "hidhandler")
            except Exception:
                pass

    def __enter__(self) -> MCP2221Bus:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def open_mcp2221_bus(
    *,
    keepalive_s: float | None = None,
    settle_s: float = DEFAULT_SETTLE_S,
    ready_address: int | None = None,
    ready_timeout_s: float = 2.0,
) -> MCP2221Bus:
    """Open the first available MCP2221/MCP2221A and return an I2C bus.

    Parameters
    ----------
    keepalive_s:
        If set, start a background HID keep-alive at this interval (seconds).
    settle_s:
        Delay after the first HID ping for USBCFG/load-switch rail rise.
    ready_address:
        If set, poll this I2C address until ACK (or ``ready_timeout_s``).
    ready_timeout_s:
        Timeout for ``ready_address`` polling.
    """
    import EasyMCP2221

    bus = MCP2221Bus(EasyMCP2221.Device(), keepalive_s=keepalive_s)
    try:
        bus.ensure_active(settle_s=settle_s)
        if ready_address is not None:
            bus.wait_for_i2c(ready_address, timeout_s=ready_timeout_s)
    except Exception:
        bus.close()
        raise
    return bus
