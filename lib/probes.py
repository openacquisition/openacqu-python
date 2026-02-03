from .devices import MCP2221, MCP9600

class ProbeTemp1(MCP9600):

    def __init__(self):
        self._mcp2221 = MCP2221.get_mcp2221()
        super().__init__(self._mcp2221)
 
