from lib.probes import ProbeTemp1
from lib.devices import MCP9600

temp_probe = ProbeTemp1()
print()
print('Hot junction Temp')
print(temp_probe.temp_hj)
print()
print('Thermocouple Type')
print(temp_probe.thermocouple_type)
temp_probe.thermocouple_type = MCP9600.TcType.K
print(temp_probe.thermocouple_type)
print()
print('Filter Coefficients')
print(temp_probe.filter_coefficient)
temp_probe.filter_coefficient = 0
print(temp_probe.filter_coefficient)




