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
                "GP2 USBCFG is high only while USB-configured and not suspended; "
                "low during Suspend is expected without an active host session. "
                "If USBCFG gates a load switch, I2C NAKs after reopen usually mean "
                "Resume/settle did not complete before the first transaction."
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
