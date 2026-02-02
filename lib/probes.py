from .devices import MCP2221, MCP9600

class ProbeTemp1:

    def __init__(self):
        self._mcp2221 = MCP2221.get_mcp2221()
        self._mcp9600 = MCP9600(self._mcp2221)
        # print(self._mcp9600.hj_temp)
    
    @property
    def temp_hj(self):
        return(self._mcp9600.temp_hj)