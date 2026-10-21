"""Hardware smoke script for ProbeTemp1.

Requires a connected MCP2221A and ProbeTemp1 hardware. For offline checks,
use the unit tests with FakeI2CBus instead.
"""

from openacqu import ProbeTemp1
from openacqu.chips.mcp9600 import AdcResolution, ThermocoupleType

probe = ProbeTemp1(check_product=True)
tc = probe.thermocouple

print()
print("Product number")
print(f"0x{probe.product_number:02X}")
print()
print("EUI-48")
print(probe.eeprom.eui48_str)
print()
print("MCP9600 identify")
print(tc.identify())
print(f"revision {tc.revision_str}, ADC {tc.adc_resolution.name}")
print()
print("Open circuit / out of range")
print(tc.open_circuit)
print()
print("Hot junction temp (°C), waiting for conversion")
print(tc.read_hot_junction_c(wait=True))
print()
print("Thermocouple type")
print(tc.thermocouple_type)
tc.thermocouple_type = ThermocoupleType.K
print(tc.thermocouple_type)
print()
print("Filter coefficient")
print(tc.filter_coefficient)
tc.filter_coefficient = 0
print(tc.filter_coefficient)
print()
print("ADC resolution -> 16-bit")
tc.adc_resolution = AdcResolution.BITS_16
print(tc.adc_resolution)
print()
print("LED named color (lime @ 40% CIE L*)")
print(probe.led.set_color("lime", brightness=0.4))
