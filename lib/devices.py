import EasyMCP2221

class MCP2221:

    @staticmethod
    def get_mcp2221():
        mcp = EasyMCP2221.Device()
        return(mcp)
        # print(mcp)

class MCP9600:

    def __init__(self, mcp2221):

        self._mcp2221 = mcp2221
        self._mcp9600 = self._mcp2221.I2C_Slave(0x67, reg_bytes = 1)
        # print(self._mcp9600.is_present())
        # print(self._mcp9600.read(30).hex(sep=' '))


    @property
    def temp_hj(self):
        # Read the hot junction temp
        hj_bytes = self._mcp9600.read(2)
        hj_high = hj_bytes[0]
        hj_low = hj_bytes[1]
        hj_temp = float(((hj_high & 0x7F) << 8) | hj_low)/16

        return(hj_temp)



