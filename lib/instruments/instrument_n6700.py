
import logging
import os
import random
import re
import sys
import math
from dataclasses import dataclass, field
from typing import Dict, Union, List
from typing import Literal

from instrument import Instrument
from modules_check import DEFAULT_N6700_MODULES, DEFAULT_N6700_PATTERNS

sys.path.append(os.path.dirname(os.path.realpath(__file__)))

FUNC_Shape = ["NONE", "STEP", "RAMP", "STAircase", "SINusoid", "PULSe", "TRAPezoid", "EXPonential", "UDEFined", "CDWell", "SEQuence"]


class ModuleIdentifier:
    DCPower = "DC Power"
    SMU = "Source Measure Unit"
    ELoad = "Electronic Load"
    PMode = "Precision DC Power"

    def __init__(self):
        self.modules = dict(DEFAULT_N6700_MODULES)
        self.module_patterns = dict(DEFAULT_N6700_PATTERNS)

        self.compiled_patterns = {}
        for module_type, patterns in self.module_patterns.items():
            compiled = []
            for pattern in patterns:
                if 'x' in pattern:
                    regex = pattern.replace('x', r'\d')
                    compiled.append(re.compile(f"^{regex}$"))
                else:
                    compiled.append(re.compile(f"^{re.escape(pattern)}$"))
            self.compiled_patterns[module_type] = compiled

    def update_config(self, config: dict):
        """
        更新module数据， config格式：

        "Modules": {
            "N6731B": {
                "Description": "50W 5V DC Power Module",
                "PowerRating": 50,
                "VoltageRating": 5,
                "CurrentRating": 10,
            },
        },

        "Patterns": {
            "DC Power": ["N673xB", "N674xB", "N677xA", "N675xA", "N676xA"],
        }
        """
        self.modules = config.get("Modules", self.modules)
        self.module_patterns = config.get("Patterns", self.module_patterns)

    def get_module_info(self, module: str):
        """
        识别模块类型
        """
        return self.modules.get(module, {}).copy()

    def identify(self, module_name: str) -> str:
        """
        识别模块类型
        """
        for module_type, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                if pattern.match(module_name):
                    return module_type
        return "Unknown"

    def get_all_module_types(self):
        """
        获取指定类型的所有可能模块名称模式
        """
        return self.module_patterns.keys()

    def get_all_matching_modules(self, module_type: str) -> List[str]:
        """
        获取指定类型的所有可能模块名称模式
        """
        return self.module_patterns.get(module_type, [])

    def is_module_supported(self, module: str, module_type: str) -> bool:
        """
        检查模块是否被支持
        """
        return self.identify(module) == module_type


@dataclass
class ModuleInfo:
    """
    通道信息 - 根据N6705编程手册优化

    Attributes:
        ModuleType: 型号
        ModuleSN: 序列号
        Description: 详细描述
        ModuleOption: 额外配置信息
        PowerRating: 额定功率(W)
        VoltageRating: 电压额定范围(V)
        CurrentRating: 电流额定范围(A)
        VoltageRange: 电压可设置的range列表
        CurrentRange: 电流可设置的range列表
        PowerRange: 功率可设置的range列表
        Emulation: Emulation列表
        Operating: Operating列表
    """
    ModuleType: str
    ModuleSN: str
    Description: str
    ModuleOption: str

    PowerRating: float
    VoltageRating: float
    CurrentRating: float

    VoltageRange: List[float] = field(default_factory=list)
    CurrentRange: List[float] = field(default_factory=list)
    PowerRange: List[float] = field(default_factory=list)
    ResistanceRange: List[float] = field(default_factory=list)

    Emulation: List[str] = field(default_factory=list)
    Operating: List[str] = field(default_factory=list)

    def supports_emulation(self, emulation_type: str) -> bool:
        """检查是否支持特定测量类型"""
        return emulation_type in self.Emulation

    def supports_operating(self, operating_type: str) -> bool:
        """检查是否支持特定测量类型"""
        return operating_type in self.Operating


class N6700Agent(Instrument):
    """
    Keysight N67xx 系列电源分析仪驱动
    """
    Max_Channel = 4

    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)
        self._module_info: Dict[int, ModuleInfo] = {}
        self.connect(reset=False)
        self._detect_channels()
        self.disconnect()

    def _detect_channels(self):
        """检测并初始化所有通道的模块信息"""
        self._module_info.clear()

        try:
            # 获取系统通道数量
            self.Max_Channel = int(self.send_command("SYSTem:CHANnel:COUNt?"))

            # 获取安装模块的通道列表
            module_cat_response = self.send_command("SYSTem:GROup:CATalog?")
            module_cat_channel_list = []

            # 解析通道列表，处理可能的引号和空格
            for channel_str in module_cat_response.split(","):
                channel_str = channel_str.replace('"', '')
                if channel_str and channel_str.isdigit():
                    module_cat_channel_list.append(int(channel_str))

            self.logger.info(f"{self.name} channel number is {self.Max_Channel}, "
                             f"modules installed at channels: {module_cat_channel_list}")

            # 为每个安装模块的通道获取详细信息
            for channel_index in module_cat_channel_list:
                if channel_index < 1 or channel_index > self.Max_Channel:
                    self.logger.warning(f"Invalid channel index {channel_index}, skipping")
                    continue

                try:
                    # 获取模块序列号和型号
                    module_sn = self.send_command(f"SYSTem:CHANnel:SERial? (@{channel_index})")
                    module_type = self.send_command(f"SYSTem:CHANnel:MODel? (@{channel_index})")
                    module_option = self.send_command(f"SYSTem:CHANnel:OPTion? (@{channel_index})")

                    # 从预定义字典获取模块基础信息
                    module_data = identifier.get_module_info(module_type)
                    if not module_data:
                        self.logger.error(f"the {module_type} module not find info, please edit to device_list.json!")
                        continue
                    module_info = ModuleInfo(ModuleType=module_type, ModuleSN=module_sn, ModuleOption=module_option, **module_data)

                    # 获取电压和电流的范围
                    vol_max_range = float(self.send_command(f"VOLTage:RANGe? MAX,(@{channel_index})"))
                    vol_cur_range = float(self.send_command(f"VOLTage:RANGe? (@{channel_index})"))
                    vol_min_range = float(self.send_command(f"VOLTage:RANGe? MIN,(@{channel_index})"))
                    vol_range = sorted(set(module_info.VoltageRange + [vol_min_range, vol_cur_range, vol_max_range]))
                    module_info.VoltageRange = vol_range
                    cur_max_range = float(self.send_command(f"CURRent:RANGe? MAX,(@{channel_index})"))
                    cur_cur_range = float(self.send_command(f"CURRent:RANGe? (@{channel_index})"))
                    cur_min_range = float(self.send_command(f"CURRent:RANGe? MIN,(@{channel_index})"))
                    cur_range = sorted(set(module_info.CurrentRange + [cur_min_range, cur_cur_range, cur_max_range]))
                    module_info.CurrentRange = cur_range
                    if identifier.is_module_supported(module_type, identifier.ELoad):
                        pwr_max_range = float(self.send_command(f"POWer:RANGe? MAX,(@{channel_index})"))
                        pwr_cur_range = float(self.send_command(f"POWer:RANGe? (@{channel_index})"))
                        pwr_min_range = float(self.send_command(f"POWer:RANGe? MIN,(@{channel_index})"))
                        pwr_range = sorted(set(module_info.PowerRange + [pwr_min_range, pwr_cur_range, pwr_max_range]))
                        module_info.PowerRange = pwr_range
                    module_info.Operating = [item.lower() for item in module_info.Operating]

                    self._module_info[channel_index] = module_info
                    self.logger.info(f"Channel {channel_index}: {module_type} (SN: {module_sn}) - "
                                     f"Voltage: {module_info.VoltageRating}V, "
                                     f"Current: {module_info.CurrentRating}A, "
                                     f"Power: {module_info.PowerRating}W"
                                     )

                except (ValueError, KeyError) as e:
                    self.logger.error(f"Error processing channel {channel_index}: {e}")
                    continue
                except Exception as e:
                    self.logger.error(f"Unexpected error on channel {channel_index}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Failed to detect channels: {e}")
            raise

        self.logger.info(f"Successfully detected {len(self._module_info)} modules")

    def get_ch_module_info(self, channel: int):
        return self._module_info[channel]

    def get_all_module_info(self):
        return self._module_info

    def update_module_info(self, channel: int, info: ModuleInfo):
        self._module_info[channel] = info

    def set_window_meter(self, only: bool = False):
        if only:
            self.send_command(f"DISPlay:WINDow:VIEW METER1")
        else:
            self.send_command(f"DISPlay:WINDow:VIEW METER4")

    def set_ch_emulation(self, channel: int, emulation='PS2Q'):
        """
        This command specifies the emulation type for models
        "N6705_Programmer_Reference_Guide" Page428 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not info.supports_emulation(emulation):
            raise ValueError(f"emulation cannot much in {info.Emulation}")
        self.send_command(f'SOURce:EMULation {emulation},(@{channel})')
        return self.send_command(f'SOURce:EMULation? (@{channel})')

    def set_ch_operating(self, channel: int, operating='Voltage'):
        """
        This command selects whether the output regulation on models N678xA is in voltage priority or current priority mode.
        In voltage priority mode the output is controlled by a bipolar constant voltage feedback loop,
        which maintains the output voltage at its positive or negative programmed setting.
        In current priority mode the output is controlled by a bipolar constant current feedback loop,
        which maintains the output sourcing or sinking current at its programmed setting.
        Refer to chapter 6 in the N6705 User's Guide for more information about priority mode operation
        "N6705_Programmer_Reference_Guide" Page430 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        operating = operating.lower()
        if not info.supports_operating(operating):
            raise ValueError(f"operating only much in {info.Operating}")
        if identifier.is_module_supported(info.ModuleType, identifier.PMode):
            if operating == 'voltage':
                self.send_command(f'OUTPut:PMOD VOLTage,(@{channel})')
            elif operating == 'current':
                self.send_command(f'OUTP:PMOD CURRent,(@{channel})')
            return self.send_command(f'OUTPut:PMOD? (@{channel})')
        if identifier.is_module_supported(info.ModuleType, identifier.SMU):
            emulating = self.send_command(f'SOURce:EMULation? (@{channel})')
            if emulating not in ["PS4Q", "PS2Q", "PS1Q"]:
                return
            if operating == 'voltage':
                self.send_command(f'FUNCtion VOLT,(@{channel})')
            elif operating == 'current':
                self.send_command(f'FUNCtion CURR,(@{channel})')
            return self.send_command(f'FUNCtion? (@{channel})')
        raise Exception(f"the {info.ModuleType} Module not has this command")

    def set_ch_voltage(self, channel: int, voltage: Union[Literal['maximum', 'MIN', 'MAX'], float] = "MIN"):
        """
        This command sets the immediate voltage level of the specified output channel.
        Units are in volts. The immediate level is the output voltage setting.
        "N6705_Programmer_Reference_Guide" Page454 for more details.
        <voltage>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the voltage rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        vol_cur_range = float(self.send_command(f"VOLTage:RANGe? (@{channel})"))
        find_out = False
        if voltage > vol_cur_range:
            for top_voltage in info.VoltageRange:
                if top_voltage >= voltage:
                    self.send_command(f'VOLTage:RANGe {top_voltage},(@{channel})')
                    find_out = True
                    break
        else:
            find_out = True
        if not find_out:
            self.send_command(f'VOLTage:RANGe MAX,(@{channel})')
            self.send_command(f'VOLTage:LEVel MAX,(@{channel})')
        else:
            self.send_command(f'VOLTage:LEVel {voltage},(@{channel})')
        return float(self.send_command(f'VOLTage? (@{channel})'))

    def set_ch_voltage_range(self, channel: int, voltage_range: Union[Literal['maximum', 'MIN', 'MAX', 'Auto'], float] = "MAX"):
        """
        This command sets the immediate voltage level of the specified output channel.
        Units are in volts. The immediate level is the output voltage setting.
        "N6705_Programmer_Reference_Guide" Page454 for more details.
        <voltage>
            0 - maximum | MIN | MAX
            Values entered are model dependent.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        vol_cur_range = float(self.send_command(f"VOLTage:RANGe? (@{channel})"))
        if voltage_range == vol_cur_range:
            return
        info = self._module_info[channel]
        if voltage_range not in info.VoltageRange:
            raise ValueError(f"the range_list only match at {info.VoltageRange}")
        self.send_command(f'VOLTage:RANGe {voltage_range},(@{channel})')
        return float(self.send_command(f'VOLTage:RANGe? (@{channel})'))

    def set_ch_voltage_limit(self, channel: int, limit: float, neg_limit: float = None):
        """
        This command sets the positive current limit of the specified output channel. Units are in amperes.
        If [SOURce:]CURRent:LIMit:COUPle is enabled, this command also sets the value of the negative current limit.
        Refer to chapter 6 in the N6705 User's Guide under "Voltage Priority" for more information about current limit operation.
        "N6705_Programmer_Reference_Guide" Page407 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.SMU):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        vol_cur_range = float(self.send_command(f"VOLTage:RANGe? (@{channel})"))
        power = info.PowerRating
        voltage = vol_cur_range / 1.02
        if limit * voltage > power:
            raise ValueError(f"The current value exceeds the allowable range! current voltage range is {voltage}V, but power rating just {power}W")
        if neg_limit:
            self.send_command(f'VOLTage:LIMit:COUPle OFF,(@{channel})')
            self.send_command(f'VOLTage:LIMit:POSitive {limit},(@{channel})')
            self.send_command(f'VOLTage:LIMit:NEGative {neg_limit},(@{channel})')
        else:
            self.send_command(f'VOLTage:LIMit:COUPle ON,(@{channel})')
            self.send_command(f'VOLTage:LIMit {limit},(@{channel})')
        return self.send_command(f'VOLTage:LIMit? (@{channel})')

    def set_ch_current(self, channel: int, current=0.08):
        """
        This command sets the immediate current level of the specified output channel.
        Units are in amperes. The immediate level is the output current setting.
        "N6705_Programmer_Reference_Guide" Page404 for more details.
        <current>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the current rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        cur_cur_range = float(self.send_command(f"CURRent:RANGe? (@{channel})"))
        range_list = info.CurrentRange
        find_out = False
        if current > cur_cur_range:
            for top_value in range_list:
                if top_value >= current:
                    self.send_command(f'CURRent:RANGe {top_value},(@{channel})')
                    find_out = False
                    break
        else:
            find_out = True
        if not find_out:
            self.send_command(f'CURRent:RANGe MAX,(@{channel})')
            self.send_command(f'CURRent:LEVel MAX,(@{channel})')
        else:
            self.send_command(f'CURRent:LEVel {current},(@{channel})')
        return self.send_command(f'CURRent:LEVel? (@{channel})')

    def set_ch_current_range(self, channel: int, current_range: Union[Literal['maximum', 'MIN', 'MAX'], float] = "MAX"):
        """
        This command sets the output current range on models that have multiple ranges.
        The value that you enter must be the highest value in amperes that you expect to source.
        The instrument selects the range with the best resolution for the value entered.
        "N6705_Programmer_Reference_Guide" Page416 for more details.
        <voltage>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the voltage rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        cur_cur_range = float(self.send_command(f"CURRent:RANGe? (@{channel})"))
        if cur_cur_range == current_range:
            return
        info = self._module_info[channel]
        range_list = info.CurrentRange
        if current_range not in range_list:
            raise ValueError(f"the range_list only match at {range_list}")
        self.send_command(f'CURRent:RANGe {current_range},(@{channel})')
        return float(self.send_command(f'CURRent:RANGe? (@{channel})'))

    def set_ch_current_limit(self, channel: int, limit: float, neg_limit: float = None):
        """
        This command sets the positive current limit of the specified output channel. Units are in amperes.
        If [SOURce:]CURRent:LIMit:COUPle is enabled, this command also sets the value of the negative current limit.
        Refer to chapter 6 in the N6705 User's Guide under "Voltage Priority" for more information about current limit operation.
        "N6705_Programmer_Reference_Guide" Page460 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.SMU):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        power = info.PowerRating
        cur_cur_range = float(self.send_command(f"CURRent:RANGe? (@{channel})"))
        current = cur_cur_range / 1.02
        if limit * current > power:
            raise ValueError(f"The current value exceeds the allowable range! Current range is {current}A, but power rating just {power}W")
        if neg_limit:
            self.send_command(f'CURRent:LIMit:COUPle OFF,(@{channel})')
            self.send_command(f'CURRent:LIMit:POSitive {limit},(@{channel})')
            self.send_command(f'CURRent:LIMit:NEGative {neg_limit},(@{channel})')
        else:
            self.send_command(f'CURRent:LIMit:COUPle ON,(@{channel})')
            self.send_command(f'CURRent:LIMit {limit},(@{channel})')
        return float(self.send_command(f'CURRent:LIMit? (@{channel})'))

    def set_ch_power(self, channel: int, power=50):
        """
        This command sets the immediate current level of the specified output channel.
        Units are in amperes. The immediate level is the output current setting.
        "N6705_Programmer_Reference_Guide" Page404 for more details.
        <current>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the current rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        pwr_cur_range = float(self.send_command(f"POWer:RANGe? (@{channel})"))
        range_list = info.PowerRange
        find_out = False
        if power > pwr_cur_range:
            for top_value in range_list:
                if top_value >= power:
                    self.send_command(f'POWer:RANGe {top_value},(@{channel})')
                    find_out = True
                    break
        else:
            find_out = True
        if not find_out:
            self.send_command(f'POWer:RANGe MAX,(@{channel})')
            self.send_command(f'POWer:LEVel MAX,(@{channel})')
        else:
            self.send_command(f'POWer:LEVel {power},(@{channel})')
        return self.send_command(f'POWer:LEVel? (@{channel})')

    def set_ch_power_range(self, channel: int, power_range: Union[Literal['maximum', 'MIN', 'MAX'], float] = "MAX"):
        """
        This command sets the output current range on models that have multiple ranges.
        The value that you enter must be the highest value in amperes that you expect to source.
        The instrument selects the range with the best resolution for the value entered.
        "N6705_Programmer_Reference_Guide" Page416 for more details.
        <voltage>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the voltage rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        pwr_cur_range = float(self.send_command(f"POWer:RANGe? (@{channel})"))
        if pwr_cur_range == power_range:
            return
        range_list = info.CurrentRange
        if power_range not in range_list:
            raise ValueError(f"the range_list only match at {range_list}")
        self.send_command(f'POWer:RANGe {power_range},(@{channel})')
        return float(self.send_command(f'POWer:RANGe? (@{channel})'))

    def set_ch_power_limit(self, channel: int, limit: float):
        """
        This command sets the positive current limit of the specified output channel. Units are in amperes.
        If [SOURce:]CURRent:LIMit:COUPle is enabled, this command also sets the value of the negative current limit.
        Refer to chapter 6 in the N6705 User's Guide under "Voltage Priority" for more information about current limit operation.
        "N6705_Programmer_Reference_Guide" Page407 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if identifier.is_module_supported(info.ModuleType, identifier.SMU):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        power = info.PowerRating
        if limit > power:
            raise ValueError(f"The current value exceeds the allowable range! Power rating is {power}W")
        self.send_command(f'POWer:LIMit {limit},(@{channel})')
        return float(self.send_command(f'POWer:LIMit? (@{channel})'))

    def set_ch_resistance(self, channel: int, resistance=50):
        """
        This command sets the immediate current level of the specified output channel.
        Units are in amperes. The immediate level is the output current setting.
        "N6705_Programmer_Reference_Guide" Page404 for more details.
        <current>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the current rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        pwr_cur_range = float(self.send_command(f":RESistance:RANGe? (@{channel})"))
        range_list = info.PowerRange
        find_out = False
        if resistance > pwr_cur_range:
            for top_value in range_list:
                if top_value >= resistance:
                    self.send_command(f':RESistance:RANGe {top_value},(@{channel})')
                    find_out = True
                    break
        if not find_out:
            self.send_command(f':RESistance:RANGe MAX,(@{channel})')
            self.send_command(f':RESistance:LEVel MAX,(@{channel})')
        else:
            self.send_command(f':RESistance:LEVel {resistance},(@{channel})')
        return self.send_command(f':RESistance:LEVel? (@{channel})')

    def set_ch_resistance_range(self, channel: int, resistance_range: Union[Literal['maximum', 'MIN', 'MAX'], float] = "MAX"):
        """
        This command sets the output current range on models that have multiple ranges.
        The value that you enter must be the highest value in amperes that you expect to source.
        The instrument selects the range with the best resolution for the value entered.
        "N6705_Programmer_Reference_Guide" Page416 for more details.
        <voltage>
            0 - maximum | MIN | MAX
            The maximum value is dependent on the voltage rating of the power module.
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        cur_range = float(self.send_command(f"POWer:RANGe? (@{channel})"))
        if cur_range == resistance_range:
            return
        range_list = info.ResistanceRange
        list_has = False
        for info in range_list:
            if str(resistance_range) in info:
                list_has = True
                break
        if not list_has:
            raise ValueError(f"the range_list only match at {range_list}")
        self.send_command(f'RESistance:RANGe {resistance_range},(@{channel})')
        return float(self.send_command(f'RESistance:RANGe? (@{channel})'))

    def set_output_short(self, channel: int, on: bool):
        """
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        if on:
            self.send_command(f'OUTPut:SHORt:STATe ON,(@{channel})')
        else:
            self.send_command(f'OUTPut:SHORt:STATe OFF,(@{channel})')
        return float(self.send_command(f'OUTPut:SHORt:STATe? (@{channel})'))

    def set_output_inhibit(self, channel: int, mode: str):
        """
        This command selects the mode of operation of the Inhibit input (INH).
        The inhibit function shuts down ALL output channels in response to an external signal on the Inhibit input.
        If an output channel has been turned off by OUTPut[:STATe], the inhibit function does not affect the output channel while it is in the OFF state.
        The Inhibit mode setting is stored in non-volatile memory.
        "N6705_Programmer_Reference_Guide" Page158 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if not identifier.is_module_supported(info.ModuleType, identifier.ELoad):
            raise Exception(f"the {info.ModuleType} Module not has this command")
        if channel not in ["OFF", "LIVE", "LATChing"]:
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        self.send_command(f'OUTPut:INHibit:MODE {mode},(@{channel})')
        return self.send_command(f'OUTPut:INHibit:MODE? (@{channel})')

    def set_output_polarity(self, channel: int, on: bool):
        """
        This command sets the positive current limit of the specified output channel. Units are in amperes.
        If [SOURce:]CURRent:LIMit:COUPle is enabled, this command also sets the value of the negative current limit.
        Refer to chapter 6 in the N6705 User's Guide under "Voltage Priority" for more information about current limit operation.
        "N6705_Programmer_Reference_Guide" Page407 for more details.
        """
        if channel not in self._module_info.keys():
            raise ValueError(f"the channel number only match at {self._module_info.keys()}")
        info = self._module_info[channel]
        if '760' not in info.ModuleOption:
            raise Exception(f"the {info.ModuleType} Module not has this command")
        if on:
            self.send_command(f'OUTPut:RELay:POLarity REV,(@{channel})')
        else:
            self.send_command(f'OUTPut:RELay:POLarity NORMal,(@{channel})')
        return float(self.send_command(f'OUTPut:RELay:POLarity? (@{channel})'))

    def set_ch_output_state(self, channel: int, state: Union[Literal['ON', 'OFF', 1, 0], bool] = "ON"):
        """
        This command enables or disables the specified output channel(s).
        The enabled state is ON (1); the disabled state is OFF (0).
        The state of a disabled output is a condition of zero output voltage and zero source current.
        <state>
            OFF | 0 | ON | 1
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        channel_state = "OFF"
        if state and state != "OFF":
            channel_state = "ON"
        self.send_command(f'OUTPut {channel_state},(@{channel})')
        return int(self.send_command(f'OUTPut? (@{channel})'))

    def measure_ch_current(self, channel: int, unit=''):
        """
        Description:
        This query initiates and triggers a measurement, and returns the average output current in amperes.
        "N6705_Programmer_Reference_Guide" Page 112 for more details.
        Syntax:
        MEASure[:SCALar]:CURRent[:DC]? (@<channel_num>)
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        current = self.send_command(f'MEASure:CURRent? (@{channel})')
        value = self.change_value_to_scale(float(current), unit=unit)
        return value

    def measure_ch_voltage(self, channel: int, unit=''):
        """
        Description:
            This query initiates and triggers a measurement, and returns the average output voltage in volts.
            "N6705_Programmer_Reference_Guide" Page 121 for more details.
        Syntax:
            MEASure[:SCALar]:VOLTage[:DC]? (@<chanlist>)
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        voltage = self.send_command(f'MEASure:VOLTage? (@{channel})')
        value = self.change_value_to_scale(float(voltage), unit=unit)
        return value

    def measure_ch_power(self, channel: int, unit=''):
        """
        Description:
            This query initiates and triggers a measurement, and returns the average output voltage in volts.
            "N6705_Programmer_Reference_Guide" Page 121 for more details.
        Syntax:
            MEASure[:SCALar]:VOLTage[:DC]? (@<chanlist>)
        <channel>
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4
            (@1:3) - channels 1 through 3
        """
        voltage = self.send_command(f'MEASure:POWer? (@{channel})')
        value = self.change_value_to_scale(float(voltage), unit=unit)
        return value

    def set_arb_func(self, channel: int, shape='NONE'):
        """
        This command sets the function of the arbitrary waveform generator.
        @param shape:
            STEP/RAMP/STAircase/SINusoid/PULSe/TRAPezoid/EXPonential/UDEFined/CDWell/SEQuence/NONE
        @param channel:
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4 (@1:3) - channels 1 through 3
        @return:
        """
        if shape not in FUNC_Shape:
            raise ValueError(f"shape only match in {FUNC_Shape}")
        self.send_command(f'ARB:FUNCtion:SHAP {shape},(@{channel})')
        return self.send_command(f'ARB:FUNCtion:SHAP? (@{channel})')

    def start_arb_on_single_ch(self, channel: int):
        """
        Description:
            INIT:TRAN (@1)
            This command enables the output trigger system. When an output trigger is initiated,
            an event on a selected trigger source causes the specified triggering action to occur.
            If the trigger system is not initiated, all triggers are ignored.

            This command generates an immediate transient trigger regardless of the selected trigger source.
            Output triggers affect the following functions: voltage, current, and current limit.
        """
        self.send_command(f'INIT:TRAN (@{channel})')
        self.send_command(f'TRIG:TRAN (@{channel})')

    def stop_arb_on_single_ch(self, channel: int):
        """
        Description:
            This command cancels any triggered actions and returns the trigger system back to the Idle state.
            ABORt:TRANsient also resets the WTG-tran bit in the Operation Condition Status register.
        """
        self.send_command(f'ABOR:TRAN (@{channel})')

    def press_arb_run(self):
        """
        Description:
            INIT:TRAN (@1)
            This command enables the output trigger system. When an output trigger is initiated,
            an event on a selected trigger source causes the specified triggering action to occur.
            If the trigger system is not initiated, all triggers are ignored.

            This command generates an immediate transient trigger regardless of the selected trigger source.
            Output triggers affect the following functions: voltage, current, and current limit.
        """
        channel_list = []
        channel_num = self.send_command('SYSTem:GROup:CATalog?').replace('"', '').split(',')
        for i in channel_num:
            arb_type = self.send_command(f'ARB:FUNC:SHAP? (@{i})')
            if arb_type != 'NONE':
                channel_list.append(i)
        channel_numbers = ','.join(channel_list)
        self.send_command(f'INIT:TRAN (@{channel_numbers})')
        self.send_command(f'TRIG:TRAN (@{channel_numbers})')

    def press_arb_stop(self):
        """
        Description:
            This command cancels any triggered actions and returns the trigger system back to the Idle state.
            ABORt:TRANsient also resets the WTG-tran bit in the Operation Condition Status register.
        """
        channel_list = []
        channel_num = self.send_command('SYSTem:GROup:CATalog?').replace('"', '').split(',')
        for i in channel_num:
            arb_type = self.send_command(f'ARB:FUNC:SHAP? (@{i})')
            if arb_type != 'NONE':
                channel_list.append(i)
        channel_numbers = ','.join(channel_list)
        self.send_command(f'ABOR:TRAN (@{channel_numbers})')

    def set_arb_type(self, channel: int, arb_type='VOLTage'):
        """
        This command determines the output value when the arbitrary waveform terminates. The state is either ON (1) or OFF (0).
        When ON, the output voltage or current remains at the last ARB value. The last voltage or current ARB value becomes the IMMediate value when the ARB completes.
        When OFF, and also when the ARB is aborted, the output returns to the settings that were in effect before the ARB started.
        "N6705_Programmer_Reference_Guide" Page 323 for more details.
        @param arb_type:
            "Voltage", "Current", "Resistance", "Power"
        @param channel:
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4 (@1:3) - channels 1 through 3
        @return:
        """
        if arb_type.lower() not in ["voltage", "current", "resistance", "power"]:
            raise ValueError("count only match in ['DC', 'ARB']")
        self.send_command(f'ARB:FUNCtion:TYPE {arb_type},(@{channel})')
        return self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')

    def set_arb_after_status(self, channel: int, status='Arb'):
        """
        This command determines the output value when the arbitrary waveform terminates. The state is either ON (1) or OFF (0).
        When ON, the output voltage or current remains at the last ARB value. The last voltage or current ARB value becomes the IMMediate value when the ARB completes.
        When OFF, and also when the ARB is aborted, the output returns to the settings that were in effect before the ARB started.
        "N6705_Programmer_Reference_Guide" Page 323 for more details.
        @param status:
            Arb, DC
        @param channel:
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4 (@1:3) - channels 1 through 3
        @return:
        """
        if status.lower() not in ["dc", "arb"]:
            raise ValueError("count only match in ['DC', 'ARB']")
        option = 'OFF'
        if status.lower() == 'arb':
            option = 'ON'
        self.send_command(f'ARB:TERMinate:LAST {option},(@{channel})')

    def set_arb_repeat(self, channel: int, count: Union[int, Literal['Continuous', 'continuous']] = 1):
        """
        This command sets the number of times that the arbitrary waveform is repeated.
        The repeat count range is 1 through >16 million. For constant-dwell Arbs only, the maximum count is limited to 256.
        "N6705_Programmer_Reference_Guide" Page 222 for more details.
        @param count:
            1 - 16,777,216 | MIN | MAX | INFinity
        @param channel:
            One or more channels.
            (@2) - channel 2
            (@1,4) - channels 1 and 4 (@1:3) - channels 1 through 3
        @return:
        """
        arb_count = 'INF'
        if isinstance(count, int):
            if count < 1:
                raise ValueError("count must greater than 1")
            arb_count = count
        self.send_command(f'ARB:COUNt {arb_count},(@{channel})')

    def set_arb_step_options(self, channel: int,
                             v0: float = 0, v1: float = 1,
                             t0: float = 1, t1: float = 1):
        self.set_arb_func(channel=channel, shape='STEP')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:STEP:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STEP:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STEP:END {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STEP:END:TIM {t1},(@{channel})')

    def set_arb_ramp_options(self, channel: int,
                             v0: float = 0, v1: float = 1,
                             t0: float = 1, t1: float = 1, t2: float = 1,
                             after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='RAMP')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:RAMP:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:RAMP:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:RAMP:RTIM {t1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:RAMP:END {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:RAMP:END:TIM {t2},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

    def set_arb_stair_options(self, channel: int,
                              v0: float = 0, v1: float = 1, step: int = 10,
                              t0: float = 1, t1: float = 1, t2: float = 1,
                              after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='STAircase')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:TIM {t1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:END {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:END:TIM {t2},(@{channel})')
        self.send_command(f'ARB:{arb_type}:STA:NST {step},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

    def set_arb_sine_options(self, channel: int,
                             v0: float = 0, v1: float = 1, freq: float = 1,
                             after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='SINusoid')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:SIN:AMPL {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:SIN:OFFS {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:SIN:FREQ {freq},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

    def set_arb_pulse_options(self, channel: int,
                              v0: float = 0, v1: float = 1,
                              t0: float = 1, t1: float = 1, t2: float = 1,
                              after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='PULSe')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:PULS:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:PULS:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:PULS:TOP {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:PULS:TOP:TIM {t1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:PULS:END:TIM {t2},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

    def set_arb_trap_options(self, channel: int,
                             v0: float = 0, v1: float = 1,
                             t0: float = 1, t1: float = 1, t2: float = 1, t3: float = 1, t4: float = 1,
                             after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='TRAPezoid')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:TOP {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:TOP:TIM {t2},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:END:TIM {t4},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:TOP:RTIM {t1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:TRAP:END:FTIM {t3},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

    def set_arb_expon_options(self, channel: int,
                              v0: float = 0, v1: float = 1,
                              t0: float = 1, t1: float = 1, tc: float = 1,
                              after_sate: str = 'DC', repeat: Union[int, Literal['Continuous', 'continuous']] = 1):
        self.set_arb_func(channel=channel, shape='EXPonential')
        arb_type = self.send_command(f'ARB:FUNCtion:TYPE? (@{channel})')
        self.send_command(f'ARB:{arb_type}:EXP:STAR {v0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:EXP:STAR:TIM {t0},(@{channel})')
        self.send_command(f'ARB:{arb_type}:EXP:END {v1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:EXP:TIM {t1},(@{channel})')
        self.send_command(f'ARB:{arb_type}:EXP:TCON {tc},(@{channel})')
        self.set_arb_after_status(channel=channel, status=after_sate)
        self.set_arb_repeat(channel=channel, count=repeat)

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


ModuleDemoList = ["", "N6761A", "N6781A", "N6791A", "N6784A"]


class Instrument_Dryrun(N6700Agent):
    def __init__(self, instrument_address, timeout: float = 5000, logger: logging.Logger = None):
        super().__init__(instrument_address, timeout, logger=logger)

    def _detect_channels(self):
        self._module_info.clear()
        self.Max_Channel = 4
        module_cat_channel_list = [1, 2, 3, 4]
        for index in module_cat_channel_list:
            module_type = ModuleDemoList[index]
            if not module_type:
                continue
            module_data = identifier.get_module_info(module_type)
            if not module_data:
                self.logger.error(f"the {module_type} module not find info, please edit to device_list.json!")
                continue
            module_info = ModuleInfo(ModuleType=module_type, ModuleSN="MY114514(demo)", ModuleOption="", **module_data)
            voltage_rating = math.ceil((module_data["VoltageRating"]*1.02) * 100) / 100
            vol_range = sorted(set(module_info.VoltageRange + [voltage_rating]))
            module_info.VoltageRange = vol_range
            current_rating = math.ceil((module_data["CurrentRating"]*1.02) * 100) / 100
            cur_range = sorted(set(module_info.CurrentRange + [current_rating]))
            module_info.CurrentRange = cur_range
            power_rating = math.ceil((module_data["PowerRating"]*1.02) * 100) / 100
            pwr_range = sorted(set(module_info.PowerRange + [power_rating]))
            module_info.PowerRange = pwr_range
            module_info.Operating = [item.lower() for item in module_info.Operating]
            self._module_info[index] = module_info

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

    def measure_ch_voltage(self, channel: int, unit=''):
        self.send_command(f"{channel} read voltage")
        stat_voltage = self.set_value_to_scale(1, unit)
        end_voltage = self.set_value_to_scale(10, unit)
        response = round(random.uniform(stat_voltage, end_voltage), 6)
        return response

    def measure_ch_current(self, channel: int, unit=''):
        self.send_command(f"{channel} read voltage")
        stat_voltage = self.set_value_to_scale(1, unit)
        end_voltage = self.set_value_to_scale(999, unit)
        response = round(random.uniform(stat_voltage, end_voltage), 6)
        return response

    def set_ch_output_state(self, channel: int, state: Union[Literal['ON', 'OFF', 1, 0], bool] = "ON"):
        return 1 if state != "OFF" or state != 0 else 0


identifier = ModuleIdentifier()


def main():
    virtual_device = N6700Agent('USB0::0x2A8D::0x0F02::MY56006826::INSTR')
    virtual_device.connect()
    virtual_device.set_window_meter(True)
    virtual_device.set_arb_pulse_options(channel=2)
    vol = virtual_device.measure_ch_voltage(2, unit="m")
    print(f"vol={vol}")
    virtual_device.disconnect()


if __name__ == '__main__':
    main()
