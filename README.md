# openacqu

Python library for Open Acquisition USB/I2C measurement probes.

Hardware talks to a host PC through an MCP2221A USB-to-I2C bridge. Product
models (for example `ProbeTemp1`) compose shared core peripherals and
model-specific sensor chips on that bus.

```python
from openacqu import ProbeTemp1

probe = ProbeTemp1()
print(probe.product_number)          # 0x01 on the temperature probe
print(probe.eeprom.eui48_str)
probe.led.set_rgb(0, 32, 0)
print(probe.temperature_c)
```

## Install

```bash
pip install -e ".[dev]"
```

## Tests

Unit tests use a fake I2C bus and do not require hardware:

```bash
pytest
```

Hardware-in-the-loop scripts live under `examples/`.

## Core peripherals

| Chip | Role | I2C (schematic) |
| --- | --- | --- |
| LP5817 | RGB LED driver | `0x2D` |
| 24AA025E48 | EEPROM + EUI-48 | `0x50` (A0=A1=GND) |
| FXL6408 | Product number (read-only) | `0x43` (ADDR=GND); `0x01` = temp probe |
| MCP9600 | Thermocouple (ProbeTemp1) | `0x67` |

## Status

Transport abstraction, shared core peripherals, MCP9600 / `ProbeTemp1`, and
offline unit tests are in place. Optional CLI test harness and additional
sensors (pH, etc.) come next.
