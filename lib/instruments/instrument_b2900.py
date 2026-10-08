import logging
import os
import random
import sys
import time
from typing import Dict, Union
from typing import Literal

from instrument import Instrument

sys.path.append(os.path.dirname(os.path.realpath(__file__)))


class B2900Agent(Instrument):
    """
    Keysight B29xx 系列电源分析仪驱动
    """

    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)
        self.source_mode: Dict[int: str] = {1: "Voltage", 2: "Voltage"}

    # 这个指令不起任何作用 Page 358
    # def disconnect(self):
    #     if self._virtual_device and self._connected:
    #         self.send_command(":SYSTem:LOCal")
    #         self._virtual_device.close()
    #     self._connected = False
    #     self.logger.info(f"{self.name} 已断开连接")

    def set_view_mode(self, mode: Union[Literal['SINGle1', 'SINGle2', 'DUAL', 'GRAPh', 'ROLL'], str]):
        self.send_command(f":DISPlay:VIEW {mode}")

    def set_ch_to_view(self, channel: int):
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        self.set_view_mode(f"SINGle{channel}")

    def set_source_mode(self, channel: int = 1, mode: Union[Literal['VOLTage', 'CURRent'], str] = "VOLTage"):
        """
        设置源输出模式

        Args:
            channel: int
            mode: "VOLTage" 或 "CURRent"
        """
        err = self.send_command(f":SOURce{channel}:FUNCtion:MODE {mode}", check_errors=True)
        if err:
            raise Exception(err)
        self.source_mode[channel] = mode
        return self.send_command(f":SOURce{channel}:FUNCtion:MODE?")

    def set_ch_voltage(self, channel: int = 1, voltage: float = 4.5):
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        mode = self.source_mode[channel]
        if mode.lower() == 'voltage':
            self.send_command(f":SOURce{channel}:VOLTage:LEVel:IMMediate:AMPLitude {voltage}")
        else:
            self.send_command(f":SENSe{channel}:VOLTage:PROTection:LEVel {voltage}")

    def set_ch_current(self, channel: int = 1, current: float = 4.5):
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        mode = self.source_mode[channel]
        if mode.lower() == 'voltage':
            self.send_command(f":SENSe{channel}:CURRent:PROTection:LEVel {current}")
        else:
            self.send_command(f":SOURce{channel}:CURRent:LEVel:IMMediate:AMPLitude {current}")

    def set_ch_output_state(self, channel: int = 1, state: bool = True):
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        self.send_command(f'OUTPut{channel} {"ON" if state else "OFF"}')

    def set_ch_voltage_range(self, channel: int = 1, range_type: Union[Literal['AUTO', 'FIXED'], str] = "AUTO", range_val: Union[Literal['MIN', "MAX", "DEF"], float, str] = "DEF"):
        """
        设置电压量程

        Args:
            channel: int
            range_type: 'AUTO', 'FIXED'
            range_val: 量程值(V) 或 "AUTO", "MIN", "MAX", "DEF"
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        if isinstance(range_val, float):
            if range_val not in [0.2, 2, 20, 200]:
                raise ValueError(f"the range_val (value: {range_val}) only match at [0.2, 2, 20, 200]")
        mode = self.source_mode[channel]
        if mode.lower() == 'voltage':
            self.send_command(f":SOURce{channel}:VOLTage:RANGe:AUTO {'ON' if range_type == 'AUTO' else 'OFF'}")
            self.send_command(f":SOURce{channel}:VOLTage:RANGe{':AUTO:LLIMit' if range_type == 'AUTO' else ''} {range_val}")
        else:
            self.send_command(f":SENSe{channel}:VOLTage:RANGe:AUTO {'ON' if range_type == 'AUTO' else 'OFF'}")
            self.send_command(f":SENSe{channel}:VOLTage:RANGe{':AUTO:LLIMit' if range_type == 'AUTO' else ''} {range_val}")

    def set_ch_current_range(self, channel: int = 1, range_type: Union[Literal['AUTO', 'FIXED'], str] = "AUTO", range_val: Union[Literal['MIN', "MAX", "DEF"], float, str] = "DEF"):
        """
        设置电流量程

        Args:
            channel: int
            range_type: 'AUTO', 'FIXED'
            range_val: 量程值(A) 或 "AUTO", "MIN", "MAX", "DEF"
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        if isinstance(range_val, float):
            if range_val not in [100e-9, 1e-6, 10e-6, 100e-6, 1e-3, 10e-3, 100e-3, 1, 1.5, 3, 10]:
                raise ValueError(f"the range_val (value: {range_val}) only match at [100e-9, 1e-6, 10e-6, 100e-6, 1e-3, 10e-3, 100e-3, 1, 1.5, 3, 10]")
        mode = self.source_mode[channel]
        if mode.lower() == 'voltage':
            self.send_command(f":SENSe{channel}:CURRent:RANGe:AUTO {'ON' if range_type == 'AUTO' else 'OFF'}")
            self.send_command(f":SENSe{channel}:CURRent:RANGe{':AUTO:LLIMit' if range_type == 'AUTO' else ''} {range_val}")
        else:
            self.send_command(f":SOURce{channel}:CURRent:RANGe:AUTO {'ON' if range_type == 'AUTO' else 'OFF'}")
            self.send_command(f":SOURce{channel}:CURRent:RANGe{':AUTO:LLIMit' if range_type == 'AUTO' else ''} {range_val}")

    def set_ch_resistance_range(self, channel: int = 1,
                                range_type: Union[Literal['AUTO', 'FIXED'], str] = "AUTO",
                                range_val: Union[Literal['AUTO', 'MIN', "MAX", "DEF"], float, str] = "DEF",
                                low_range_val: Union[Literal['AUTO', 'MIN', "MAX", "DEF"], float, str] = "DEF"
                                ):
        """
        设置电流量程

        Args:
            channel: int
            range_type: 'AUTO', 'FIXED'
            range_val: 量程值(ohm) 或 "AUTO", "MIN", "MAX", "DEF"
            low_range_val: 量程值(ohm) 或 "AUTO", "MIN", "MAX", "DEF"
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        self.send_command(f":SENSe{channel}:RESistance:MODE Manual")
        if range_type == "OFF":
            self.set_ch_measurement_functions(channel, state="OFF", function1="RESistance", function2=None, function3=None)
            return
        elif range_type == "V/I":
            self.set_ch_measurement_functions(channel, function3="RESistance")
            return
        if isinstance(range_val, float):
            if range_val not in [2, 20, 200, 2000, 20000, 200000, 2000000, 20000000, 200000000]:
                raise ValueError(f"the range_val (value: {range_val}) only match at [2, 20, 200, 2000, 20000, 200000, 2000000, 20000000, 200000000]")
        if isinstance(low_range_val, float):
            if low_range_val not in [2, 20, 200, 2000, 20000, 200000, 2000000, 20000000, 200000000]:
                raise ValueError(f"the range_val (value: {low_range_val}) only match at [2, 20, 200, 2000, 20000, 200000, 2000000, 20000000, 200000000]")
        self.send_command(f":SENSe{channel}:RESistance:MODE AUTO")
        self.set_ch_measurement_functions(channel, function3="RESistance")
        self.send_command(f":SENSe{channel}:RESistance:RANGe:AUTO {'ON' if range_type == 'AUTO' else 'OFF'}")
        if range_type == 'AUTO':
            self.send_command(f":SENSe{channel}:RESistance:RANGe:AUTO:ULIMit {range_val}")
            self.send_command(f":SENSe{channel}:RESistance:RANGe:AUTO:LLIMit {low_range_val}")
        else:
            self.send_command(f":SENSe{channel}:RESistance:RANGe {range_val}")

    def set_ch_integration_time(self, channel: int = 1, function: Union[Literal['VOLTage', 'CURRent', 'RESistance'], str] = "VOLTage",
                                mode: Union[Literal['AUTO', 'APER', 'NPLC'], str] = "AUTO", state: bool = True,
                                ms_time: Union[Literal['MINimum', 'MAXimum', 'DEFault'], float, None] = None,
                                nplc: Union[Literal['MINimum', 'MAXimum', 'DEFault'], float, None] = None):
        """
        设置积分时间

        Args:
            channel: int
            function: "VOLTage", "CURRent", "RESistance"
            mode: "AUTO", "APER", "NPLC"
            state: auto bool
            ms_time: 'MINimum', 'MAXimum', 'DEFault' or +8E-6 to +2 seconds
            nplc: 'MINimum', 'MAXimum', 'DEFault' or +4E-4 to +100 for 50 Hz or +4.8E-4 to +120 for 60 Hz
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        if function not in ['VOLTage', 'CURRent', 'RESistance']:
            raise ValueError("the function only match at ['VOLTage', 'CURRent', 'RESistance']")
        if mode not in ['AUTO', 'APER', 'NPLC']:
            raise ValueError("the mode only match at ['AUTO', 'APER', 'NPLC']")
        if mode == "AUTO":
            self.send_command(f":SENSe{channel}:{function}:APER:AUTO {'ON' if state else 'OFF'}")
            self.send_command(f":SENSe{channel}:{function}:NPLCycles:AUTO {'ON' if state else 'OFF'}")
        else:
            value = ms_time if mode == "APER" else nplc
            cmd = f":SENSe{channel}:{function}:{mode} {value}"
            self.send_command(cmd)

    def set_ch_measurement_functions(self, channel: int = 1,
                                     state: Union[Literal['ON', 'OFF'], str] = "ON",
                                     function1: Union[Literal['VOLTage', 'CURRent', 'RESistance'], str] = "VOLTage",
                                     function2: Union[Literal['VOLTage', 'CURRent', 'RESistance'], str, None] = "CURRent",
                                     function3: Union[Literal['VOLTage', 'CURRent', 'RESistance'], str, None] = None):
        """
        设置测量功能

        Args:
            channel: int
            state: 'ON', 'OFF'
            function1: "VOLTage", "CURRent", "RESistance"
            function2: "VOLTage", "CURRent", "RESistance"
            function3: "VOLTage", "CURRent", "RESistance"
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        # if state == "ON":
        #     self.send_command(f":SENSe{channel}:FUNCtion:OFF:ALL")
        funcs = []
        for func in [function1, function2, function3]:
            if func:
                funcs.append(f'"{func}"')
        self.send_command(f":SENSe{channel}:FUNCtion:{state} {','.join(funcs)}")
        # datas = self.send_command(f":SENSe{channel}:FUNCtion:ON?")
        # return [value.strip() for value in str(datas).split(",")]

    def measure_ch_voltage(self, channel: int = 1, unit: str = ''):
        """测量电压"""
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        value = float(self.send_command(f":MEASure:VOLTage? (@{channel})"))
        return self.change_value_to_scale(value, unit=unit)

    def measure_ch_current(self, channel: int = 1, unit: str = ''):
        """测量电流"""
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        value = float(self.send_command(f":MEASure:CURRent? (@{channel})"))
        return self.change_value_to_scale(value, unit=unit)

    def measure_ch_resistance(self, channel: int = 1, unit: str = ''):
        """测量电阻"""
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        value = float(self.send_command(f":MEASure:RESistance? (@{channel})"))
        return self.change_value_to_scale(value, unit=unit)

    def get_ch_all_measure(self, channel: int = 1):
        """return the 'set_measure_functions' command set data"""
        datas = self.send_command(f":MEASure? (@{channel})")
        return [float(value.strip()) for value in str(datas).split(",")]

    def set_sweep(self, mode: Union[Literal['LINear', "LOGarithmic", "OFF"], str],
                  start: float = 0, stop: float = 0,
                  points: Union[Literal['MINimum', 'MAXimum', 'DEFault'], int, None] = None,
                  step: Union[Literal['MINimum', 'MAXimum', 'DEFault'], float, None] = None,
                  channel: int = 1, double_stair: bool = False):
        """
        设置电压扫描

        Args:
            channel: int
            mode: 'LINear', "LOGarithmic", "OFF"
            start: 起始
            stop: 停止
            points: 点数
            step: 步进
            double_stair: bool
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        source = self.source_mode[channel]
        if mode == "OFF":
            self.send_command(f":SOURce{channel}:{source}:MODE FIXed")
            return
        # 设置扫描模式
        self.send_command(f":SOURce{channel}:{source}:MODE SWEep")

        self.send_command(f":SOURce{channel}:SWEep:SPACing {'LOGarithmic' if 'log' in mode.lower() else 'LINear'}")
        self.send_command(f":SOURce{channel}:SWEep:STAir {'DOUBle' if double_stair else 'SINGle'}")

        # 设置起始和停止值
        self.send_command(f":SOURce{channel}:{source}:STARt {start}")
        self.send_command(f":SOURce{channel}:{source}:STOP {stop}")

        # 设置点数
        if 'log' in mode.lower() and points:
            self.send_command(f":SOURce{channel}:{source}:POINts {points}")

        # 设置步进
        if 'line' in mode.lower() and step:
            self.send_command(f":SOURce{channel}:{source}:STEP {step}")

    def set_pulse(
            self, mode: Union[Literal["ON", "OFF"], str],
            peak: float = 0, delay: float = 0, width: float = 0,
            channel: int = 1
    ):
        """
        设置电压扫描

        Args:
            channel: int
            mode: 'ON', "OFF"
            peak: float V
            delay: flat s
            width: float s
        """
        if channel not in self.source_mode.keys():
            raise ValueError(f"the channel number only match at {self.source_mode.keys()}")
        if mode == "OFF":
            self.send_command(f":SOURce{channel}:FUNCtion DC")
            return
        # 设置扫描模式
        self.send_command(f":SOURce{channel}:FUNCtion PULSe")

        # source = self.source_mode[channel]
        # sweep_mode = self.send_command(f":SOURce{channel}:{source}:MODE?")
        # if "sweep" != sweep_mode.lower():
        #     self.send_command(f":SOURce{channel}:PULSe:PEAK {peak}")

        self.send_command(f":SOURce{channel}:PULSe:DELay {delay}")
        self.send_command(f":SOURce{channel}:PULSe:WIDTh {width}")

    def initiate_sweep(self):
        """开始扫描测量"""
        self.send_command(":INITiate", wait_for_device=True)

    def fetch_sweep_data(self, channel: int = 1):
        """获取扫描数据"""
        return self.send_command(f":FETCh:ARRay? (@{channel})")

    def set_output_off_mode(self, channel: int = 1, mode="NORM"):
        """
        设置输出关闭模式

        Args:
            channel: int
            mode: "NORM", "HIZ", 或 "ZERO"
        """
        cmd = f":OUTPut{channel}:OFF:MODE {mode}"
        self.send_command(cmd)

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
            self._virtual_device.write("HCOP:SDUM:DATA:FORMat BMP")
            self._virtual_device.write("HCOP:SDUM:DATA?")

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


class Instrument_Dryrun(B2900Agent):
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

    def measure_ch_voltage(self, channel: int = 1, unit: str = ''):
        self.send_command(f"{channel} read voltage")
        stat_voltage = self.set_value_to_scale(1, unit)
        end_voltage = self.set_value_to_scale(10, unit)
        response = round(random.uniform(stat_voltage, end_voltage), 6)
        return response

    def measure_ch_current(self, channel: int = 1, unit: str = ''):
        self.send_command(f"{channel} read voltage")
        stat_voltage = self.set_value_to_scale(1, unit)
        end_voltage = self.set_value_to_scale(999, unit)
        response = round(random.uniform(stat_voltage, end_voltage), 6)
        return response


def main():
    virtual_device = B2900Agent('USB0::0x0957::0x8C18::MY51142334::INSTR')
    virtual_device.connect()
    virtual_device.set_source_mode(1, "VOLTage")
    virtual_device.set_ch_voltage(1, 0.5)
    virtual_device.set_ch_current(1, 0.01)
    virtual_device.set_ch_voltage_range(1, "FIXED", 2)
    virtual_device.set_ch_current_range(1, "AUTO")
    virtual_device.set_ch_integration_time(1, "VOLTage", 'NPLC', nplc=1.0)
    virtual_device.set_ch_integration_time(1, "CURRent", 'NPLC', nplc=1.0)
    virtual_device.set_ch_output_state(1, True)
    time.sleep(2)
    virtual_device.set_ch_output_state(1, False)
    virtual_device.disconnect()


if __name__ == '__main__':
    main()
