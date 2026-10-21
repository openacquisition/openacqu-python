# USB / MCP2221A notes (HIL)

## USBCFG (GP2)

Factory default: GP2 = **USBCFG**.

Per the MCP2221A datasheet:

- Low at power-up / reset
- High after successful USB configuration
- **Low again in USB Suspend**, high on Resume

So a brief high pulse when the cable is plugged in, then low, usually means the
host enumerated the device and then **autosuspended** it. That is expected when
no userspace process holds the HID interface open.

Software cannot force USBCFG high while the host has suspended the device. The
fix is:

1. Keep an open handle for the session (`ProbeTemp1()` / `openacqu` commands).
2. Optionally enable keep-alive HID traffic (`--keepalive` / `keepalive_s=`).
3. If the host still suspends, adjust OS USB power policy (below).

Related dedicated function: GP0 can be muxed as **SSPND** (active-low while
suspended) for clearer suspend diagnostics. Do not rewrite flash pin mux until
HIL confirms you need it.

## Library / CLI

```bash
# Diagnose + prove the handle is open
openacqu usb

# Hold the device open while scoping USBCFG (with HID keep-alive)
openacqu usb --keepalive --hold 30
```

```python
from openacqu import ProbeTemp1

probe = ProbeTemp1(keepalive=True)  # 1.0 s HID ping thread
# or: ProbeTemp1(keepalive=0.5)
```

## Host autosuspend (Linux)

Microchip VID/PID for MCP2221A: `04d8:00dd`.

Example udev rule to disable autosuspend for this device:

```
# /etc/udev/rules.d/99-mcp2221a-autosuspend.rules
ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="04d8", ATTR{idProduct}=="00dd", ATTR{power/control}="on"
```

Then:

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Host selective suspend (Windows)

Device Manager → Universal Serial Bus devices / HID → MCP2221 → Properties →
Power Management → uncheck “Allow the computer to turn off this device to save
power” if USBCFG drops while an openacqu process is running.

## HIL scope checklist

| Condition | Expected USBCFG |
| --- | --- |
| Cable plugged, no app open | High briefly, then low (often) |
| `openacqu usb --hold 10` running | High for the hold window |
| Process exits | May go low again (autosuspend) |
