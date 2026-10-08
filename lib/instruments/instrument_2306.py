import logging
import os
import random
import sys
import time
from typing import Literal, Union

from instrument import Instrument

sys.path.append(os.path.dirname(os.path.realpath(__file__)))


class Keithley2306Agent(Instrument):
    """
    Keithley 2306电源分析仪驱动
    """

    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)

    def set_ch_to_view(self, mode: Union[Literal[1, 2, "ON", "OFF"], str, int]):
        if mode in ["ON", "OFF"]:
            self.send_command(f":DISPlay:ENABle {mode}")
        else:
            state = self.send_command(":DISPlay:ENABle?")
            if state == "OFF" or state == "0":
                self.send_command(":DISPlay:ENABle ON")
            self.send_command(f":DISPlay:CHANnel {mode}")

    def set_ch_voltage(self, channel: int = 1, voltage: float = 4.5):
        self.send_command(f":SOURce{channel}:VOLTage {voltage}")

    def set_ch_current(self, channel: int = 1, current: float = 4.5):
        self.send_command(f":SOURce{channel}:CURRent {current}")

    def set_ch_output_state(self, channel: int = 1, state: bool = True):
        self.send_command(f'OUTPut{channel} {"ON" if state else "OFF"}')

    def measure_ch_voltage(self, channel: int = 1, unit: str = ''):
        """测量电压"""
        value = float(self.send_command(f":MEASure{channel}:VOLTage?"))
        return self.change_value_to_scale(value, unit=unit)

    def measure_ch_current(self, channel: int = 1, unit: str = ''):
        """测量电流"""
        value = float(self.send_command(f":MEASure{channel}:CURRent?"))
        return self.change_value_to_scale(value, unit=unit)


class Instrument_Dryrun(Keithley2306Agent):
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


def main():
    virtual_device = Keithley2306Agent('USB0::0x0957::0x8C18::MY51142334::INSTR')
    virtual_device.connect()
    virtual_device.set_ch_voltage(1, 0.5)
    virtual_device.set_ch_current(1, 0.01)
    virtual_device.set_ch_output_state(1, True)
    time.sleep(2)
    virtual_device.set_ch_output_state(1, False)
    virtual_device.disconnect()


if __name__ == '__main__':
    main()
