# USB / MCP2221A notes (HIL)

## USBCFG (GP2) and the peripheral load switch

Factory default: GP2 = **USBCFG**.

Per the MCP2221A datasheet:

- Low at power-up / reset
- High after successful USB configuration
- **Low again in USB Suspend**, high on Resume

On Open Acquisition boards, **USBCFG typically enables a load switch** that
powers I2C sensors (for example the MCP9600). That keeps enumeration/suspend
current low, but it means:

| USB state | USBCFG | Switched rail / sensors |
| --- | --- | --- |
| Suspended / no open handle | Low | Unpowered → I2C **NAK** |
| Active HID session | High | Powered → I2C ACK |

A brief high pulse when the cable is plugged in, then low, usually means the
host enumerated the device and then **autosuspended** it.

### Why “first script run works, second run NAKs”

Common causes:

1. **Previous session did not release the HID handle** — EasyMCP2221 only closes
   HID in `Device.__del__` (GC). `openacqu` now calls an explicit `close()` that
   releases `hidhandler`.
2. **Second open raced the load switch** — Resume brings USBCFG high, but the
   rail needs a short settle before the MCP9600 ACKs. We now `ping()` (Resume),
   settle, then poll I2C until ACK.
3. **Host still autosuspends** between runs — expected; the next open should
   Resume. If it does not, see host policy below.

## Session lifecycle (what openacqu does)

1. **Open** HID (`EasyMCP2221.Device`)
2. **`ensure_active()`** — HID ping to Resume, then `settle_s` (default 50 ms)
3. **`wait_for_i2c(mcp9600)`** — retry ACK up to `ready_timeout_s` (default 2 s)
4. Use the probe
5. **`close()`** — stop keep-alive, close HID handle (do not wait for GC)

Prefer a context manager:

```python
from openacqu import ProbeTemp1

with ProbeTemp1(check_product=True) as probe:
    print(probe.temperature_c)
# HID released here; USBCFG may go low (suspend) afterward — that is OK.
```

## Library / CLI

```bash
# Diagnose + prove the handle is open
openacqu usb

# Hold the device open while scoping USBCFG (with HID keep-alive)
openacqu --keepalive usb --hold 30
```

```python
probe = ProbeTemp1(keepalive=True)  # 1.0 s HID ping thread
# or: ProbeTemp1(keepalive=0.5, settle_s=0.1, ready_timeout_s=3.0)
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

## HIL checklist

| Condition | Expected USBCFG | Expected I2C |
| --- | --- | --- |
| Cable plugged, no app open | High briefly, then low (often) | NAK on sensors |
| `with ProbeTemp1() as p:` active | High | ACK after settle |
| After context exits | May go low again | NAK |
| Second run immediately after | High again on open | ACK after settle/retry |

If step 4 fails: increase `settle_s` / `ready_timeout_s`, confirm the load
switch enable net is really USBCFG, and verify HID close with
`openacqu usb` in two consecutive process invocations.
