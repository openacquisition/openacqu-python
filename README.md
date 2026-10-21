# openacqu

Python library for Open Acquisition USB/I2C measurement probes.

Hardware talks to a host PC through an MCP2221A USB-to-I2C bridge. Product
models (for example `ProbeTemp1`) compose shared core peripherals and
model-specific sensor chips on that bus.

```python
from openacqu import ProbeTemp1

probe = ProbeTemp1()
print(probe.thermocouple.hot_junction_c)
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

## Status

Early refactor: transport abstraction, MCP9600 thermocouple support, and
`ProbeTemp1`. Shared core peripherals (LED driver, EEPROM, GPIO expander /
hardware revision) and additional sensors (pH, etc.) come next.
