# openacqu

Python library for Open Acquisition USB/I2C measurement probes.

Hardware talks to a host PC through an MCP2221A USB-to-I2C bridge. Product
models (for example `ProbeTemp1`) compose shared core peripherals and
model-specific sensor chips on that bus.

```python
from openacqu import ProbeTemp1

with ProbeTemp1() as probe:  # always release HID (USBCFG may gate sensor power)
    print(probe.product_number)          # 0x01 on the temperature probe
    print(probe.eeprom.eui48_str)
    probe.led.set_color("lime", brightness=0.4)  # CSS name → LED PWM profile
    probe.led.set_rgb(0, 32, 0)                  # raw PWM still available
    print(probe.temperature_c)
```

## Install

```bash
pip install -e ".[dev]"
```

## CLI test harness

The library is the primary API. The `openacqu` CLI mirrors model features for
hardware bring-up:

```bash
openacqu usb
openacqu usb --keepalive --hold 30
openacqu info
openacqu product
openacqu eui48
openacqu led set 0 64 0
openacqu led color orange --brightness 0.5
openacqu led colors
openacqu led off
openacqu temp read
openacqu temp status
openacqu temp type K
openacqu temp filter 0
openacqu temp resolution 16
openacqu temp identify
openacqu eeprom read 0xFA 6
```

Also: `python -m openacqu ...`. Use `--check-product` to require product `0x01`
on ProbeTemp1. Use `--keepalive` to keep HID traffic alive (helps USBCFG stay high).

See [docs/usb.md](docs/usb.md) for MCP2221A USBCFG / USB Suspend notes and host
autosuspend setup.

## Tests

Unit tests use a fake I2C bus and do not require hardware:

```bash
pytest
```

Hardware-in-the-loop scripts also live under `examples/`.

## Core peripherals

| Chip | Role | I2C (schematic) |
| --- | --- | --- |
| LP5817 | RGB LED driver (+ CSS colors / CIE L* dimming) | `0x2D` |
| 24AA025E48 | EEPROM + EUI-48 | `0x50` (A0=A1=GND) |
| FXL6408 | Product number (read-only) | `0x43` (ADDR=GND); `0x01` = temp probe |
| MCP9600 | Thermocouple (ProbeTemp1) | `0x67` |

## Status

Transport abstraction, shared core peripherals, MCP9600 / `ProbeTemp1`, and
offline unit tests are in place. Optional CLI test harness and additional
sensors (pH, etc.) come next.
