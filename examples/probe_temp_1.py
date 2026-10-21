"""Hardware smoke script for ProbeTemp1.

Requires a connected MCP2221A and ProbeTemp1 hardware. For offline checks,
use the unit tests with FakeI2CBus instead.
"""

from openacqu import ProbeTemp1
from openacqu.chips.mcp9600 import ThermocoupleType

probe = ProbeTemp1(check_product=True)

print()
print("Product number")
print(f"0x{probe.product_number:02X}")
print()
print("EUI-48")
print(probe.eeprom.eui48_str)
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
print()
print("LED green pulse")
probe.led.set_rgb(0, 64, 0)
