import EasyMCP2221
from enum import Enum
class MCP2221:

    @staticmethod
    def get_mcp2221():
        mcp = EasyMCP2221.Device()
        return(mcp)
        # print(mcp)

class MCP9600:

    # Register Addresses and lengths
    HOT_JUNC_TEMP = [0x00, 2]
    JUNC_TEMP_DELTA = [0x01, 2]
    COLD_JUNC_TEMP = [0x02, 2]
    RAW_ADC_DATA = [0x03, 3]
    STATUS = [0x04, 1]
    SENSOR_CONFIG = [0x05, 1]
    DEVICE_CONFIG = [0x06, 1]
    ALERT_CONFIG_BASE = [0x08, 1]
    ALERT_HYST_BASE = [0x0C, 1]
    ALERT_LIMIT_BASE = [0x10, 2]
    DEVICE_ID_REV = [0x20, 1]

    class TcType(Enum):
        K = 0x0
        J = 0x1
        T = 0x2
        N = 0x3
        S = 0x4
        E = 0x5
        B = 0x6
        R = 0x7

    def __init__(self, mcp2221):

        self._mcp2221 = mcp2221
        self._mcp9600 = self._mcp2221.I2C_Slave(0x67, reg_bytes = 1)
        # print(self._mcp9600.is_present())
        print(self._mcp9600.read(30).hex(sep=' '))

    def _read_register(self, register):
        reg_bytes = self._mcp9600.read_register(register[0], length=register[1])
        return(reg_bytes)

    def _write_register(self, register, reg_bytes):
        self._mcp9600.write_register(register[0], reg_bytes)

    @property
    def temp_hj(self):
        # Read the hot junction temp
        hj_bytes = self._read_register(MCP9600.HOT_JUNC_TEMP)
        hj_high = hj_bytes[0]
        hj_low = hj_bytes[1]
        hj_temp = float(((hj_high & 0x7F) << 8) | hj_low)/16

        return(hj_temp)

    @property
    def thermocouple_type(self):
        # Get the type of thermocouple set in the MCP9600 registers
        register = self._read_register(MCP9600.SENSOR_CONFIG)[0]
        thermocouple = (register & 0x70) >> 4
        tc_type = MCP9600.TcType(thermocouple)
        return(tc_type)

    @thermocouple_type.setter
    def thermocouple_type(self, tctype_enum):
        # Receive the new value for the thermocouple type
        tc_value = tctype_enum.value
        # Read the current register value
        sensor_config = self._read_register(MCP9600.SENSOR_CONFIG)[0]
        # Mask off the type bits
        sensor_config = sensor_config & 0x07
        # OR in the new bits
        sensor_config = sensor_config | (tc_value << 4)
        # Convert to bytes
        register = sensor_config.to_bytes(1)
        # Write to the MCP9600
        self._write_register(MCP9600.SENSOR_CONFIG, register)


    @property
    def filter_coefficient(self):
        # Get the type of filter coefficient in the MCP9600 registers
        register = self._read_register(MCP9600.SENSOR_CONFIG)[0]
        filter_coef = register & 0x07
        return(filter_coef)
    
    @filter_coefficient.setter
    def filter_coefficient(self, filter_coef):
        # Read the current register value
        sensor_config = self._read_register(MCP9600.SENSOR_CONFIG)[0]
        # Mask off the filter bits
        sensor_config = sensor_config & 0xF8
        # OR in the new bits
        sensor_config = sensor_config | filter_coef
        # Convert to bytes
        register = sensor_config.to_bytes(1)
        # Write to the MCP9600
        self._write_register(MCP9600.SENSOR_CONFIG, register)



