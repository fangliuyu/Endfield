import logging
import os
import random
import re
import statistics
import sys
import time
import traceback
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Union
from typing import Literal
from pyvisa.errors import VisaIOError

from lib.custommath import teardown_str_value_and_unit
from .instrument import Instrument

sys.path.append(os.path.dirname(os.path.realpath(__file__)))


class MeasurementFunction:
    """测量功能枚举"""
    DC_VOLTAGE = "VOLT:DC"
    AC_VOLTAGE = "VOLT:AC"
    DC_CURRENT = "CURR:DC"
    AC_CURRENT = "CURR:AC"
    RESISTANCE_2W = "RES"
    RESISTANCE_4W = "FRES"
    CAPACITANCE = "CAP"
    FREQUENCY = "FREQ"
    PERIOD = "PER"
    CONTINUITY = "CONT"
    DIODE = "DIOD"
    TEMPERATURE = "TEMP"


MeasurementUnit = {
    MeasurementFunction.DC_VOLTAGE: "V",
    MeasurementFunction.AC_VOLTAGE: "V",
    MeasurementFunction.DC_CURRENT: "A",
    MeasurementFunction.AC_CURRENT: "A",
    MeasurementFunction.RESISTANCE_2W: "Ω",
    MeasurementFunction.RESISTANCE_4W: "Ω",
    MeasurementFunction.CAPACITANCE: "F",
    MeasurementFunction.FREQUENCY: "Hz",
    MeasurementFunction.PERIOD: "s",
    MeasurementFunction.TEMPERATURE: "°C",
    MeasurementFunction.CONTINUITY: "Ω",
    MeasurementFunction.DIODE: "V",
}
APER_LIST = ["CURR:DC", "VOLT:DC", "RES"]
NO_RANGE_AUTO_LIST = ["FREQ", "PER", "DIOD", "CONT", "TEMP"]


def unit_from_range_or_function(func: str, range_text: str = None) -> str:
    if func in [MeasurementFunction.FREQUENCY, MeasurementFunction.PERIOD]:
        return MeasurementUnit.get(func, "")
    range_value = re.sub(r'[^-+\d.]+', '', range_text)
    if range_value != "":
        _, unit = teardown_str_value_and_unit(range_text)
        return unit
    unit = MeasurementUnit.get(func, "")
    if range_text not in ["Auto", "on", "off"]:
        unit = range_text
    return unit


class TriggerSource:
    """触发源枚举"""
    IMMEDIATE = "IMM"
    BUS = "BUS"
    EXTERNAL = "EXT"


class TriggerSlope:
    """触发边沿枚举"""
    POSITIVE = "POS"  # 上升沿
    NEGATIVE = "NEG"  # 下降沿


class SyncRole:
    """同步角色枚举"""
    STANDALONE = "standalone"  # 独立运行
    MASTER = "master"  # 主设备（输出触发信号）
    SLAVE = "slave"  # 从设备（接收触发信号）


class MeasurementMode:
    """测量模式枚举"""
    STANDARD = "standard"  # 标准高精度直流模式
    DIGITIZE = "digitize"  # 高速数字化采样模式


def check_function(obj: object, func: str) -> bool:
    # 简单字符串检查
    valid_funcs = [str(v).lower() for v in obj.__dict__.values()]
    if func.lower() not in valid_funcs:
        return False
    return True


@dataclass
class MeasurementConfig:
    """
    测量配置

    Attributes:
        function: 测量功能
        aperture_mode: 电源线周期模式（影响精度和速度）
        aperture_value: 电源线周期数（影响精度和速度）
        auto_range: 是否自动量程
        manual_range: 手动量程值
        auto_zero: 自动调零设置
        impedance: 输入阻抗设置
        sample: 采样数
        trigger_source: 触发源
        trigger_delay: 触发延迟
    """
    digitize_mode: bool = False
    function: str = MeasurementFunction.DC_VOLTAGE

    aperture_mode: str = "NPLC"
    aperture_value: float = 1.0

    auto_range: bool = True
    manual_range: Optional[float] = None

    auto_zero: bool = True
    impedance: str = "AUTO"

    trigger_source: str = TriggerSource.IMMEDIATE
    trigger_delay: float = 0.0
    sample: int = 1
    sample_spin: int = 0
    sample_count: int = 1


class DmmAgent(Instrument):
    """
    Keysight 数字万用表驱动
    """

    # 数字化采样参数范围
    DIGITIZE_SAMPLE_RATE_MIN = 1000  # 最小采样率 1kS/s
    DIGITIZE_SAMPLE_RATE_MAX = 50000  # 最大采样率 50kS/s
    DIGITIZE_SAMPLE_COUNT_MAX = 1000000  # 最大采样点数

    def __init__(self, instrument_address, timeout: float = 50000, logger: logging.Logger = None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)
        self.current_function: str = ''
        self.current_mode: str = MeasurementMode.STANDARD
        self._config: Optional[MeasurementConfig] = None

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
        self._initialize_device()
        self.logger.info(f"{self.name} 已连接")

    def disconnect(self):
        if self._virtual_device and self._connected:
            self.send_command("SYSTem:LOCal")
            self._virtual_device.close()
        self._connected = False
        self.logger.info(f"{self.name} 已断开连接")

    def reset(self):
        self.send_command("*RST")
        self.send_command("*CLS")
        self._initialize_device()

    def _initialize_device(self) -> None:

        self._config = MeasurementConfig()

        now_func = self.send_command("FUNC?")
        now_func = str(now_func).replace("\"", "")
        if now_func in ["VOLT", "CURR"]:
            now_func += ":DC"

        if now_func in APER_LIST:
            aperture_status = self.send_command(f"{now_func}:APER:ENAB?")
            mode = "NPLC" if int(aperture_status) == 0 else "APERture"
            self._config.aperture_mode = mode
            self._config.aperture_value = self.send_command(f"{now_func}:{mode}?")

            auto_zero_val = self.send_command(f"{now_func}:ZERO:AUTO?")
            self._config.auto_zero = bool(int(auto_zero_val))

        if now_func not in NO_RANGE_AUTO_LIST:
            range_status_val = self.send_command(f"{now_func}:RANG:AUTO?")
            self._config.auto_range = bool(int(range_status_val))
            self._config.manual_range = self.send_command(f"{now_func}:RANG?")

        now_impedance = "Auto"
        if now_func == "VOLT:DC":
            auto_impedance = self.send_command(f"{now_func}:IMPedance:AUTO?")
            if int(auto_impedance) == 0:
                now_impedance = "HI-Z"
        self._config.impedance = now_impedance

        self._config.trigger_source = self.send_command("TRIG:SOUR?")
        self._config.sample = int(float(self.send_command("TRIG:COUN?")))
        self._config.trigger_delay = int(float(self.send_command("TRIG:DEL?")) * 1000)
        self._config.sample_count = int(float(self.send_command("SAMP:COUN?")))
        self._config.sample_spin = int(float(self.send_command("SAMP:TIM?")) * 1000)

        self._digitize_config = None
        self.current_function = now_func
        self.current_mode = MeasurementMode.STANDARD

        self.logger.info(f"万用表 {self.name} 已初始化到默认状态")

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

    def set_measurement_function(self, func: str) -> None:
        """
        设置测量功能

        Args:
            func: 功能代码 ("VOLT:DC", "CURR:DC", "RES", 等)
        """

        checked = check_function(MeasurementFunction, func)
        if not checked:
            raise ValueError(
                f"无效的功能: {func}，可选: {[str(v).lower() for v in MeasurementFunction.__dict__.values()]}"
            )
        if func == self._config.function or func == self.current_function:
            self.logger.warning(f"当前测量功能已为{self._config.function}， 跳过设置为 {func}")
            return

        self.send_command(f"FUNC '{func}'")
        ext_str = ""
        if func in [
            MeasurementFunction.FREQUENCY,
            MeasurementFunction.PERIOD,
        ]:
            ext_str = ":VOLT"
        self.current_function = func + ext_str
        self._config.function = func
        self.logger.info(f"{self.name} 测试类型 切换为 {self.current_function}")

    def set_range(self, range_value: Union[int, float, str]) -> None:
        """
        设置测量量程

        Args:
            range_value: 量程值
        """
        if self.current_function is None:
            raise Exception("未配置测量功能")
        can_set_range = False
        if self.current_function not in [
            MeasurementFunction.CONTINUITY,
            MeasurementFunction.DIODE,
            MeasurementFunction.TEMPERATURE,
        ]:
            can_set_range = True
        if not can_set_range:
            # 如果不能设置量程则跳过
            return

        if str(range_value).lower() == "auto":
            if self._config.auto_range:
                self.logger.warning(f"当前量程已为{self._config.auto_range}， 跳过设置为 {range_value}")
                return
            self.send_command(f"{self.current_function}:RANG:AUTO ON")
            self._config.auto_range = True
        else:
            self.send_command(f"{self.current_function}:RANG:AUTO OFF")
            self._config.auto_range = False
            self._config.manual_range = range_value
            if (
                    self.current_function == MeasurementFunction.DC_CURRENT
                    and float(range_value) == 10
            ):
                self.send_command(f"{self.current_function}:TERMinals {range_value}")
                return
            elif self.current_function == MeasurementFunction.DC_CURRENT:
                self.send_command(f"{self.current_function}:TERMinals 3")
            self.send_command(f"{self.current_function}:RANG {range_value}")

        self.logger.info(f"{self.name} 量程 设置为{range_value}")

    def set_aperture(self, mode: Union[Literal["NPLC", "APERture"], str], value: Union[int, float, str]) -> None:
        """
        设置 NPLC（电源线周期数）

        Args:
            mode: 模式
            value: 值,当mode为APERture时单位为ms
        """
        if self.current_function is None:
            raise Exception("未配置测量功能")
        value = float(value)
        if self.current_function in ["CURR:DC", "VOLT:DC"]:
            if mode != "NPLC":
                value /= 1000
            if mode == "NPLC":
                if not 0.001 <= value <= 100:
                    raise ValueError("NPLC 必须在 0.001 到 100 之间")
            elif not 0.02 <= value <= 1000:
                raise ValueError("APERture 必须在 0.02 到 1000 之间")
            if self.current_function in [
                MeasurementFunction.DC_VOLTAGE,
                MeasurementFunction.DC_CURRENT,
                MeasurementFunction.RESISTANCE_2W,
                MeasurementFunction.RESISTANCE_4W
            ]:
                if mode != "NPLC":
                    self.send_command(f"{self.current_function}:APER:ENAB ON")
                else:
                    self.send_command(f"{self.current_function}:APER:ENAB OFF")
                self.send_command(f"{self.current_function}:{mode} {value}")
                self._config.aperture_mode = mode
                self._config.aperture_value = value
                self.logger.info(f"{self.name} {mode} 设置为 {value}")
        else:
            pass

    def set_auto_zero(self, enable: bool) -> None:
        if self.current_function is None:
            raise Exception("未配置测量功能")
        if self.current_function in [
            MeasurementFunction.DC_VOLTAGE,
            MeasurementFunction.DC_CURRENT,
            MeasurementFunction.RESISTANCE_2W,
            MeasurementFunction.RESISTANCE_4W
        ]:
            self.send_command(f"{self.current_function}:ZERO:AUTO {1 if enable else 0}")
            self._config.auto_zero = True

    def set_impedance_HiZ(self, enable: bool) -> None:
        if self.current_function is None:
            raise Exception("未配置测量功能")
        if self.current_function in [
            MeasurementFunction.DC_VOLTAGE,
            MeasurementFunction.DC_CURRENT,
            MeasurementFunction.RESISTANCE_2W,
            MeasurementFunction.RESISTANCE_4W
        ]:
            self.send_command(f"{self.current_function}:IMPedance:AUTO {1 if enable else 0}")
            self._config.impedance = "HI-Z" if enable else "AUTO"

    def set_multiple_sample(
            self, count: int = 1, delay_ms: float = 0, space_ms: float = 0, sample: int = 1
    ):
        """
        读取多个测量值

        Args:
            count: 测量次数
            delay_ms: 测量触发延迟
            space_ms: 测量间隔
            sample: 每次采样次数
        Return:
            last_timeout: 设置前的timeout
            now_time: 设置后的timeout
        """
        current_timeout = self._virtual_device.timeout
        timeout = float(count) * (delay_ms + float(sample) * (1.2 * space_ms + 0.2))
        if timeout < current_timeout:
            timeout = current_timeout
        self.logger.debug(f"set timeout to {timeout}")
        self.set_timeout(timeout)
        self.send_command("TRIG:SOUR TIMER")
        self.send_command(f"TRIG:COUN {count}")
        self.send_command(f"TRIG:DEL {delay_ms / 1000}")
        self.send_command(f"SAMP:COUN {sample}")
        self.send_command(f"SAMP:TIM {space_ms / 1000}")
        self.send_command("SENS:SPEED MAX")
        return current_timeout, timeout

    def read_measurement(self, unit: str = "") -> float:
        """
        执行单次测量

        Returns:
            float: 测量值
        """
        # value_str = self.send_command(f"MEAS:{self._config.function}?")
        # self.send_command(f"FUNC '{self._config.function}'")
        value_str = self.send_command("READ?")
        value = self.change_value_to_scale(float(value_str), unit)
        self.logger.debug(f"{self.name} 测量{self._config.function}值: {value}")
        return value

    def read_multiple(
            self, count: int = 1, delay_ms: float = 0, space_ms: float = 0, sample: int = 1, unit: str = ''
    ) -> List[float]:
        """
        读取多个测量值

        Args:
            count: 测量次数
            delay_ms: 测量触发延迟
            space_ms: 测量间隔
            sample: 每次采样次数
            unit: 单位
        Returns:
            list: 测量列表
        """
        current_timeout = self.timeout
        try:
            current_timeout, _ = self.set_multiple_sample(count, delay_ms, space_ms, sample)
            self.send_command("INIT")
            data_str = self.send_command("FETC?", wait_for_device=True)
            data = data_str.split(',')
            results = []
            for value in data:
                value_f = self.change_value_to_scale(float(value), unit)
                results.append(value_f)

            return results
        finally:
            self.set_timeout(current_timeout)

    def read_fetch(self, unit: str = '') -> List[float]:
        """
        读取多个测量值
        Returns:
            list: 测量列表
        """
        self.send_command("INIT")
        data_str = self.send_command("FETC?", wait_for_device=True)
        data = data_str.split(',')
        results = []
        for value in data:
            value_f = self.change_value_to_scale(float(value), unit)
            results.append(value_f)

        return results

    def set_dynamic_capture(
            self,
            trigger_source: str,
            trigger_slope: str = "POS",
            enable_trigger_out: bool = False,
    ) -> None:
        """配置34465A内部buffer采样。"""
        self.send_command(f"TRIG:SOUR {trigger_source}")
        if trigger_source.upper().startswith("EXT"):
            self.send_command(f"TRIG:SLOP {trigger_slope}")
        self.send_command("TRIG:DEL 0")
        self.send_command(f"TRIG:COUN MIN")
        self.send_command(f"SAMP:COUN MIN")
        self.send_command("SAMP:SOUR TIM")
        self.send_command(f"SAMP:TIM MIN")

        try:
            if not enable_trigger_out:
                self.send_command("OUTP:TRIG OFF")
                return
            self.send_command(f"OUTP:TRIG:SLOP {trigger_slope}")
            self.send_command("OUTP:TRIG:SOUR AINT")
            self.send_command("OUTP:TRIG ON")
        except Exception as e:
            self.logger.warning(f"{self.name} 不支持 Trig Out 配置，硬件同步可能无效: {e}")

    def restore_dynamic_capture(self) -> None:
        """恢复到单点READ?友好的状态"""
        try:
            self.send_command("OUTP:TRIG OFF")
            self.send_command("TRIG:SOUR IMM")
            self.send_command("SAMP:COUN 1")
            self.send_command("SAMP:SOUR IMM")
            self.send_command("*CLS")
        except Exception as e:
            self.logger.warning(f"{self.name}恢复动态采样状态失败, {e}", exc_info=True)

    def stop_action(self):
        try:
            self.send_command("ABORt")
        except Exception as e:
            self.logger.warning(str(e))
        self.send_command("*CLS")

    def get_unit(self) -> str:
        """获取当前测量功能的单位"""
        if self.current_function:
            return MeasurementUnit.get(self.current_function, "")
        return ""

    def get_measurement_info(self) -> dict[str, Any]:
        """获取当前测量配置信息"""
        self._initialize_device()
        info = self._config.__dict__
        return info


def calculate_power_from_waveforms(
        voltage_waveform: List[float],
        current_waveform: List[float]
) -> Dict[str, Any]:
    """
    从同步采集的电压电流波形计算瞬时功率

    用于动态功耗分析。

    Args:
        voltage_waveform: 电压采样数组
        current_waveform: 电流采样数组

    Returns:
        Dict: 包含功率统计数据
            - power_waveform: 瞬时功率数组
            - average_power: 平均功率
            - peak_power: 峰值功率
            - min_power: 最小功率
            - rms_power: RMS功率
    """
    import math

    if len(voltage_waveform) != len(current_waveform):
        raise ValueError(
            f"波形长度不匹配: 电压{len(voltage_waveform)}点, "
            f"电流{len(current_waveform)}点"
        )

    if not voltage_waveform:
        raise ValueError("波形数据为空")

    # 计算瞬时功率 P(n) = V(n) * I(n)
    power_waveform = [
        abs(v * i) for v, i in zip(voltage_waveform, current_waveform)
    ]

    # 计算统计数据
    average_power = statistics.mean(power_waveform)
    peak_power = max(power_waveform)
    min_power = min(power_waveform)

    # 计算RMS功率
    rms_power = math.sqrt(
        sum(p ** 2 for p in power_waveform) / len(power_waveform)
    )

    return {
        'power_waveform': power_waveform,
        'average_power': average_power,
        'peak_power': peak_power,
        'min_power': min_power,
        'rms_power': rms_power,
        'sample_count': len(power_waveform),
    }


class Instrument_Dryrun(DmmAgent):
    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address, timeout, logger=logger)
        self._config = MeasurementConfig()

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

    def read_multiple(
            self, count: int = 1, delay_ms: float = 0, space_ms: float = 0, sample: int = 1, unit: str = ''
    ) -> List[float]:
        results = []
        for _ in range(count):
            time.sleep(delay_ms / 1000)
            for _ in range(sample):
                value = round(random.uniform(3.5, 5.0), 2)
                results.append(value)
                time.sleep(1.5 * space_ms / 1000)
        return results

    def get_measurement_info(self) -> dict[str, Any]:
        """获取当前测量配置信息"""
        info = self._config.__dict__
        return info


def main():
    virtual_dmm = DmmAgent('USB0::0x2A8D::0x0101::MY60009053::INSTR')
    virtual_dmm.connect()
    virtual_dmm.set_measurement_function("VOLT:DC")
    vol = virtual_dmm.read_measurement(unit="m")
    print(f"vol={vol}")
    vol = virtual_dmm.read_multiple(5, 1, 0, 1, "m")
    print(vol)
    virtual_dmm.disconnect()


if __name__ == '__main__':
    main()
