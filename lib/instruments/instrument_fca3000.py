
import logging
import os
import sys
from typing import Union, Literal

from instrument import Instrument

sys.path.append(os.path.dirname(os.path.realpath(__file__)))


class FCA3000Agent(Instrument):
    """
    Keysight B29xx 系列电源分析仪驱动
    """

    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)
        self.meas_time = 0.05  # 默认测量时间（秒）

    def set_meas_time(self, meas_time: float) -> None:
        """
        设置测量时间

        Args:
            meas_time: 测量时间（秒），必须为正数
        """
        if meas_time <= 0:
            raise ValueError("测量时间必须为正数")

        self.send_command(f":ACQuire:AREa:TIME {meas_time}")
        self.meas_time = meas_time

    def read_measurement(self, channel: int = 1, unit: str = "") -> float:
        """
        执行频率测量

        Returns:
            float: 测量的频率值（Hz）
        """
        value = float(self.send_command(f":MEASure:FREQuency? (@{channel})"))
        return self.change_value_to_scale(value, unit=unit)

    def set_coupling(self, channel: int, coupling: Union[Literal['AC', 'DC'], str]) -> None:
        """
        设置输入耦合
        """
        coupling_upper = coupling.upper()
        self.send_command(f":INPut:SELect CH{channel}")
        self.send_command(f":INPut:COUPling {coupling_upper}")

    def set_impedance(self, channel: int, impedance: int) -> None:
        """
        设置输入阻抗
        """
        self.send_command(f":INPut{channel}:IMPedance {impedance}")

    def get_screen_image(self, timeout: int = None) -> bytes:
        """
        Reads the screen image data from an InfiniiVision oscilloscope

        Args:
            timeout: 超时时间(ms)
        """
        original_timeout = self._virtual_device.timeout
        if timeout:
            self._virtual_device.timeout = timeout

        try:
            self._virtual_device.write("HCOPy:SDUMp:DATA?")

            raw_data = self._virtual_device.read_raw()

            if raw_data.startswith(b"#"):
                header_len = int(raw_data[1:2])
                data_start = 2 + header_len
                img_data = raw_data[data_start:-1]
                self.logger.debug(f"截图完成: {len(img_data)} 字节")
                return img_data

            self.logger.debug(f"截图完成 (无头部): {len(raw_data)} 字节")
            return raw_data

        except Exception as e:
            self.logger.error(f"截图数据获取失败: {e}")
            raise Exception(f"截图数据获取失败: {e}")
        finally:
            if timeout:
                self._virtual_device.timeout = original_timeout


class Instrument_Dryrun(FCA3000Agent):
    def __init__(self, instrument_address, timeout: float = 5000, logger=None):
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
            response = "666e-6"
        else:
            response = ""

        return response


def main():
    virtual = FCA3000Agent('USB0::0x2A8D::0x0101::MY60009053::INSTR')
    virtual.connect()
    pass
    virtual.disconnect()


if __name__ == '__main__':
    main()
