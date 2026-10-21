"""EasyMCP2221-backed I2C bus adapter.

USB note
--------
MCP2221A GP2 factory-default function is ``USBCFG``. Per the datasheet that
pin is low at reset, goes high after USB configuration, then goes **low again
in USB Suspend** and high on Resume. A brief high pulse on plug-in with no
userspace handle open is usually host autosuspend, not a pin-mux fault.

Keeping an open HID handle (this bus) for the probe session is the primary
software control. Optional :meth:`start_keepalive` issues periodic HID traffic
to further discourage selective suspend. Host policy (udev / Windows power
settings) may still be required — see ``docs/usb.md``.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from openacqu.transport.base import I2CDevice

# Microchip MCP2221 / MCP2221A
USB_VID = 0x04D8
USB_PID = 0x00DD


class MCP2221Device:
    """Thin wrapper around EasyMCP2221 ``I2C_Slave``."""

    def __init__(self, slave: Any) -> None:
        self._slave = slave

    def read_register(self, register: int, length: int = 1) -> bytes:
        data = self._slave.read_register(register, length=length)
        return bytes(data)

    def write_register(self, register: int, data: bytes | list[int]) -> None:
        self._slave.write_register(register, list(data))


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
        return self._device

    @property
    def keepalive_active(self) -> bool:
        return self._keepalive_thread is not None and self._keepalive_thread.is_alive()

    def device(self, address: int, *, reg_bytes: int = 1) -> I2CDevice:
        slave = self._device.I2C_Slave(address, reg_bytes=reg_bytes)
        return MCP2221Device(slave)

    def ping(self) -> None:
        """Issue a cheap HID transaction to discourage USB selective suspend."""
        # Prefer a lightweight SRAM/GPIO touch; fall back to flash info.
        gpio_read = getattr(self._device, "GPIO_read", None)
        if callable(gpio_read):
            gpio_read()
            return
        read_flash = getattr(self._device, "read_flash_info", None)
        if callable(read_flash):
            read_flash()
            return
        # Last resort: stringifying the device often triggers status reads.
        str(self._device)

    def start_keepalive(self, interval_s: float = 1.0) -> None:
        """Start a background thread that periodically calls :meth:`ping`.

        Parameters
        ----------
        interval_s:
            Seconds between HID pings. Must be > 0.
        """
        if interval_s <= 0:
            raise ValueError("keepalive interval_s must be > 0")
        self.stop_keepalive()
        self._keepalive_interval_s = interval_s
        self._keepalive_stop.clear()

        def _loop() -> None:
            while not self._keepalive_stop.wait(interval_s):
                try:
                    self.ping()
                except Exception:
                    # Keep trying; a transient USB glitch should not kill the thread.
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
            "handle_open": not self._closed,
            "keepalive_active": self.keepalive_active,
            "keepalive_interval_s": self._keepalive_interval_s,
            "usbcfg_note": (
                "GP2 USBCFG is high only while USB-configured and not suspended; "
                "low during Suspend is expected without an active host session."
            ),
        }
        read_flash = getattr(self._device, "read_flash_info", None)
        if callable(read_flash):
            try:
                status["flash"] = read_flash()
            except Exception as exc:  # pragma: no cover - hardware-specific
                status["flash_error"] = str(exc)
        # EasyMCP2221 Device often stringifies to a useful settings dump.
        try:
            status["device"] = str(self._device)
        except Exception as exc:  # pragma: no cover
            status["device_error"] = str(exc)
        return status

    def close(self) -> None:
        """Stop keep-alive and release the underlying device if possible."""
        self.stop_keepalive()
        self._closed = True
        close = getattr(self._device, "close", None)
        if callable(close):
            close()


def open_mcp2221_bus(*, keepalive_s: float | None = None) -> MCP2221Bus:
    """Open the first available MCP2221/MCP2221A and return an I2C bus.

    Parameters
    ----------
    keepalive_s:
        If set, start a background HID keep-alive at this interval (seconds).
    """
    import EasyMCP2221

    return MCP2221Bus(EasyMCP2221.Device(), keepalive_s=keepalive_s)
