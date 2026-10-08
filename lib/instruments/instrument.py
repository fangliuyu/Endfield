import functools
import random
import traceback
from typing import Optional

import pyvisa
import logging

from lib.instruments.visa_env import get_resource_manager

Base_Unit: dict[str: float] = {'m': 1e3, 'u': 1e6, 'n': 1e9, 'p': 1e12, 'K': 1e-3, 'M': 1e-6, 'G': 1e-9, "%": 1e-2}


def _connected_check(func):
    """装饰器方法，检查设备连接状态"""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        self = args[0]
        if not (self._virtual_device and self._connected):
            raise Exception("the device not connected")
        return func(*args, **kwargs)

    return wrapper


class Instrument:
    """通用VISA对象"""

    def __init__(self, instrument_address: str, timeout: float = 5000, logger=None):
        self.logger = logger
        if not self.logger:
            self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
        self.rm = get_resource_manager(logger=self.logger)
        self.address = instrument_address
        self.timeout = timeout
        self._virtual_device: Optional[pyvisa.resources.Resource] = None
        self._connected = False
        self.name = ""
        self.sn = ""
        try:
            self.logger.info("获取设备信息")
            self.connect(reset=False)
            drive_name, drive_sn = idn2module(self.get_idn())
            self.name = drive_name
            self.sn = drive_sn
            self.disconnect()
        except Exception as e:
            self.logger.debug(e)

    def connect(self, reset=True):
        if self._connected:  # 将旧设备关闭
            self.disconnect()
        try:
            self._virtual_device = self.rm.open_resource(self.address)
        except Exception as ex:
            self.logger.exception(traceback.format_exc())
            raise Exception(f"Exception Type: {type(ex).__name__}, Message: {ex}")

        self._connected = True
        if reset:
            self.reset()
        self._virtual_device.timeout = self.timeout
        self.logger.info(f"{self.name} 已连接")

    def __repr__(self):
        return f"{self.name} - {self.sn}"

    def disconnect(self):
        if self._virtual_device:
            self._virtual_device.close()
        self._connected = False
        self.logger.info(f"{self.name} 已断开连接")

    def reset(self):
        self.send_command("*RST")
        # Clear existing status.
        self.send_command("*CLS")

    @_connected_check
    def set_timeout(self, timeout_ms: float):
        self.timeout = timeout_ms
        if self._virtual_device:
            self._virtual_device.timeout = self.timeout

    def self_test(self):
        self_test_result = self.send_command('TEST:ALL?')
        return int(self_test_result) == 0

    @_connected_check
    def send_command(self, command: str, check_errors=False, wait_for_opc=False, wait_for_device=False):
        self.logger.info(f'{self.name}({self.sn})| send | {command}')

        write_success = self._send_command_with_retry(command)
        if not write_success:
            raise Exception(f"Failed to send command after 3 attempts: {command}")

        response = ""
        if '?' in command:
            response = self._read_response().strip()
            self.logger.info(f'{self.name}({self.sn})| resp | {response}')

        if wait_for_device:
            self._virtual_device.write("*WAI")

        if wait_for_opc:
            self._wait_for_opc()

        if check_errors and '*' not in command:
            err = self._check_command_errors()
            if err:
                self.logger.info(f'{self.name}({self.sn})| err  | : {err}')
                return err

        return response

    def _send_command_with_retry(self, command: str, max_retries: int = 3) -> bool:
        """带重试机制的命令发送"""
        for attempt in range(max_retries):
            try:
                self._virtual_device.write(command)
                return True
            except Exception as ex:
                self.logger.warning(f"Command send attempt {attempt + 1} failed: [{type(ex).__name__}] {ex}")
                if attempt == max_retries - 1:  # 最后一次尝试失败
                    self.logger.error(f"All {max_retries} attempts failed for command: {command}")
                    return False

        return False

    def _check_command_errors(self):
        """检查命令执行错误"""
        error_code = int(self.send_command(command="*ESR?", check_errors=False))

        if error_code and error_code != 1:  # 错误代码不为0或1表示有错误
            error_log = f"[Error] code: {error_code}, Detailed: {self.send_command(command=':SYSTem:ERRor?', check_errors=False)}"
            self.logger.error(error_log)
            return error_log
        return ""

    def _wait_for_opc(self):
        result = 0
        while int(result) != 1:
            result = self._virtual_device.query("*OPC?")

    def _read_response(self):
        """
        Internal method used to read responses from the device.
        This method is also encapsulated in the SendCommand method.
        """
        return self._virtual_device.read()

    @_connected_check
    def get_idn(self):
        """Get device identification"""
        response = self.send_command("*IDN?")
        return response

    @staticmethod
    def change_value_to_scale(value: float, unit: str):
        for base_unit, scale in Base_Unit.items():
            if base_unit in unit:
                return value * scale
        return value

    @staticmethod
    def set_value_to_scale(value: float, unit: str):
        for base_unit, scale in Base_Unit.items():
            if base_unit in unit:
                return value / scale
        return value

    @staticmethod
    def get_scale_for_units(unit):
        for base_unit, scale in Base_Unit.items():
            if base_unit in unit:
                return 1 / scale
        return 1.0


class Instrument_Dryrun(Instrument):
    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address, timeout, logger=logger)

    def connect(self, reset=True):
        self._connected = True
        self.logger.info(f"{self.name} 已连接")

    def disconnect(self):
        self._connected = False
        self.logger.info(f"{self.name} 已断开")

    def reset(self):
        pass

    def self_test(self):
        return True

    def send_command(self, command, check_errors=False, wait_for_opc=False, wait_for_device=False):
        self.logger.info(f'send {self.name} command: {command}')

        # read command
        if command.find('?') > 0:
            response = str(round(random.uniform(333e-6, 666e-6), 6))
        else:
            response = ""

        return response


def get_device_list():
    manager = get_resource_manager()
    resource_list = manager.list_resources("(USB|TCPIP)[0-9]*::[a-zA-Z0-9:]*::?*INSTR")
    return resource_list


def check_device_module(address: str, module_list: list[str] = None):
    """
    检测设备是否在对应列表的里
    :param address: 设备地址
    :param module_list: 设备列表
    :return: tuple[str, str]: 设备信息, 设备SN
    """
    in_list = False
    try:
        temp_instrument = Instrument(address)
        temp_instrument.connect(False)
        idn_read = temp_instrument.get_idn()
        module, sn = idn2module(idn_read)
        # print(module, ":", sn)
        temp_instrument.disconnect()
        if module_list:
            for name in module_list:
                if name in module:
                    in_list = True
                    break
        else:
            in_list = True
        return in_list, module, sn
    except Exception as e:
        print(f"Exception Type: {type(e).__name__}, Message: {e}")
        return False, "", ""


def idn2module(idn: str):
    """
    获取设备信息
    :param idn: 设备指令返回值
    :return:
        str: 设备名称
        str: 设备SN
    """
    data_info = idn.split(',')
    idn = ' '.join(data_info[:2]).replace('-', '')
    class_name = ''.join([word.strip().capitalize() for word in idn.split(' ')])
    sn = data_info[2]
    return class_name, sn


if __name__ == '__main__':
    instruments = get_device_list()
    print(instruments)
    instrument_agent = Instrument(input("sn: "))
    print(instrument_agent.name, instrument_agent.sn)
