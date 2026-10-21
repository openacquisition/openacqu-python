"""Hardware smoke script for ProbeTemp1.

Requires a connected MCP2221A + MCP9600. For offline checks, use the unit
tests with FakeI2CBus instead.
"""

from openacqu import ProbeTemp1
from openacqu.chips.mcp9600 import ThermocoupleType

probe = ProbeTemp1()

print()
print("Hot junction temp (°C)")
print(probe.temperature_c)
print()
print("Thermocouple type")
print(probe.thermocouple.thermocouple_type)
probe.thermocouple.thermocouple_type = ThermocoupleType.K
print(probe.thermocouple.thermocouple_type)
print()
print("Filter coefficient")
print(probe.thermocouple.filter_coefficient)
probe.thermocouple.filter_coefficient = 0
print(probe.thermocouple.filter_coefficient)
