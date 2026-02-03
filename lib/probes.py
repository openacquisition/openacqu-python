from .devices import MCP2221, MCP9600

class ProbeTemp1:

    def __init__(self):
        self._mcp2221 = MCP2221.get_mcp2221()
        self._mcp9600 = MCP9600(self._mcp2221)
    
    @property
    def temp_hj(self):
        return(self._mcp9600.temp_hj)

    @property
    def thermocouple_type(self):
        return(self._mcp9600.thermocouple_type)

    @thermocouple_type.setter
    def thermocouple_type(self, tctype_enum):
        self._mcp9600.thermocouple_type = tctype_enum

    @property
    def filter_coefficient(self):
        return(self._mcp9600.filter_coefficient)

    @filter_coefficient.setter
    def filter_coefficient(self, value):
        self._mcp9600.filter_coefficient = value

