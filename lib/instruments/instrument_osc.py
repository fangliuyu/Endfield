import logging
import os
import re
import sys
import time
import traceback
from enum import Enum
from os import PathLike

import numpy as np
from pathlib import Path
from typing import Optional, Union, Literal

import pyvisa

from lib.custommath import change_str_value_to_scale
from .instrument import Instrument
from .device_list import DEFAULT_DEVICE_LISTS, get_device_patterns

sys.path.append(os.path.dirname(os.path.realpath(__file__)))


class SourceWaveformType(Enum):
    """测量功能枚举"""
    CH = "CHANnel"
    Func = "FUNCtion"
    Ref = "WMEMory"
    Math = "MATH"
    SBus = "SBUS"
    Dig = "DIGital"
    Bus = "BUS"
    WaveGen = "WaveGen"
    POD = "POD"


class SourceTriggerType(Enum):
    CH = "CHANnel"
    Dig = "DIGital"
    WGEN = "WGEN"
    EXT = "EXTernal"
    LINE = "LINE"
    modulation = "WMOD"


class TriggerModeType(Enum):
    EDGE = "EDGE"
    GLITch = "GLITch"
    PATTern = "PATTern"
    TV = "TV"
    DELay = "DELay"
    EBURst = "EBURst"
    OR = "OR"
    RUNT = "RUNT"
    SHOLd = "SHOLd"
    TRANsition = "TRANsition"
    SBUS1 = "SBUS1"
    SBUS2 = "SBUS2"
    NFC = "NFC"


class TriggerSlopeType(Enum):
    Rising = "POSitive"
    Falling = "NEGative"
    Alternating = "ALTernate"
    Either = "Either"


class FunctionTYPE(Enum):
    # MATH
    Add = "ADD"
    Sub = "SUBTract"
    Mult = "MULTiply"
    Div = "DIVide"
    # Tans
    Diff = "DIFF"
    Intg = "INTegrate"
    FFT = "FFT"
    FFTPhase = "FFTPhase"
    Linear = "LINear"
    Square = "SQUare"
    SQRT = "SQRT"
    Abs = "ABSolute"
    LOG = "LOG"
    LN = "LN"
    EXP = "EXP"
    TEN = "TEN"
    # Filters
    Low = "LOWPass"
    High = "HIGHpass"
    Avg = "AVERage"
    Smooth = "SMOoth"
    Envelope = "ENVelope"
    # Visualizations
    Max = "MAXimum"
    Min = "MINimum"
    Peak = "PEAK"
    MaxHold = "MAXHold"
    MinHold = "MINHold"
    TRENd = "TRENd"
    BTime = "BTIMing"
    BState = "BSTate"


class CursorMode(Enum):
    OFF = "OFF"
    Meas = "MEASurement"
    Manual = "MANual"
    Waveform = "WAVeform"
    Binary = "BINary"
    HEX = "HEX"


Measure_Dict = {
    'ALL': ':MEASure:ALL{read} {source1}',
    # Current
    'Pk-Pk': ':MEASure:VPP{read} {source1}',
    'Max': ':MEASure:VMAX{read} {source1}', 'Min': ':MEASure:VMIN{read} {source1}',
    'Y@X': ":MEASure:YATX{read} {x},{source1}",
    # ----------------
    'Ampl': ':MEASure:VAMPlitude{read} {source1}', 'Top': ':MEASure:VTOP{read} {source1}',
    'Base': ':MEASure:VBASe{read} {source1}',
    # ----------------
    'Overshoot': ':MEASure:OVERshoot{read} {source1}', 'Preshoot': ':MEASure:PREShoot{read} {source1}',
    # ----------------
    'Avg-Cyc': ':MEASure:VAVerage{read} CYCLe,{source1}', 'Avg-FS': ':MEASure:VAVerage{read} {source1}',
    # ----------------
    'DC RMS-Cyc': ':MEASure:VRMS{read} CYCLe,DC,{source1}', 'DC RMS-FS': ':MEASure:VRMS{read} DISPlay,DC,{source1}',
    'AC RMS-Cyc': ':MEASure:VRMS{read} CYCLe,AC,{source1}', 'AC RMS-FS': ':MEASure:VRMS{read} DISPlay,AC,{source1}',
    'Ratio-Cyc': ':MEASure:VRATio{read} CYCLe,{source1},{source2}',
    'Ratio-FS': ':MEASure:VRATio{read} DISPlay,{source1},{source2}',
    # Time
    'Period': ':MEASure:PERiod{read} {source1}', 'Freq': ':MEASure:FREQuency{read} {source1}',
    'Counter': ':MEASure:COUNter{read} {source1}',
    '+Width': ':MEASure:PWIDth{read} {source1}', '-Width': ':MEASure:NWIDth{read} {source1}',
    'Burst Width': ':MEASure:BWIDth{read} {source1}',
    '+Duty': ':MEASure:DUTYcycle{read} {source1}', '-Duty': ':MEASure:NDUTy{read} {source1}',
    'BRate': ':MEASure:BRATe{read} {source1}',
    # ----------------
    'Rise': ':MEASure:RISetime{read} {source1}', 'Fall': ':MEASure:FALLtime{read} {source1}',
    'T@Edge': ":MEASure:TEDGe{read} {slope},{occurrence},{source1}",
    # ----------------
    "Delay": ":MEASure:DELay{read} {edge_select_mode},{source1},{source2}",
    "Phase": ":MEASure:PHASe{read} {source1},{source2}",
    # ----------------
    'X@Min': ':MEASure:XMIN{read} {source1}', 'X@Max': ':MEASure:XMAX{read} {source1}',
    # Count
    '+Pulse Count': ':MEASure:PPULses{read} {source1}', '-Pulse Count': ':MEASure:NPULses{read} {source1}',
    # ----------------
    'Rise Edge': ':MEASure:PEDGes{read} {source1}', 'Fall Edge': ':MEASure:NEDGes{read} {source1}',
    # Mixed
    'Area-Cyc': ':MEASure:AREa{read} CYCLe,{source1}', 'Area-FS': ':MEASure:AREa{read} {source1}',
    "Slew": ':MEASure:SLEWrate{read} {source1},{slope}'
}
Real_Eyes_Measure_Dict = {
    'height': ':MEASure:CGRade:EHEight{read} MEASured,{source}',
    'width': ':MEASure:CGRade:EWIDth{read} MEASured,{source}',
    'one level': ':MEASure:CGRade:OLEVel{read} {source}',
    'zero level': ':MEASure:CGRade:ZLEVel{read} {source}',
    'jitter(RMS)': ':MEASure:CGRade:JITTer{read} RMS,{source}',
    'jitter(PP)': ':MEASure:CGRade:JITTer{read} PP,{source}',
    'crossing': ':MEASure:CGRade:CROSsing{read} {source}',
    'Q factor': ':MEASure:CGRade:QFACtor{read} {source}',
    'DutyCycle(Time)': ':MEASure:CGRade:JITTer{read} TIME,{source}',
    'DutyCycle(PERCent)': ':MEASure:CGRade:JITTer{read} PERCent,{source}',
}


def check_osc_type(osc_info: str, type_list: list[str]) -> bool:
    for name in type_list:
        if name.lower() in osc_info.lower():
            return True
    return False


def create_osc_agent(osc_info: str, address: str, logger=None):
    if "demo" in osc_info:
        return Instrument_Dryrun(instrument_address=address, logger=logger)
    elif check_osc_type(osc_info, get_device_patterns("OSC")["osc_cata"]):
        return InfiniiumCatAOsc(instrument_address=address, logger=logger)
    elif check_osc_type(osc_info, get_device_patterns("OSC")["osc_tek"]):
        return TektronixOsc(instrument_address=address, logger=logger)
    else:
        return OscAgnet(instrument_address=address, logger=logger)


def peel_data(data_in, logger: logging.Logger):
    """
    date_in is an IEEE binary block and interprets the header.
    The function strips off the header and outputs the rest of the data。
    Which used to be saved to a .png file.
    """
    # Grap the header.
    header = str(data_in[0:12])
    logging.debug(f"Header is {header}")
    # Find the start position of the IEEE header, which starts with a '#'.
    start_pos = header.find("#")
    logger.debug(f"Start Position is reported at {start_pos}")

    # if not find start position, return None
    if start_pos < 0:
        logger.debug(f"No start of block found in {header}")
        return None
    else:
        size_of_length = int(header[start_pos + 1])
        logging.debug(f"Size of Length reported as {size_of_length}")
        # Read image size
        image_size = int(header[start_pos + 2:start_pos + 2 + size_of_length])
        logger.debug(f"Size of image reported as {image_size}")
        # return the actual image
        return data_in[start_pos + size_of_length:start_pos + size_of_length + image_size]


def waveform_info(pre, logger: logging.Logger):
    """
    Debug shows out waveform preamble of selected waveform source and returns
    vertical and horizontal scaling and translation information:

    <preamble_block> is:
        FORMAT : int16-0= BYTE, 1 = WORD, 4 = ASCII.
        TYPE : int16-0= NORM, 1 = PEAK, 2 = AVER, 3 = HRES
        POINTS : int32 - number of data points transferred.
        COUNT : int32 - 1 and is always 1.
        XINCREMENT : float64 - time difference between data points.
        XORIGIN : float64 - always the first data point in memory.
        XREFERENCE : int32 - specifies the data point associated with
        x-origin.
        YINCREMENT : float32 - voltage diff between data points.
        YORIGIN : float32 - value is the voltage at center screen.
        YREFERENCE : int32 - specifies the data point where y-origin
        occurs.
    """

    wav_format = pre[0]

    wav_type = pre[1]
    wav_points = pre[2]
    avg_count = pre[3]
    x_increment = pre[4]
    x_origin = pre[5]
    x_ref = pre[6]
    y_increment = pre[7]
    y_origin = pre[8]
    y_ref = pre[9]

    logger.debug(f"\n[waveform Info]\n> number of points: {wav_points}\n> waveform format: {wav_format}\n> waveform type: {wav_type}\n> average count: {avg_count}\n"
                 f"> X increment: {x_increment}\n> X origin: {x_origin}\n> X reference: {x_ref}\n> Y increment: {y_increment}\n> Y origin: {y_origin}\n> Y reference: {y_ref}")
    return x_origin, y_origin, x_increment, y_increment, y_ref


def _validate_source_parameters(source_type: Union[SourceWaveformType, str], source_number: Optional[int]) -> str:
    """验证源参数并返回格式化字符串"""
    if isinstance(source_type, str):
        for source in SourceWaveformType:
            if source.value.lower() == source_type.lower():
                source_type = source
                break
    if not isinstance(source_type, SourceWaveformType):
        raise TypeError("source_type 必须是 SourceWaveformType 枚举")

    if source_number or source_number == 0:
        if source_number <= 0:
            raise ValueError(f"通道号不能低于1")

    return f"{source_type.value}{source_number}"


class OscAgnet(Instrument):
    SOURCE_STATUS = ['ON', 'OFF', 1, 0]
    Image_Format = ['BMP', 'BMP8bit', 'PNG']
    WAVEFORM_TYPES = [member.value for member in SourceWaveformType]
    TRIGGER_MODE_TYPES = [member.value for member in TriggerModeType]
    TRIGGER_SLOPE_TYPES = [member.value for member in TriggerSlopeType]

    def __init__(self, instrument_address, timeout: float = 5000, logger=None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)

    # -------------------------------------------------------------------------------
    #                                 File Command
    # -------------------------------------------------------------------------------
    def get_screen_image(self, image_format: str = 'PNG', color: bool = True, timeout: int = None) -> bytes:
        """
        Reads the screen image data from an InfiniiVision oscilloscope

        Args:
            image_format: 图片格式 in ['BMP', 'BMP8bit', 'PNG']
            color: 是否彩色
            timeout: 超时时间(ms)
        """
        if image_format not in self.Image_Format:
            raise Exception(f"image_format only match in {self.Image_Format}")
        original_timeout = self._virtual_device.timeout
        if timeout:
            self._virtual_device.timeout = timeout

        try:
            self.logger.info(f"截取屏幕 ({image_format} 格式, 超时: {timeout}ms)")
            self.send_command(':HARDCOPY:INKSAVER OFF')
            color_param = "COLOR" if color else "GRAYSCALE"
            self._virtual_device.write(f":DISPLAY:DATA? {image_format},{color_param}")

            raw_data = self._virtual_device.read_raw()

            if raw_data.startswith(b"#"):
                header_len = int(raw_data[1:2])
                data_start = 2 + header_len
                img_data = raw_data[data_start:-1]
                self.logger.debug(f"截图完成: {len(img_data)} 字节")
                return img_data

            self.logger.debug(f"截图完成 (无头部): {len(raw_data)} 字节")
            return raw_data

        except pyvisa.VisaIOError as e:
            if "timeout" in str(e).lower():
                self.logger.error(f"截图超时: {e}")
                raise Exception(f"截图超时 (>{timeout}ms)")
            self.logger.error(f"截图数据获取失败: {e}")
            raise Exception(f"截图数据获取失败: {e}")
        finally:
            if timeout:
                self._virtual_device.timeout = original_timeout

    def file_save_screen(self, image_name: str, save_dir: Union[PathLike[str], str], image_format: str = 'PNG', color: bool = True, timeout: int = 30000):
        """
        saves it to a local directory on the controller PC.
        """
        try:
            original_image_data = self.get_screen_image(image_format, color, timeout)
            if original_image_data:
                peeled_image_data = peel_data(original_image_data, self.logger)

                '''Get Directory'''
                image_dir = Path(save_dir)
                if not image_dir:
                    image_dir = Path(os.path.expanduser('~')) / 'Documents' / 'Pictures'
                if not image_dir.exists():
                    image_dir.mkdir()

                with open(image_dir / image_name, 'wb') as gs_file:
                    gs_file.write(peeled_image_data)
                    gs_file.close()
                self.logger.info(f"ScreenShot saved to: {(image_dir / image_name).as_posix()}")
                return image_name
        except Exception as e:
            self.logger.error(traceback.format_exc())
            raise e

    def file_save_channel_waveform_to_csv(self, save_dir: Union[PathLike[str], str], source_type: Union[SourceWaveformType, str], source_number: int = 1, num_points: int = None, csv_name='csv_data.csv'):
        """
        This command save the waveform of the specified channel as a CSV file on the controller PC.
        """
        source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':waveform:source {source}')
        self.send_command(":WAVeform:POINts:MODE RAW")
        if num_points:
            self.send_command(f':waveform:points {num_points}')
        self.send_command(":waveform:format word")
        self.send_command(":acquire:type NORMal")
        self.send_command(":waveform:byteorder lsbfirst")
        self.send_command(":waveform:unsigned 0")
        self.send_command(":acquire:segmented:count?")
        self.send_command(":waveform:segmented:count?")
        # Display waveform settings
        pre = self.send_command(":waveform:preamble?").split(',')
        x_origin, y_origin, x_increment, y_increment, y_ref = waveform_info(pre, self.logger)

        # Set waveform source
        self.send_command(f':waveform:source {source}')
        self.get_waveform(float(x_origin), float(y_origin), float(x_increment), float(y_increment), float(y_ref), Path(save_dir) / csv_name)

    def get_waveform(self, x_origin, y_origin, x_increment, y_increment, y_ref, csv_path):
        """
        Transfers waveform data to csv.
        """

        # Grab and interpret data
        # data = self._virtual_device.session.query_binary_values(":waveform:data?", datatype=u'h', header_fmt=u'ieee')
        data = self._virtual_device.query_binary_values(":waveform:data?", datatype=u'h', header_fmt=u'ieee')
        data = np.array(data, dtype='f')
        num_points = len(data)

        # Create arrays for all offsets to perform vector calculations
        y_origin_arr = np.array([y_origin] * num_points)
        y_ref_arr = np.array([y_ref] * num_points)
        y_incr_arr = np.array([y_increment] * num_points)

        # Rescale and translate
        ydata = y_origin_arr + (data - y_ref_arr) * y_incr_arr
        xdata = np.arange(x_origin, x_origin + x_increment * num_points, x_increment)
        xdata = xdata[0:num_points]
        if not csv_path.exists():
            csv_path.touch()
        np.savetxt(csv_path, np.c_[xdata, ydata], delimiter=",")
        self.logger.info(f"波形数据已保存到{csv_path}")

    def file_save_setup(self, location: Optional[str] = None, file_name: Optional[str] = None):
        """
        This command saves an oscilloscope setup. file_name should be setup_x.scp x in [0-9]
        """
        if location:
            self.send_command(f':SAVE {location}')
        if file_name:
            self.send_command(f':SAVE "{file_name}"')

    def file_recall_setup(self, location: Optional[str] = None, file_name: Optional[str] = None):
        """
        This command recalls an oscilloscope setup.
        If a file extension is provided as part of a specified <file_name>, it must be ".scp".
        """
        if location:
            self.send_command(f':REC:SET {location}')
        elif file_name:
            self.send_command(f':REC:SET "{file_name}"')

    def file_input_external_setup(self, pc_file_path: Union[int, str, bytes, PathLike[str], PathLike[bytes]]):
        try:
            with open(pc_file_path, 'r') as setup_file:
                setup = setup_file.read()
                self._virtual_device.write_binary_values(':SYSTem:SETup ', setup, datatype='B')
                self.logger.info(f"oscilloscope setup set with date from local file: {pc_file_path}")
        except Exception as ex:
            self.logger.error(ex)

    def file_query_system_setup(self, pc_file_path: Union[int, str, bytes, PathLike[str], PathLike[bytes]]):
        self._virtual_device.write(':SYSTem:SETup?')
        setup = self._virtual_device.read_raw()

        '''Get Directory'''
        try:
            with open(pc_file_path, 'wb') as setup_file:
                setup_file.write(setup)
                self.logger.info(f"oscilloscope setup saved to local file: {pc_file_path}")
        except Exception as ex:
            self.logger.error(ex)

    def file_recall_file(self, file_name: str):
        """
        This command specifies the source for any RECall operations.
        This command specifies a file's base name only, without path information or an extension.
        """
        self.send_command(f':RCL:FIL "{file_name}"')

    def _perform_self_calibration(self):
        success = not bool(self.send_command(command='*CAL?'))
        return success

    # -------------------------------------------------------------------------------
    #                                 Run Control Command
    # -------------------------------------------------------------------------------
    def run_ctl_press_run(self):
        """
        This function is the same as pressing the Run key on the front panel.
        """
        self.send_command(':RUN')

    def run_ctl_press_single(self):
        """
        This function is the same as pressing the single key on the front panel.
        """
        self.send_command(':SINGle')

    def run_ctl_press_stop(self):
        """
        This function is the same as pressing the Stop key on the front panel.
        """
        self.send_command(':STOP')

    # -------------------------------------------------------------------------------
    #                                 Horizontal Command
    # -------------------------------------------------------------------------------
    def horizon_set_time_base_scale(self, scale_value: float = 1.0, scale_suffix: str = 's'):
        """
        This command sets the full-scale horizontal time in seconds for the main window.
        The range is 10 times the current time-per-division setting.
        """
        if scale_value <= 0:
            raise Exception(f"scale_value must > 0")
        scale_value = self.set_value_to_scale(float(scale_value) * 10, scale_suffix)
        self.send_command(f":TIM:RANG {scale_value}")
        return float(self.send_command(f":TIM:RANG?"))

    def horizon_set_time_base_delay(self, delay_value: float = 0.0, delay_suffix: str = 's'):
        """
        time in seconds from the trigger to the display reference in NR3 format
        This command sets the time interval between the trigger event and the display reference point on the screen.
        The maximum position value depends on the time/division settings.
        """
        delay_value = self.set_value_to_scale(float(delay_value), delay_suffix)
        self.send_command(f":TIMebase:POSition {delay_value}")
        return float(self.send_command(f":TIMebase:POSition?"))

    def horizon_set_mode(self, mode: str = 'MAIN'):
        """
        This command sets the current time base. There are four time base modes:
        • MAIN — The normal time base mode is the main time base. It is the default time base mode after the *RST (Reset) command.
        • WINDow — In the WINDow (zoomed or delayed) time base mode, measurements are made in the zoomed time base if possible; otherwise, the measurements are made in the main time base.
        • XY — In the XY mode, the :TIMebase:RANGe, :TIMebase:POSition, and :TIMebase:REFerence commands are not available. No measurements are available in this mode.
        • ROLL — In the ROLL mode, data moves continuously across the display from left to right. The oscilloscope runs continuously and is untriggered. The :TIMebase:REFerence selection changes to RIGHt.
        """
        if mode not in ['MAIN', 'WINDow', 'XY', 'ROLL']:
            raise Exception("delay_suffix only match in l['MAIN', 'WINDow', 'XY', 'ROLL']")
        self.send_command(f":TIMebase:MODE {mode}")

    def horizon_zoom_set_time_scale(self, scale_value: float = 1.0, scale_suffix: str = 's'):
        """This command sets the full-scale horizontal time in seconds for the zoomed (delayed) window.
        The range is 10 times the current zoomed view window seconds per division setting. The main sweep range determines the range for this command.
        The maximum value is one half of the :TIMebase:RANGe value.
        """
        if scale_value <= 0:
            raise Exception(f"scale_value must > 0")
        scale_value = self.set_value_to_scale(float(scale_value) * 10, scale_suffix)
        self.send_command(f":TIMebase:WINDow:RANG {scale_value}")
        return float(self.send_command(f":TIMebase:WINDow:RANG?"))

    def horizon_zoom_set_time_position(self, pose_value: float = 0.0, pose_suffix: str = 's'):
        """
        This command sets the horizontal position in the zoomed (delayed) view of the main sweep.
        The main sweep range and the main sweep horizontal position determine the range for this command.
        The value for this command must keep the zoomed view window within the main sweep range.
        """
        pose_value = self.set_value_to_scale(float(pose_value), pose_suffix)
        self.send_command(f":TIMebase:WINDow:POSition {pose_value}")
        return float(self.send_command(f":TIMebase:WINDow:POSition?"))

    # -------------------------------------------------------------------------------
    #                                 Trigger Command
    # -------------------------------------------------------------------------------
    def trigger_set_mode(self, mode: str = 'AUTO') -> str:
        """
        This command selects the trigger sweep mode.
        When AUTO sweep mode is selected, a baseline is displayed in the absence of a signal.
        If a signal is present but the oscilloscope is not triggered, the unsynchronized signal is displayed instead of a baseline.
         When NORMal sweep mode selected and no trigger is present, the instrument does not sweep, and the data acquired on the previous trigger remains on the screen.
        """
        if mode not in ['AUTO', 'NORMal']:
            raise Exception("mode only match in ['AUTO', 'NORMal']")
        self.send_command(f':TRIGger:SWEep {mode}')
        return self.send_command(f':TRIGger:SWEep?')

    def trigger_set_type(self, trigger_type: str = 'EDGE') -> str:
        """
        This command selects the trigger mode (trigger type).
        """
        if trigger_type not in self.TRIGGER_MODE_TYPES:
            raise Exception(f"trigger_type only match in {self.TRIGGER_MODE_TYPES}")
        self.send_command(f':TRIGger:MODE {trigger_type}')
        return self.send_command(f':TRIGger:MODE?')

    def trigger_set_edge_option(self, source_type: Union[SourceTriggerType, str], source_number: int = None, slope: Union[TriggerSlopeType, str] = TriggerSlopeType.Rising, level: str = '1V'):
        """
        This command set the edge trigger options.
        """
        if isinstance(source_type, SourceTriggerType):
            source = source_type.value
        else:
            source = source_type
        if source not in ["EXTernal", "LINE", "WMOD"]:
            source = _validate_source_parameters(source, source_number)
        if isinstance(slope, TriggerSlopeType):
            slope_type = slope.value
        else:
            slope_type = slope
        self.send_command(':TRIGger:MODE EDGE')
        self.send_command(f':TRIGger:EDGE:SOURce {source}')
        self.send_command(f':TRIGger:EDGE:SLOPE {slope_type}')
        self.send_command(f':TRIGger:EDGE:LEVel {level}')

    # -------------------------------------------------------------------------------
    #                                 Source Command
    # -------------------------------------------------------------------------------
    def source_set_status(self, source_type: Union[SourceWaveformType, str], source_number: int = None, status: Union[str, int] = 'ON'):
        """
        This command set a channel status on the oscilloscope.
        """
        source = _validate_source_parameters(source_type, source_number)

        if status not in self.SOURCE_STATUS:
            raise Exception(f"state only match in {self.SOURCE_STATUS}")
        self.send_command(f':{source}:DISPlay {status}')
        return self.send_command(f':{source}:DISPlay?')

    def source_set_label_status(self, status: Union[str, int] = 'ON'):
        """
        This command set the channel text label status on the oscilloscope.
        """
        if status not in self.SOURCE_STATUS:
            raise Exception(f"state only match in {self.SOURCE_STATUS}")
        self.send_command(f":DISPlay:LABel {status}")
        return self.send_command(f":DISPlay:LABel?")

    def source_set_label(self, label: str, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None):
        """
        This command set a text label to a channel.
        """
        source = _validate_source_parameters(source_type, source_number)
        self.send_command(":DISPlay:LABel ON")
        self.send_command(f':{source}:LABEL "{label}"')
        return self.send_command(f':{source}:LABEL?')

    def source_set_vertical(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None,
                            vertical_value=1.0, vertical_suffix: str = 'mV'):
        """
        This command defines the full-scale vertical axis of the selected channel.
        When using 1:1 probe attenuation, legal values for the range are from 8 mV to 40 V.
        """
        source = _validate_source_parameters(source_type, source_number)
        value = self.set_value_to_scale(vertical_value, vertical_suffix) * 8
        if source_type in [SourceWaveformType.Ref]:
            self.send_command(f":{source}:YRANGe {value}")
            return float(self.send_command(f":{source}:YRANGe?"))
        self.send_command(f":{source}:RANGe {value}")
        return float(self.send_command(f":{source}:RANGe?"))

    def source_set_offset(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None,
                          offset_value=0.0, offset_suffix: str = 'V'):
        """
        This command sets the value that is represented at center screen for the selected channel.
        The range of legal values varies with the value set by the channel vertical axis commands.
        If you set the offset to a value outside of the legal range, the offset value is automatically set to  the nearest legal value.
        Legal values are affected by the probe attenuation setting.
        """
        source = _validate_source_parameters(source_type, source_number)
        value = self.set_value_to_scale(offset_value, offset_suffix)
        if source_type in [SourceWaveformType.Ref]:
            self.send_command(f":{source}:YOFFset {value}")
            return float(self.send_command(f":{source}:YOFFset?"))
        self.send_command(f":{source}:OFFSet {value}")
        return float(self.send_command(f":{source}:OFFSet?"))

    # -------------------------------------------------------------------------------
    #                                 Channel Command
    # -------------------------------------------------------------------------------
    def ch_set_coupling(self, channel_number: int = 1, coupling: str = 'DC'):
        """
        This command selects the input coupling for the specified channel.
        The coupling for each analog channel can be set to AC or DC
        """
        if coupling not in ['AC', 'DC']:
            raise Exception("coupling only match in ['AC', 'DC']")
        self.send_command(f':CHANnel{channel_number}:COUPling {coupling}')

    def ch_set_bw(self, channel: int = 1, status: Union[str, int] = 'ON'):
        """
        This command controls an internal low-pass filter.
        When the filter is on, the bandwidth of the specified channel is limited to approximately 25 MHz.
        """
        if status not in self.SOURCE_STATUS:
            raise Exception(f"state only match in {self.SOURCE_STATUS}")
        self.send_command(f":CHANnel{channel}:BWLimit {status}")
        return self.send_command(f":CHANnel{channel}:BWLimit?")

    # -------------------------------------------------------------------------------
    #                                 Measure Command
    # -------------------------------------------------------------------------------
    def meas_set_status(self, status: Union[str, int] = 'ON') -> int:
        """
        This command enables markers for tracking measurements on the display.
        """
        if status not in self.SOURCE_STATUS:
            raise Exception(f"state only match in {self.SOURCE_STATUS}")
        self.send_command(f"MEASure:SHOW {status}")
        return self.send_command(f"MEASure:SHOW?")

    def meas_clear_all(self) -> None:
        """
        This command clears all selected measurements and markers from the screen.
        """
        self.send_command(f":MEASure:CLEar")

    def meas_show_measure(self, measure_type: str = 'ALL', source1: str = "CHANnel1", source2: str = "CHANnel2", **kwargs):
        """
        This command installs a screen measurement and starts the specified measurement.
        If the optional source parameter is specified, the current source is modified.
        If the measure_type is ALL, installs a Snapshot All measurement on the screen.
        """
        if measure_type not in Measure_Dict.keys():
            raise Exception(f"measure_type only match in {Measure_Dict.keys()}")
        self.send_command(f":MEASure:SHOW ON")
        self.send_command(str(Measure_Dict[measure_type]).format(read="", source1=source1, source2=source2, edge_select_mode="AUTO", x=1, **kwargs))
        self.send_command(f":MARKer:MODE MANual; :MARKer:MODE OFF")

    def meas_set_thresholds(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None,
                            thresholds_mode: str = 'PERCent', upper_middle_lower: list = ('90%', '50%', '10%')) -> str:
        """
        This command sets up the definition for measurements by specifying the threshold values.
        Changing these values may affect the results of other measure commands.
        • STANdard: upper_middle_lower like []
        • PERCent: upper_middle_lower like ['90%', '50%', '10%']
        • ABSolute: upper_middle_lower like []
        """
        if thresholds_mode not in ['STANdard', 'PERCent', 'ABSolute']:
            raise Exception("source only match in ['STANdard', 'PERCent', 'ABSolute']")
        source = _validate_source_parameters(source_type, source_number)
        upper_middle_lower = ",".join([item.strip('%') for item in upper_middle_lower])
        command = f':MEASure:DEFine THResholds,{thresholds_mode},{upper_middle_lower},{source}'
        err = self.send_command(command, check_errors=True)
        if err:
            raise Exception(err)
        return self.send_command(f':MEASure:DEFine? THResholds')

    def meas_get_measure(self, measure_type='FREQ', base_unit='', source1: str = "CHANnel1", source2: str = "CHANnel2"):
        """
        This command query returns the value of the specified measurement.
        """
        if measure_type not in Measure_Dict.keys():
            raise Exception(f"measure_type only match in {Measure_Dict.keys()}")
        result = self.send_command(Measure_Dict[measure_type].format(read="?", source1=source1, source2=source2))
        value = self.change_value_to_scale(result, base_unit)
        return float(value)

    # -------------------------------------------------------------------------------
    #                                 cursor Command
    # -------------------------------------------------------------------------------
    def cursor_set_mode(self, mode: str = 'MANual'):
        """
        This command sets the cursors mode:
        • OFF — removes the cursor information from the display.
        • MANual — enables manual placement of the X and Y cursors.If the front-panel cursors are off, or are set to the front-panel Hex or Binary mode, setting :MARKer:MODE MANual will put the cursors in the front-panel Normal mode.
        • MEASurement — cursors track the most recent measurement.Setting the mode to MEASurement sets the marker sources (:MARKer:X1Y1source and :MARKer:X2Y2source) to the measurement source (:MEASure:SOURce). Setting the measurement source remotely always sets the marker sources.
        • WAVeform — the Y1 cursor tracks the voltage value at the X1 cursor of the waveform specified by the X1Y1source, and the Y2 cursor does the same for the X2 cursor and its X2Y2source.
        • BINary — logic levels of displayed waveforms at the current X1 and X2 cursor positions are displayed in the Cursor sidebar dialog in binary.
        • HEX — logic levels of displayed waveforms at the current X1 and X2 cursor positions are displayed in the Cursor sidebar dialog in hexadecimal.
        """
        if mode not in CursorMode:
            raise Exception(f"measure_type only match in {CursorMode}")
        self.send_command(f":MARKer:MODE {mode}")

    def cursor_get_x_delta(self, base_unit=''):
        """
        This command query returns the value difference between the current X1 and X2 cursor positions.
        Xdelta = (Value at X2 cursor) - (Value at X1 cursor)
        """
        x_delta = self.send_command(':MARKer:XDELta?')
        value = self.change_value_to_scale(x_delta, base_unit)
        return float(value)

    def cursor_get_x1_position(self, base_unit=''):
        """
        This command query returns the current X1 cursor position.
        """
        x_delta = self.send_command(':MARKer:X1Position?')
        value = self.change_value_to_scale(x_delta, unit=base_unit)
        return float(value)

    def cursor_get_x2_position(self, base_unit=''):
        """
        This command query returns the current X2 cursor position.
        """
        x_delta = self.send_command(':MARKer:X2Position?')
        value = self.change_value_to_scale(x_delta, unit=base_unit)
        return float(value)

    def cursor_get_y_delta(self, base_unit=''):
        """
        This command query returns the value difference between the current Y1 and Y2 cursor positions.
        Ydelta = (Value at Y2 cursor) - (Value at Y1 cursor)
        """
        y_delta = self.send_command(':MARKer:YDELta?')
        value = self.change_value_to_scale(y_delta, unit=base_unit)
        return float(value)

    def cursor_get_y1_position(self, base_unit=''):
        """
        This command query returns the current Y1 cursor position.
        """
        y_delta = self.send_command(':MARKer:Y1Position?')
        value = self.change_value_to_scale(y_delta, unit=base_unit)
        return float(value)

    def cursor_get_y2_position(self, base_unit=''):
        """
        This command query returns the current Y2 cursor position.
        """
        y_delta = self.send_command(':MARKer:Y2Position?')
        value = self.change_value_to_scale(y_delta, unit=base_unit)
        return float(value)

    def cursor_set_channels(self, source1_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source1_number: int = None,
                            source2_type: Union[SourceWaveformType, str] = None, source2_number: int = None):
        """
        This command sets the source for the cursors.
        The channels you specify must be enabled for cursors to be displayed. If the channel or function is not on, an error message is issued.
        
        • will put the cursors in the MANual mode.
        • Setting the channel for one pair of markers (for X1Y1); Setting the channel2 for the other (for X2Y2).
        
        If the channel2 is None, just setting the channel for X1Y1 markers
        """
        source1 = _validate_source_parameters(source1_type, source1_number)
        self.send_command(f':MARKer:X1Y1source {source1}')
        if source2_type:
            source2 = _validate_source_parameters(source2_type, source2_number)
            self.send_command(f':MARKer:X2Y2source {source2}')

    def cursor_get_reciprocal_delta_x(self, base_unit=''):
        """
        This command query returns the value reciprocal of difference between the current X1 and X2 cursor positions.
        Hz = 1/( (Value at X2 cursor) - (Value at X1 cursor) )
        """
        try:
            self.send_command(":MARKer:XUNits HERTz")
            time.sleep(1)
            x_delta = self.send_command(':MARKer:XDELta?')
            value = self.change_value_to_scale(x_delta, unit=base_unit)
            return float(value)
        finally:
            self.send_command(":MARKer:XUNits SEConds")

    def cursor_get_delta_y_vs_delta_x(self, base_unit=''):
        """
        This command query returns the cursor ∆Y/∆X value.
        """
        x_delta = self.send_command(':MARKer:DYDX?')
        value = self.change_value_to_scale(x_delta, unit=base_unit)
        return float(value)

    # -------------------------------------------------------------------------------
    #                                 Function Command
    # -------------------------------------------------------------------------------
    def func_math_set_type(self, math_num: int = 1, math_type: FunctionTYPE = FunctionTYPE.Add):
        """
        This command sets the desired waveform math operator, transform, filter or visualization:
             1) Operators:
                    • ADD — Source1 + source2.
                    • SUBTract — Source1 - source2.
                    • MULTiply — Source1 * source2.
                    • DIVide — Source1 / source2.
                Operators perform their function on two analog channel sources.
             2) Transforms:
                    • DIFF — Differentiate
                    • INTegrate — The INTegrate:IOFFset command lets you specify a DC offset correction factor.
                    • FFT (magnitude) — Using the Fast Fourier Transform (FFT).
                            this operation displays the magnitudes of the frequency content that makes up the source waveform. The FFT takes the digitized time record of the specified source and transforms it to the frequency domain.
                            The SPAN, CENTer, VTYPe, and WINDow commands are used for FFT functions. When FFT is selected, the horizontal cursors change from time to frequency (Hz), and the vertical cursors change from volts to decibels or V RMS.
                    • FFTPhase — Using the Fast Fourier Transform (FFT).
                            this operation shows the phase relationships of the frequency content that makes up the source waveform. The FFT takes the digitized time record of the specified source and transforms it to the frequency domain.
                            The SPAN, CENTer, VTYPe, and WINDow commands are used for FFT functions. When FFTPhase is selected, the horizontal cursors change from time to frequency (Hz), and the vertical cursors change from volts to degrees or radians.
                    • LINear — Ax + B — The LINear commands set the gain (A) and offset (B) values for this function.
                    • SQUare
                    • SQRT — Square root
                    • ABSolute — Absolute Value
                    • LOG — Common Logarithm
                    • LN — Natural Logarithm
                    • EXP — Exponential (ex)
                    • TEN — Base 10 exponential (10x)
                Transforms operate on a single analog channel source or on lower math functions.
            3) Filters:
                    • LOWPass — Low pass filter — The FREQuency:LOWPass command sets the -3 dB cutoff frequency.
                    • HIGHpass — High pass filter — The FREQuency:HIGHpass command sets the -3 dB cutoff frequency.
                    • AVERage — Averaged value — The AVERage:COUNt command specifies the number of averages.
                            Unlike acquisition averaging, the math averaging operator can be used to average the data on a single analog input channel or math function.
                            If acquisition averaging is also used, the analog input channel data is averaged and the math function averages it again. You can use both types of averaging to get a certain number of averages on all waveforms and an increased number of averages on a particular waveform.
                            Averages are calculated using a "decaying average" approximation, where: next_average = current_average + (new_data - current_average)/N
                            Where N starts at 1 for the first acquisition and increments for each following acquisition until it reaches the selected number of averages, where it holds.
                    • SMOoth — Smoothing — The resulting math waveform is the selected source with a normalized rectangular (boxcar) FIR filter applied.
                            The boxcar filter is a moving average of adjacent waveform points, where the number of adjacent points is specified by the SMOoth:POINts command. You can choose an odd number of points, from 3 to 999.
                            The smoothing operator limits the bandwidth of the source waveform. The smoothing operator can be used, for example, to smooth measurement trend waveforms.
                    • ENVelope — Envelope — The resulting math waveform is the amplitude envelope for an amplitude modulated (AM) input signal.
                            This function uses a Hilbert transform to get the real (in-phase, I) and imaginary (quadrature, Q) parts of the input signal and then performs a square root of the sum of the real and imaginary parts to get the demodulated amplitude envelope waveform.
                Filters operate on a single analog channel source or on a lower math function.
            4) Visualizations:
                    • MAGNify — Operates on a single analog channel source or on a lower math function.
                    • MAXimum — This operator is like the MAXHold operator without the hold. The maximum vertical values found at each horizontal bucket are used to build a waveform.
                    • MINimum — This operator is like the MINHold operator without the hold. The minimum vertical values found at each horizontal bucket are used to build a waveform.
                    • PEAK — The PEAK operator is like the MAXimum operator minus the MINimum operator. At each horizontal bucket, the minimum vertical values found are subtracted from the maximum vertical values found to build a waveform.
                    • MAXHold — Operates on a single analog channel source or on a lower math function. The Max Hold (or Max Envelope) operator records the maximum vertical values found at each horizontal bucket across multiple analysis cycles and uses those values to build a waveform.
                    • MINHold — Operates on a single analog channel source or on a lower math function. The Min Hold (or Min Envelope) operator records the minimum vertical values found at each horizontal bucket across multiple analysis cycles and uses those values to build a waveform.
                    • TRENd — Measurement trend — Operates on a single analog channel source. The TRENd:NMEasurement command selects the measurement whose trend you want to measure.
                    • BTIMing — Chart logic bus timing — Operates on a bus made up of digital channels. The BUS:YINcrement, BUS:YORigin, and BUS:YUNits commands specify function values.
                    • BSTate — Chart logic bus state — Operates on a bus made up of digital channels. The BUS:YINcrement, BUS:YORigin, and BUS:YUNit commands specify function values. The BUS:CLOCk and BUS:SLOPe commands specify the clock source and edge.
        """
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        self.send_command(f':FUNCtion{math_num}:OPERation {math_type}')

    def func_math_set_ch_sources(self, math_num: int = 1,
                                 source1_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source1_number: int = None,
                                 source2_type: Union[SourceWaveformType, str] = None, source2_number: int = None):
        """
        This command
                • selects the source1 for the operator math functions or the single source for the transform functions, filter functions, or visualization functions,
                • specifies the source2 for math operator functions that have two sources.
        """
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        source1 = _validate_source_parameters(source1_type, source1_number)
        self.send_command(f':FUNCtion{math_num}:SOURce1 {source1}')
        if source2_type:
            source2 = _validate_source_parameters(source2_type, source2_number)
            self.send_command(f':FUNCtion{math_num}:SOURce2 {source2}')

    def func_math_set_type_and_sources(self, math_num: int = 1, math_type: FunctionTYPE = FunctionTYPE.Add,
                                       source1_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source1_number: int = None,
                                       source2_type: Union[SourceWaveformType, str] = None, source2_number: int = None):
        """
        This command sets the desired waveform math operator, transform, filter or visualization:
             1) Operators:
                    • ADD — Source1 + source2.
                    • SUBTract — Source1 - source2.
                    • MULTiply — Source1 * source2.
                    • DIVide — Source1 / source2.
                Operators perform their function on two analog channel sources.
             2) Transforms:
                    • DIFF — Differentiate
                    • INTegrate — The INTegrate:IOFFset command lets you specify a DC offset correction factor.
                    • FFT (magnitude) — Using the Fast Fourier Transform (FFT).
                            this operation displays the magnitudes of the frequency content that makes up the source waveform. The FFT takes the digitized time record of the specified source and transforms it to the frequency domain.
                            The SPAN, CENTer, VTYPe, and WINDow commands are used for FFT functions. When FFT is selected, the horizontal cursors change from time to frequency (Hz), and the vertical cursors change from volts to decibels or V RMS.
                    • FFTPhase — Using the Fast Fourier Transform (FFT).
                            this operation shows the phase relationships of the frequency content that makes up the source waveform. The FFT takes the digitized time record of the specified source and transforms it to the frequency domain.
                            The SPAN, CENTer, VTYPe, and WINDow commands are used for FFT functions. When FFTPhase is selected, the horizontal cursors change from time to frequency (Hz), and the vertical cursors change from volts to degrees or radians.
                    • LINear — Ax + B — The LINear commands set the gain (A) and offset (B) values for this function.
                    • SQUare
                    • SQRT — Square root
                    • ABSolute — Absolute Value
                    • LOG — Common Logarithm
                    • LN — Natural Logarithm
                    • EXP — Exponential (ex)
                    • TEN — Base 10 exponential (10x)
                Transforms operate on a single analog channel source or on lower math functions.
            3) Filters:
                    • LOWPass — Low pass filter — The FREQuency:LOWPass command sets the -3 dB cutoff frequency.
                    • HIGHpass — High pass filter — The FREQuency:HIGHpass command sets the -3 dB cutoff frequency.
                    • AVERage — Averaged value — The AVERage:COUNt command specifies the number of averages.
                            Unlike acquisition averaging, the math averaging operator can be used to average the data on a single analog input channel or math function.
                            If acquisition averaging is also used, the analog input channel data is averaged and the math function averages it again. You can use both types of averaging to get a certain number of averages on all waveforms and an increased number of averages on a particular waveform.
                            Averages are calculated using a "decaying average" approximation, where: next_average = current_average + (new_data - current_average)/N
                            Where N starts at 1 for the first acquisition and increments for each following acquisition until it reaches the selected number of averages, where it holds.
                    • SMOoth — Smoothing — The resulting math waveform is the selected source with a normalized rectangular (boxcar) FIR filter applied.
                            The boxcar filter is a moving average of adjacent waveform points, where the number of adjacent points is specified by the SMOoth:POINts command. You can choose an odd number of points, from 3 to 999.
                            The smoothing operator limits the bandwidth of the source waveform. The smoothing operator can be used, for example, to smooth measurement trend waveforms.
                    • ENVelope — Envelope — The resulting math waveform is the amplitude envelope for an amplitude modulated (AM) input signal.
                            This function uses a Hilbert transform to get the real (in-phase, I) and imaginary (quadrature, Q) parts of the input signal and then performs a square root of the sum of the real and imaginary parts to get the demodulated amplitude envelope waveform.
                Filters operate on a single analog channel source or on a lower math function.
            4) Visualizations:
                    • MAGNify — Operates on a single analog channel source or on a lower math function.
                    • MAXimum — This operator is like the MAXHold operator without the hold. The maximum vertical values found at each horizontal bucket are used to build a waveform.
                    • MINimum — This operator is like the MINHold operator without the hold. The minimum vertical values found at each horizontal bucket are used to build a waveform.
                    • PEAK — The PEAK operator is like the MAXimum operator minus the MINimum operator. At each horizontal bucket, the minimum vertical values found are subtracted from the maximum vertical values found to build a waveform.
                    • MAXHold — Operates on a single analog channel source or on a lower math function. The Max Hold (or Max Envelope) operator records the maximum vertical values found at each horizontal bucket across multiple analysis cycles and uses those values to build a waveform.
                    • MINHold — Operates on a single analog channel source or on a lower math function. The Min Hold (or Min Envelope) operator records the minimum vertical values found at each horizontal bucket across multiple analysis cycles and uses those values to build a waveform.
                    • TRENd — Measurement trend — Operates on a single analog channel source. The TRENd:NMEasurement command selects the measurement whose trend you want to measure.
                    • BTIMing — Chart logic bus timing — Operates on a bus made up of digital channels. The BUS:YINcrement, BUS:YORigin, and BUS:YUNits commands specify function values.
                    • BSTate — Chart logic bus state — Operates on a bus made up of digital channels. The BUS:YINcrement, BUS:YORigin, and BUS:YUNit commands specify function values. The BUS:CLOCk and BUS:SLOPe commands specify the clock source and edge.
        """
        self.func_math_set_type(math_num, math_type)
        self.func_math_set_ch_sources(math_num, source1_type=source1_type, source1_number=source1_number, source2_type=source2_type, source2_number=source2_number)

    def func_math_set_integrate_option(self, math_num: int = 1, offset_value: float = 0.0, offset_suffix: str = ''):
        """
        This command lets you enter a DC offset correction factor for the integrate math waveform input signal. This DC offset correction lets you level a "ramp"ed waveform.
        """
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        value = self.set_value_to_scale(offset_value, unit=offset_suffix)
        self.send_command(f':FUNCtion{math_num}:INTegrate:IOFFset {value}')

    def func_math_set_fft_options(self, math_num: int = 1, window: str = 'RECTangular',
                                  phase_reference: str = None, units: str = None,
                                  span: float = None, center: float = None, start: float = None, stop: float = None, freq: float = None):
        """
        This command allows the selection of different windowing transforms or operations for the FFT (Fast Fourier Transform) function.
        The FFT operation assumes that the time record repeats. Unless an integral number of sampled waveform cycles exist in the record, a discontinuity is created between the end of one record and the beginning of the next. This discontinuity introduces additional frequency components about the peaks into the spectrum. This is referred to as leakage. To minimize leakage, windows that approach zero smoothly at the start and end of the record are employed as filters to the FFTs. Each window is useful for certain classes of input signals.
            • RECTangular — useful for transient signals, and signals where there are an integral number of cycles in the time record.
            • HANNing — useful for frequency resolution and general purpose use. It is good for resolving two frequencies that are close together, or for making frequency measurements. This is the default window.
            • FLATtop — best for making accurate amplitude measurements of frequency peaks.
            • BHARris (Blackman-Harris) — reduces time resolution compared to the rectangular window, but it improves the capacity to detect smaller impulses due to lower secondary lobes (provides minimal spectral leakage).
            • BARTlett — (triangular, with end points at zero) window is similar to the Hanning window in that it is good for making accurate frequency measurements, but its higher and wider secondary lobes make it not quite as good for resolving frequencies that are close together.
        options is the dict data like: 
            • {'span': 16e6 , 'center': 8e6 }
            • {'start': 0 , 'stop': 16e6 }
        phase_reference sets the reference point for calculating the FFT Phase function to either the trigger point or beginning of the displayed waveform.
        For the FFT (Magnitude) operation units, DECibel equates to the user interface's Logarithmic selection, and VRMS equates to the user interface's Linear selection.
        units = { DEC | VRMS } for the FFT (magnitude) operation
        units = { DEGR | RAD } for the FFTPhase operation
        """
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        if window not in ['DMAGnitude', 'RECTangular', 'HANNing', 'FLATtop', 'BHARris', 'BARTlett']:
            raise Exception("window only match in ['DMAGnitude', 'RECTangular', 'HANNing', 'FLATtop', 'BHARris', 'BARTlett']")
        if phase_reference and phase_reference not in ['TRIGger', 'DISPlay']:
            raise Exception("phase_reference only match in ['TRIGger', 'DISPlay']")
        if units and units not in ['DECibel', 'VRMS', 'DEGRees', 'RADians']:
            raise Exception("units only match in ['DECibel', 'VRMS', 'DEGRees', 'RADians']")
        self.send_command(f':FUNCtion{math_num}:FFT:WINDow {window}')
        if span:
            self.send_command(f':FUNCtion{math_num}:FFT:SPAN {span}')
        if freq:
            self.send_command(f':FUNCtion{math_num}:FFT:CENTer {freq}')
        if start:
            self.send_command(f':FUNCtion{math_num}:FFT:FREQuency:STARt {start}')
        if stop:
            self.send_command(f':FUNCtion{math_num}:FFT:FREQuency:STOP {stop}')
        if phase_reference:
            self.send_command(f':FUNCtion{math_num}:FFT:PHASe:REFerence {phase_reference}')
        if units:
            self.send_command(f':FUNCtion{math_num}:FFT:VTYPe {units}')

    def func_ref_save_ch(self, ref_num: int = 1, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None):
        """
        This command copies the analog channel or math function waveform to the specified reference waveform location.
        """
        if ref_num <= 0:
            raise Exception("ref_num must > 0")
        source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':WMEMory{ref_num}:SAVE {source}')

    def func_ref_set_skew(self, ref_num: int = 1, skew_value: float = 0.0, skew_suffix: str = 's'):
        """
        This command sets the skew factor for the specified reference waveform.
        """
        if ref_num <= 0:
            raise Exception(f"ref_num must > 0")
        value = self.set_value_to_scale(skew_value, unit=skew_suffix)
        self.send_command(f':WMEMory{ref_num}:SKEW {value}')

    # -------------------------------------------------------------------------------
    #                                 display Command
    # -------------------------------------------------------------------------------
    def display_set_persistence(self, mode: Union[str, float] = 'MINimum'):
        """
        This command specifies the persistence setting:
            • MINimum — indicates zero persistence.
            • INFinite — indicates infinite persistence.
            • <time> — for variable persistence, that is, you can specify how long acquisitions remain on the screen.
        Use the display_clear_waveforms command to erase points stored by persistence.

        mode: Union['MINimum', 'INFinite', float] = 'MINimum'
        """
        if mode not in ['MINimum', 'INFinite']:
            try:
                mode = float(mode)
            except ValueError:
                raise Exception("skew_suffix only match in ['MINimum', 'INFinite'] or float")
        self.send_command(f':DISPlay:PERSistence {mode}')

    def display_clear_waveforms(self):
        """
        This command clears the display and resets all associated measurements.
        If the oscilloscope is stopped, all currently displayed data is erased.
        If the oscilloscope is running, all the data for active channels and functions is erased; however, new data is displayed on the next acquisition.
        """
        self.send_command(':DISPlay:CLEar')

    def display_set_menu_show(self, menu: str = 'OFF'):
        """
        This command changes the front panel softkey menu or turns it off.
        When off, channel setup information is displayed instead.

        menu: ['MASK', 'MEASure', 'SEGMented', 'LISTer', 'POWer', 'OFF'] = 'OFF'
        """
        if menu not in ['MASK', 'MEASure', 'SEGMented', 'LISTer', 'POWer', 'OFF']:
            raise Exception(f"menu only match in ['MASK', 'MEASure', 'SEGMented', 'LISTer', 'POWer', 'OFF']")
        self.send_command(f':DISPlay:MENU {menu}')

    def display_set_acquire(self, mode: str = 'AUTO', sample_rate: Union[Literal['Auto'], int] = 'AUTO',
                            memory_depth: Union[Literal['Auto'], int] = 'AUTO'):
        """
        This command turns Digitizer mode on or off.
        Normally, when Digitizer mode is disabled (Automatic mode), the oscilloscope's time per division setting determines the sample rate and memory depth so as to fill the waveform display with data while the oscilloscope is running (continuously making acquisitions). For single acquisitions, the time/division setting still determines the sample rate, but the maximum amount of acquisition memory is used.
        In Digitizer mode, you choose the acquisition sample rate and memory depth, and those settings are used even though the captured data may extend way beyond the edges of, or take up just a small portion of, the waveform display, depending on the oscilloscope's time/div setting.
        Digitizer mode cannot be used along with these other oscilloscope features: XY and Roll time modes, horizontal Zoom display, time references other than Center, segmented memory, uartSerial decode, digital channels, frequency response analysis, mask test, and the power application. In most cases, enabling one of these features when Digitizer mode is enabled will automatically disable Digitizer mode, and then disabling the feature will automatically reenable Digitizer mode.
        Digitizer mode primarily aids external software that controls and combines data from multiple instruments.

        mode: ['DISable', 'AUTO'] = 'AUTO'\n
        sample_rate: ['Auto', int] = 'AUTO'\n
        memory_depth: ['Auto', int] = 'AUTO'\n
        """
        if mode not in ['DISable', 'AUTO']:
            raise Exception(f"mode only match in ['DISable', 'AUTO']")
        if mode == 'AUTO':
            self.send_command(':ACQuire:DIGitizer OFF')
            return
        self.send_command(f':ACQuire:POINts {memory_depth}')
        self.send_command(f':ACQuire:SRATe {sample_rate}')
        self.send_command(':ACQuire:DIGitizer ON')


class InfiniiumCatAOsc(OscAgnet):
    def __init__(self, instrument_address, timeout: float = 5000, logger=None):
        super().__init__(instrument_address=instrument_address, timeout=timeout, logger=logger)

        self.Image_Format = ['BMP', 'JPG', 'GIF', 'TIF', 'PNG']

    # -------------------------------------------------------------------------------
    #                                 File Command
    # -------------------------------------------------------------------------------
    def get_screen_image(self, image_format: str = 'PNG', color: bool = True, timeout: int = 30000) -> bytes:
        """
        Reads the screen image data from an InfiniiVision oscilloscope

        Args:
            image_format: 图片格式 in ['BMP', 'JPG', 'GIF', 'TIF', 'PNG']
            color: 是否彩色
            timeout: 超时时间(ms)
        """
        if image_format not in self.Image_Format:
            raise Exception(f"image_format only match in {self.Image_Format}")
        original_timeout = self._virtual_device.timeout
        self._virtual_device.timeout = timeout

        try:
            self.logger.info(f"截取屏幕 ({image_format} 格式, 超时: {timeout}ms)")
            color_param = "SCReen" if color else "GRATicule"
            self._virtual_device.write(f":DISPLAY:DATA? {image_format},{color_param}")

            raw_data = self._virtual_device.read_raw()

            if raw_data.startswith(b"#"):
                header_len = int(raw_data[1:2])
                data_start = 2 + header_len
                img_data = raw_data[data_start:-1]
                self.logger.debug(f"截图完成: {len(img_data)} 字节")
                return img_data

            self.logger.debug(f"截图完成 (无头部): {len(raw_data)} 字节")
            return raw_data

        except pyvisa.VisaIOError as e:
            if "timeout" in str(e).lower():
                self.logger.error(f"截图超时: {e}")
                raise Exception(f"截图超时 (>{timeout}ms)")
            self.logger.error(f"截图数据获取失败: {e}")
            raise Exception(f"截图数据获取失败: {e}")
        finally:
            self._virtual_device.timeout = original_timeout

    # -------------------------------------------------------------------------------
    #                                 Trigger Command
    # -------------------------------------------------------------------------------
    def trigger_set_edge_option(self, source_type: Union[SourceTriggerType, str], source_number: int = None, slope: Union[TriggerSlopeType, str] = TriggerSlopeType.Rising, level: str = '1V'):
        """
        This command set the edge trigger options.
        """
        if isinstance(source_type, SourceTriggerType):
            source = source_type.value
        else:
            source = source_type
        if source not in ["EXTernal", "LINE", "WMOD"]:
            source = _validate_source_parameters(source, source_number)
        if isinstance(slope, TriggerSlopeType):
            slope_type = slope.value
        else:
            slope_type = slope
        self.send_command(':TRIGger:SWEep TRIGgered;:TRIGger:MODE EDGE')
        self.send_command(f':TRIGger:LEVel {source},{level}')
        self.send_command(f':TRIGger:EDGE:SOURce {source}')
        self.send_command(f':TRIGger:EDGE:SLOPe  {slope_type}')

    # -------------------------------------------------------------------------------
    #                                 Channel Command
    # -------------------------------------------------------------------------------
    def ch_set_coupling(self, channel: int = 1, coupling: str = 'DC'):
        if coupling not in ['AC', 'DC']:
            raise Exception("coupling only match in ['AC', 'DC']")
        self.send_command(f':CHANnel{channel}:INPut {coupling}')

    # -------------------------------------------------------------------------------
    #                                 Real eyes Command
    # -------------------------------------------------------------------------------
    def real_eyes_set_channel_to_on(self, source_type: Union[SourceWaveformType, str] = None, source_number: int = None, fast_mode: str = 'OFF'):
        if fast_mode not in self.SOURCE_STATUS:
            raise Exception(f"state only match in {self.SOURCE_STATUS}")
        source = ""
        if source_type:
            source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':MTESt:FOLDing ON,{source}')
        self.send_command(f':MTESt:FOLDing:FAST {fast_mode},{source}')

    def real_eyes_set_horizon_ui_scale(self, source_type: Union[SourceWaveformType, str] = None, source_number: int = None, scale: float = 2.0, position: float = 0.0):
        """
        This command sets:
                • the real-time eye horizontal scale, that is, the number of unit intervals (UIs) shown on screen.
                • the real-time eye horizontal center position in time.
        """
        source = ""
        if source_number:
            source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':MTESt:FOLDing ON,{source}')
        self.send_command(f':MTESt:FOLDing:SCALe {"%.2f" % scale},{source}')
        self.send_command(f':MTESt:FOLDing:POSition {"%.2f" % position},{source}')

    def real_eyes_set_horizon_time_scale(self, source_type: Union[SourceWaveformType, str] = None, source_number: int = None, scale: float = 2.0, position: float = 0.0):
        """
        This command sets:
                • sets the real-time eye horizontal scale per division in time.
                • the real-time eye horizontal center position in time.
        """
        source = ""
        if source_number:
            source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':MTESt:FOLDing ON,{source}')
        self.send_command(f':MTESt:FOLDing:TSCale {scale},{source}')
        self.send_command(f':MTESt:FOLDing:TPOSition {position},{source}')

    def real_eyes_show_measurement(self, source_type: Union[SourceWaveformType, str] = None, source_number: int = None, measure_type: str = 'height'):
        """
        This command enables the measurement on the current eye pattern.
        Before using this command or query, you must be a full eye diagram on screen before a valid measurement can be made.
        """
        source = ""
        if source_number:
            source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':MTESt:FOLDing ON,{source}')
        # self.send_command(f"MEASure:SHOW ON")
        self.send_command(str(Real_Eyes_Measure_Dict.get(measure_type)).format(read="", source=source))

    def real_eyes_get_measurement(self, source_type: Union[SourceWaveformType, str] = None, source_number: int = None,
                                  measure_type: str = 'height', base_unit: str = ""):
        """
        This command query returns the value of the specified measurement on the current eye pattern.
        """
        source = ""
        if source_number:
            source = _validate_source_parameters(source_type, source_number)
        get_value = self.send_command(str(Real_Eyes_Measure_Dict.get(measure_type)).format(read="?", source=source))
        value = self.change_value_to_scale(get_value, unit=base_unit)
        return float(value)

    # -------------------------------------------------------------------------------
    #                                 Function Command
    # -------------------------------------------------------------------------------
    def func_math_set_type_and_sources(self, math_num: int = 1, math_type: FunctionTYPE = FunctionTYPE.Add,
                                       source1_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source1_number: int = None,
                                       source2_type: Union[SourceWaveformType, str] = None, source2_number: int = None):
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        source1 = _validate_source_parameters(source1_type, source1_number)
        source2 = _validate_source_parameters(source2_type, source2_number)
        self.send_command(f':FUNCtion{math_num}:{math_type} {source1}, {source2}')

    # -------------------------------------------------------------------------------
    #                                 cursor Command
    # -------------------------------------------------------------------------------
    def cursor_add_marker(self, marker_num: int = 5, marker_type: str = 'XMANual', source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None):
        """
        This command turns a particular marker on, then specifies a particular marker's type:
            • XMANual — manual X only horizontal marker that can be moved freely.
            • YMANual — manual Y only vertical marker that can be moved freely.
                    Vertical markers are not allowed if the marker source is a digital input channel.
            • TRACk — track waveform marker.
                    A track waveform marker is a horizontal marker that can be moved freely. The waveform's vertical value at that horizontal time point is also marked (but cannot be moved).
            • RF — track RF marker.
                    Track RF markers are allowed only on frequency domain (FFT) waveform sources. Track RF markers show the frequency and vertical value associated with the marker's horizontal position.
        """
        if marker_num <= 0:
            raise Exception(f"marker_num must > 0")
        if marker_type not in ['XMANual', 'YMANual', 'TRACk', 'RF']:
            raise Exception("marker_type only match in ['XMANual', 'YMANual', 'TRACk', 'RF']")
        source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':MEASure:MARK {marker_num},ON')
        self.send_command(f':MARKer{marker_num}:TYPE {marker_type}')
        self.send_command(f':MARKer{marker_num}:SOURce {source}')
        self.send_command(f':MARKer{marker_num}:ENABle ON')

    def cursor_get_marker_position(self, marker_num: int = 5, position: str = 'X', base_unit: str = ""):
        """
        This command specifies the position of a particular marker.
        Whether this command is valid depends on the type of marker (see cursor_add_marker). For example, you cannot set the X position of a manual Y only vertical marker.
        """
        if marker_num <= 0:
            raise Exception(f"marker_num must > 0")
        if position not in ['X', 'Y']:
            raise Exception("position only match in ['X', 'Y']")
        delta = self.send_command(f':MARKer{marker_num}:{position}:POSition?')
        value = self.change_value_to_scale(delta, unit=base_unit)
        return float(value)

    def cursor_get_markers_delta(self, marker1_num=5, marker2_num=6, unit_for_state_x_invx_y_invy=',,,'):
        """
        This command query returns a particular marker's "delta to" state and delta values
        <marker_delta_results> = <delta-to_state>,<delta_X>,<delta_X_inv>,<delta_Y>,<delta_Y_over_delta_X>
                • <delta-to_state> = {0 | 1}
                • <delta_X> = ΔX value in NR3 format
                • <delta_X_inv> = 1/ΔX value in NR3 format
                • <delta_Y> = ΔY value in NR3 format
                • <delta_Y_over_delta_X> = ΔY/ΔX value in NR3 format
        If the delta measurement does not apply or cannot be made, the infinity representation value (9.99999E+37) is returned.

        unit_for_state_x_invx_y_invy like ",,,,", "1,u,M,m,K", "1,,,m,K", "1,p,G,,"
        """
        if marker1_num <= 0 or marker2_num <= 0:
            raise Exception(f"marker_num must > 0")
        self.send_command(f':MARKer{marker1_num}:DELTa MARKer{marker2_num},ON')
        delta = self.send_command(f':MARKer{marker1_num}:DELTa? MARKer{marker2_num}').split(',')
        base_unit_list = unit_for_state_x_invx_y_invy.split(',')
        x = len(delta) - len(base_unit_list)
        if x > 0:
            base_unit_list.append(',' * x)
        data_list = []
        for i in range(len(delta)):
            if delta[i].isdigit():
                value = self.change_value_to_scale(delta[i], unit=base_unit_list[i])
                data_list.append(value)
            else:
                data_list.append(delta[i])
        return data_list

    # -------------------------------------------------------------------------------
    #                                 display Command
    # -------------------------------------------------------------------------------
    def display_set_acquire(self, mode: str = 'AUTO',
                            sample_rate: Union[Literal['Auto'], int] = 'AUTO',
                            memory_depth: Union[Literal['Auto'], int] = 'AUTO'):
        if mode not in ['DISable', 'AUTO']:
            raise Exception(f"mode only match in ['DISable', 'AUTO']")
        if mode == 'AUTO':
            self.send_command(':ACQuire:POINts:AUTO ON')
            self.send_command(':ACQuire:SRATe:AUTO ON')
            return
        self.send_command(f':ACQuire:POINts {memory_depth}')
        self.send_command(f':ACQuire:SRATe {sample_rate}')

    # -------------------------------------------------------------------------------
    #                                 Histogram Command
    # -------------------------------------------------------------------------------
    def histogram_set_status(self, status: str = 'OFF'):
        """
        This command selects the histogram mode.
        The histogram may be off, set to track the waveforms, or set to track the measurement when the Jitter Analysis Software license is installed.
        When the Jitter Analysis Software license is installed, sending the :MEASure:JITTer:HISTogram ON command will automatically set :HISTOgram:MODE to MEASurement.
        """
        if status not in ['OFF', 'MEASurement', 'WAVeforms']:
            raise Exception("mode only match in ['OFF', 'MEASurement', 'WAVeforms']")
        self.send_command(f':HISTogram:MODE {status}')

    def histogram_set_histogram_options(self, size: float = 1.0, orientation: str = 'VERTical', max_bins: int = 1024):
        """
        This command features:
                • Sets histogram size for vertical and horizontal mode.
                
                        The size is from 1.0 to 8.0 for the horizontal mode and from 1.0 to 10.0 for the vertical mode.
                        
                • Selects the type of histogram. 
                
                        A horizontal histogram can be used to measure time related information like jitter.

                        A vertical histogram can be used to measure voltage related information like noise.


                • Sets the maximum number of bins used for a vertical waveform histogram.
        """
        if orientation not in ['VERTical', 'HORizontal']:
            raise Exception("orientation only match in ['VERTical', 'HORizontal']")
        if orientation == "HORizontal":
            if size > 8.0:
                size = 8.0
        else:
            if size > 10.0:
                size = 10.0
        if size < 1.0:
            size = 1.0
        self.send_command(f':HISTogram:SCALe:SIZE {size}')
        self.send_command(f':HISTogram:AXIS {orientation}')
        self.send_command(f':HISTogram:VERTical:BINS {max_bins}')

    def histogram_set_window_options(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH, source_number: int = None, top_left_bottom_right=''):
        """
        This command features:
                • Selects the source of the histogram window. The histogram window will track the source's vertical and horizontal scale.

                • Moves the By marker (limits) of the histogram window.

                        The histogram window determines the portion of the display used to build the database used for the histogram.
                        The histogram window markers will track the scale of the histogram window source.
        top_left_bottom_right like "0.5, 80e-6 , 1 , 90e-6"

        """
        source = _validate_source_parameters(source_type, source_number)
        self.send_command(f':HISTogram:WINDow:SOURce {source}')
        top, left, bottom, right = top_left_bottom_right.split(',')
        self.send_command(f':HISTogram:WINDow:LLIMit {left}')
        self.send_command(f':HISTogram:WINDow:RLIMit {right}')
        self.send_command(f':HISTogram:WINDow:BLIMit {bottom}')
        self.send_command(f':HISTogram:WINDow:TLIMit {top}')

    def histogram_set_window_to_default(self):
        """
        This command positions the histogram markers to a default location on the display.
        Each marker will be positioned one division off the left, right, top, and bottom of the display.
        """
        self.send_command(':HISTogram:WINDow:DEFault')

    # -------------------------------------------------------------------------------
    #                                 Measure Command
    # -------------------------------------------------------------------------------
    def meas_set_window(self, meas_number: int = 1, window: str = 'MAIN'):
        """
        This command specifies whether measurements are made in the ZOOM window (measurement gating), the CGRade (color grade) view, or over the entire acquisition (MAIN or ALL). 
        The MAIN and ALL parameters are equivalent.
        Not all measurements can be applied to the color grade view.
        If MEAS<N> is omitted, the command attempts to apply the selected window to all active measurements.
        """
        if meas_number <= 0:
            raise Exception(f"meas_number must > 0")
        if window not in ['ZOOM', 'CGRade', 'MAIN', 'ALL']:
            raise Exception("window only match in ['ZOOM', 'CGRade', 'MAIN', 'ALL']")
        self.send_command(f"MEASure:WINDow {window},{meas_number}")

    # -------------------------------------------------------------------------------
    #                                 Horizontal Command
    # -------------------------------------------------------------------------------
    def horizon_set_mode(self, mode: str = 'MAIN'):
        if mode not in ['MAIN', 'WINDow']:
            raise Exception("mode only match in ['MAIN', 'WINDow']")
        self.send_command(f":TIMebase:VIEW {mode}")

    def func_math_set_fft_options(self, math_num: int = 1, mode: str = 'MAGNitude', channel: int = 1, window: str = 'RECTangular',
                                  phase_reference: str = None, units: str = None, level: float = None, count: int = None, time_delay: float = 0.0,
                                  span: float = None, center: float = None, start: float = None, stop: float = None, freq: float = None,
                                  horizontal_scale: str = "LINear",
                                  sort_type: str = 'OFF', detector_type: str = 'OFF', detector_points: int = None):
        """
        This command allows the selection of different windowing transforms or operations for the FFT (Fast Fourier Transform) function.
        The FFT operation assumes that the time record repeats. Unless an integral number of sampled waveform cycles exist in the record, a discontinuity is created between the end of one record and the beginning of the next. This discontinuity introduces additional frequency components about the peaks into the spectrum. This is referred to as leakage. To minimize leakage, windows that approach zero smoothly at the start and end of the record are employed as filters to the FFTs. Each window is useful for certain classes of input signals.
            • RECTangular — useful for transient signals, and signals where there are an integral number of cycles in the time record.
            • HANNing — useful for frequency resolution and general purpose use. It is good for resolving two frequencies that are close together, or for making frequency measurements. This is the default window.
            • FLATtop — best for making accurate amplitude measurements of frequency peaks.
            • BHARris (Blackman-Harris) — reduces time resolution compared to the rectangular window, but it improves the capacity to detect smaller impulses due to lower secondary lobes (provides minimal spectral leakage).
            • BARTlett — (triangular, with end points at zero) window is similar to the Hanning window in that it is good for making accurate frequency measurements, but its higher and wider secondary lobes make it not quite as good for resolving frequencies that are close together.

        phase_reference sets the reference point for calculating the FFT Phase function to either the trigger point or beginning of the displayed waveform.
        For the FFT (Magnitude) operation units, DECibel equates to the user interface's Logarithmic selection, and VRMS equates to the user interface's Linear selection.
        units = { DEC | VRMS } for the FFT (magnitude) operation
        units = { DEGR | RAD } for the FFTPhase operation

        When enabled, the first N peaks in the FFT above the specified Peak Level are annotated.
        The annotated peak values are displayed in the graphical user interface's FFT Peaks results window at the bottom of the display.
        This command specifies whether peaks are annotated by Decreasing Magnitude (DMAGnitude), Increasing Frequency (IFRequency), Decreasing Frequency (DFRequency), or Increasing Magnitude (IMAGnitude) order.
        Peak annotations are numbered according to the chosen sort.

        Detectors decimate the number of points on screen to at most the number of detector points (buckets).
        Detectors give you a way of manipulating the acquired data to emphasize different features of the data. The detector types are:
                • OFF — No detector is used.
                • SAMPle — Takes the point nearest to the center of every bucket.
                • PPOSitive — Takes the most positive point in every bucket.
                • PNEGative — Takes the most negative point in every bucket.
                • NORMal — Implements a rosenfell algorithm. For details, see the   Spectrum Analysis Basics application note.
                • AVERage — Takes the average of all points in every bucket.
        """
        if math_num <= 0:
            raise Exception(f"math_num must > 0")
        if mode not in ['MAGNitude', 'Phase']:
            raise Exception("mode only match in ['MAGNitude', 'Phase']")
        if horizontal_scale not in ['LINear', 'LOG ']:
            raise Exception("horizontal_scale only match in ['LINear', 'LOG ']")
        if window not in ['RECTangular', 'HANNing ', 'FLATtop', 'BHARris', 'HAMMing']:
            raise Exception("window only match in ['RECTangular', 'HANNing ', 'FLATtop', 'BHARris', 'HAMMing']")
        if phase_reference and phase_reference not in ['TRIGger', 'DISPlay']:
            raise Exception("phase_reference only match in ['TRIGger', 'DISPlay']")
        if units and units not in ['DB', 'DBMV ', 'DBUV', 'WATT', 'VRMS']:
            raise Exception("units only match in ['DB', 'DBMV ', 'DBUV', 'WATT', 'VRMS']")
        if sort_type not in ['DMAGnitude', 'DFRequency', 'IMAGnitude', 'IFRequency', 'OFF']:
            raise Exception("sort_type only match in ['DMAGnitude', 'DFRequency', 'IMAGnitude', 'IFRequency', 'OFF']")
        if detector_type not in ['OFF', 'SAMPle ', 'PPOSitive', 'PNEGative', 'NORMal', 'AVERage']:
            raise Exception("detector_type only match in ['OFF', 'SAMPle ', 'PPOSitive', 'PNEGative', 'NORMal', 'AVERage']")

        self.send_command(f':FUNCtion{math_num}:DISPlay ON')
        self.send_command(f':FUNCtion{math_num}:FFT{mode} CHANnel{channel}')
        self.send_command(f':FUNCtion{math_num}:FFT:WINDow {window}')
        self.send_command(f':FUNCtion{math_num}:FFT:HSCale {horizontal_scale}')
        if level:
            self.send_command(f':FUNCtion{math_num}:FFT:PEAK:LEVel {level}')
        if count:
            self.send_command(f':FUNCtion{math_num}:FFT:PEAK:COUNt {count}')
        if span:
            self.send_command(f':FUNCtion{math_num}:FFT:SPAN {span}')
        if center:
            self.send_command(f':FUNCtion{math_num}:FFT:CENTer {center}')
        if start:
            self.send_command(f':FUNCtion{math_num}:FFT:FREQuency:STARt {start}')
        if stop:
            self.send_command(f':FUNCtion{math_num}:FFT:FREQuency:STOP {stop}')
        if phase_reference:
            self.send_command(f':FUNCtion{math_num}:FFT:REFerence {phase_reference}')
            self.send_command(f':FUNCtion{math_num}:FFT:TDELay {time_delay}')
        if units:
            self.send_command(f':FUNCtion{math_num}:FFT:VUNits {units}')
        self.send_command(f':FUNCtion{math_num}:FFT:DETector:TYPE {detector_type}')
        if detector_type != 'OFF':
            self.send_command(f':FUNCtion{math_num}:FFT:DETector:POINts {detector_points}')
        if sort_type == 'OFF':
            self.send_command(f':FUNCtion{math_num}:FFT:PEAK:STATe OFF')
        else:
            self.send_command(f':FUNCtion{math_num}:FFT:PEAK:STATe ON')
            self.send_command(f':FUNCtion{math_num}:FFT:PEAK:SORT {sort_type}')



class TektronixOsc(InfiniiumCatAOsc):
    """
    Tektronix 4/5/6 系列 MSO 示波器控制类

    基于 Tektronix 4/5/6 Series MSO Programmer Manual (077130526) 实现
    支持以下主要功能:
    - 波形采集与读取
    - 通道控制 (垂直刻度、偏移、耦合等)
    - 触发设置 (边沿、脉宽、超时、视频等)
    - 水平系统 (时基、位置、缩放)
    - 测量功能 (自动测量、光标)
    - 数学运算 (FFT、滤波、波形运算)
    - 文件操作 (设置保存/召回、截图)
    """

    # Tektronix 源类型映射
    SourceType = {
        "CHANnel": "CH",
        "Math": "MATH",
        "Ref": "REF",
        "Dig": "D",
        "Bus": "BUS",
    }

    # 触发类型
    TRIGGER_TYPES = [
        "EDGE", "GLITch", "PULSe", "TRANsition", "RUNT", "TIMEout",
        "SETup", "LOGIC", "VIDeo", "IIC", "SPI", "RS232", "CAN", "LIN",
        "FLEXray", "I2S", "MIL1553B",
    ]

    # 耦合类型
    COUPLING_TYPES = ["DC", "AC", "GND"]

    # 带宽限制
    BANDWIDTH_TYPES = ["FULL", "250MHZ", "20MHZ"]

    # 采集模式
    ACQUIRE_MODES = ["SAMPLE", "PEAKDETect", "HIRes", "AVERAGE"]

    # 测量槽位最大数量 (Tektronix 4/5/6 MSO 通常支持 8 个)
    MAX_MEAS_SLOTS = 8

    def __init__(self, instrument_address, timeout: float = 5000, logger=None):
        super().__init__(instrument_address, timeout, logger=logger)
        self._waveview = "WAVEView1"
        # 测量槽位轮询计数器 (避免每次查询 STATE? 太慢)
        self._meas_slot_counter = 0

    # ===============================================================================
    #                              系统命令
    # ===============================================================================
    def system_reset(self):
        """*RST - 重置示波器到默认状态"""
        self.send_command('*RST')

    def system_self_calibrate(self):
        """执行自校准，返回校准结果"""
        result = self.send_command('*CAL?')
        return result == '0'

    def system_get_id(self) -> str:
        """*IDN? - 获取仪器标识符"""
        return self.send_command('*IDN?')

    def system_get_status(self) -> str:
        """*STB? - 获取状态字节"""
        return self.send_command('*STB?')

    def system_clear_status(self):
        """*CLS - 清除状态寄存器"""
        self.send_command('*CLS')

    # ===============================================================================
    #                              文件命令
    # ===============================================================================
    def get_screen_image(self, image_format: str = 'BMP', color: bool = True, timeout: int = 30000) -> bytes:
        """
        读取示波器屏幕截图

        Args:
            image_format: 图片格式，Tektronix 仅支持 'BMP'
            color: 是否彩色
            timeout: 超时时间 (ms)

        Returns:
            图片数据的字节
        """
        if image_format.upper() != 'BMP':
            self.logger.warning(f"Tektronix 示波器仅支持 BMP 格式，已自动切换")
            image_format = 'BMP'

        original_timeout = self._virtual_device.timeout
        self._virtual_device.timeout = timeout

        try:
            self.logger.info(f"截取屏幕 ({image_format} 格式，超时：{timeout}ms)")
            self.send_command(r'FILESYSTEM:DELETE "C:/waveform_screen.bmp";*OPC?')
            self.send_command(r'SAVE:IMAGE "C:/waveform_screen.bmp";*OPC?')
            self._virtual_device.write(r'FILESYSTEM:READFILE "C:/waveform_screen.bmp"')

            raw_data = self._virtual_device.read_raw()

            if raw_data.startswith(b"#"):
                header_len = int(raw_data[1:2])
                data_start = 2 + header_len
                img_data = raw_data[data_start:-1]
                self.logger.debug(f"截图完成：{len(img_data)} 字节")
                return img_data

            self.logger.debug(f"截图完成 (无头部): {len(raw_data)} 字节")
            return raw_data

        except pyvisa.VisaIOError as e:
            if "timeout" in str(e).lower():
                self.logger.error(f"截图超时：{e}")
                raise Exception(f"截图超时 (>{timeout}ms)")
            self.logger.error(f"截图数据获取失败：{e}")
            raise Exception(f"截图数据获取失败：{e}")
        finally:
            self._virtual_device.timeout = original_timeout

    def file_save_setup(self, file_path: str):  # NOQA
        """保存示波器设置到文件"""
        self.send_command(f'SAVE:SETUP "{file_path}";*OPC?')

    def file_recall_setup(self, file_path: str):  # NOQA
        """从文件召回示波器设置"""
        self.send_command(f'RECALL:SETUP "{file_path}";*OPC?')

    def file_delete(self, file_path: str):
        """删除示波器上的文件"""
        self.send_command(f'FILESYSTEM:DELETE "{file_path}"')

    # ===============================================================================
    #                              运行控制命令
    # ===============================================================================
    def run_ctl_press_run(self):
        """运行/继续采集 (RUNSTop 模式)"""
        # Tektronix 4/5/6 MSO: RUNSTop = 连续采集
        self.send_command('ACQuire:STOPAfter RUNSTop')
        self.send_command('ACQuire:STATE 1')

    def run_ctl_press_single(self):
        """单次触发 (SEQuence 模式)"""
        # Tektronix 4/5/6 MSO: SEQuence = 单次采集
        self.send_command('ACQuire:STOPAfter SEQuence')
        self.send_command('ACQuire:STATE 1')

    def run_ctl_press_stop(self):
        """停止采集"""
        # Tektronix 4/5/6 MSO: STOP / OFF
        self.send_command('ACQuire:STATE 0')

    def run_ctl_get_acquisition_status(self) -> str:
        """获取采集状态"""
        return self.send_command('ACQuire:STATE?')

    def run_ctl_wait_for_acquisition(self, timeout: float = 10.0):
        """等待采集完成"""
        import time
        start_time = time.time()
        while time.time() - start_time < timeout:
            status = self.run_ctl_get_acquisition_status()
            if status == '0':
                return
            time.sleep(0.1)
        raise TimeoutError(f"采集超时 ({timeout}秒)")

    # ===============================================================================
    #                              采集系统命令
    # ===============================================================================
    def acquire_set_mode(self, mode: str = 'SAMPLE'):
        """
        设置采集模式

        Args:
            mode: 采集模式 [SAMPLE|PEAKDETect|HIRes|AVERAGE]
        """
        if mode.upper() not in self.ACQUIRE_MODES:
            raise Exception(f"mode 必须是 {self.ACQUIRE_MODES} 之一")
        self.send_command(f'ACQuire:MODe {mode.upper()}')

    def acquire_get_mode(self) -> str:
        """获取采集模式"""
        return self.send_command('ACQuire:MODe?')

    def acquire_set_sample_rate(self, sample_rate: float):
        """设置采样率 (Sa/s)"""
        self.send_command(f'ACQuire:SAMPLERate {sample_rate}')

    def acquire_get_sample_rate(self) -> float:
        """获取采样率"""
        return float(self.send_command('ACQuire:SAMPLERate?'))

    def acquire_set_record_length(self, length: int):
        """设置记录长度 (点数)"""
        self.send_command(f'HORizontal:RECORDLength {length}')

    def acquire_get_record_length(self) -> int:
        """获取记录长度"""
        return int(self.send_command('HORizontal:RECORDLength?'))

    def acquire_set_num_avg(self, num_avg: int):
        """设置平均次数 (2-1000)"""
        if num_avg < 2 or num_avg > 1000:
            raise ValueError("平均次数必须在 2-1000 之间")
        self.send_command(f'ACQuire:NUMAVg {num_avg}')

    def acquire_get_num_avg(self) -> int:
        """获取平均次数"""
        return int(self.send_command('ACQuire:NUMAVg?'))

    # ===============================================================================
    #                              水平系统命令
    # ===============================================================================
    def horizon_set_time_base_scale(self, scale_value: float = 1.0, scale_suffix: str = 's'):
        """设置时基刻度 (秒/格)"""
        if scale_value <= 0:
            raise ValueError("scale_value 必须大于 0")
        scale_value = self.set_value_to_scale(float(scale_value), scale_suffix)
        self.send_command(f"HORizontal:MAIn:SCAle {scale_value}")
        return float(self.send_command(f"HORizontal:MAIn:SCAle?"))

    def horizon_get_time_base_scale(self) -> float:
        """获取时基刻度"""
        return float(self.send_command('HORizontal:MAIn:SCAle?'))

    def horizon_set_time_base_position(self, position_value: float = 0.0, position_suffix: str = 's'):
        """设置水平位置 (触发点位置)"""
        position_value = self.set_value_to_scale(float(position_value), position_suffix)
        self.send_command(f"HORizontal:MAIn:POSition {position_value}")
        return float(self.send_command(f"HORizontal:MAIn:POSition?"))

    def horizon_set_time_base_delay(self, delay_value: float = 0.0, delay_suffix: str = 's'):
        """
        设置水平延迟 (触发点时间偏移)

        Tektronix 4/5/6 MSO 有两种模式:
        - HORizontal:DELay:MODe OFF -> 使用 HORizontal:POSition (百分比 0-100)
        - HORizontal:DELay:MODe ON  -> 使用 HORizontal:DELay:TIMe (秒)

        这里使用 delay mode 来精确设置时间

        Args:
            delay_value: 延迟时间值
            delay_suffix: 单位后缀 [s|ms|us|ns|ps]
        """
        delay_value = self.set_value_to_scale(float(delay_value), delay_suffix)
        # 开启 delay 模式
        self.send_command("HORizontal:DELay:MODe ON")
        # 设置延迟时间 (秒)
        self.send_command(f"HORizontal:DELay:TIMe {delay_value}")
        return float(self.send_command(f"HORizontal:DELay:TIMe?"))

    def horizon_get_time_base_position(self) -> float:
        """获取水平位置"""
        return float(self.send_command('HORizontal:MAIn:POSition?'))

    def horizon_set_mode(self, mode: str = 'MAIN'):
        """
        设置水平模式

        Args:
            mode: ['MAIN', 'WINDow', 'XY', 'ROLL']
                  MAIN - 主时基模式
                  WINDow - 启用缩放窗口
                  XY - XY 模式
                  ROLL - 滚动模式
        """
        if mode not in ['MAIN', 'WINDow', 'XY', 'ROLL']:
            raise Exception(f"mode 只能是 ['MAIN', 'WINDow', 'XY', 'ROLL']")
        if mode == 'MAIN':
            # 关闭缩放窗口
            self.send_command('DISplay:WAVEView1:ZOOM:ZOOM1:STATe OFF')
        elif mode == 'WINDow':
            # 开启缩放窗口
            self.send_command('DISplay:WAVEView1:ZOOM:ZOOM1:STATe ON')
        elif mode == 'XY':
            self.send_command('HORizontal:MODE XY')
        elif mode == 'ROLL':
            self.send_command('HORizontal:MODE ROLL')

    def horizon_zoom_set_time_scale(self, scale_value: float = 1.0, scale_suffix: str = 's'):
        """
        设置缩放窗口的水平刻度 (秒/格)

        Tektronix 4/5/6 MSO 用缩放因子 (zoom factor) 表达，
        需要根据主时基刻度计算缩放因子

        Args:
            scale_value: 刻度值
            scale_suffix: 单位后缀
        """
        if scale_value <= 0:
            raise ValueError("scale_value 必须大于 0")
        # 转换为秒
        zoom_scale_sec = self.set_value_to_scale(float(scale_value), scale_suffix)
        # 获取主时基刻度
        main_scale_sec = float(self.send_command('HORizontal:MAIn:SCAle?'))
        if main_scale_sec <= 0:
            main_scale_sec = zoom_scale_sec
        # 计算缩放因子 (必须是 1, 2, 4, 8, 16... 等整数倍)
        zoom_factor = max(1, round(main_scale_sec / zoom_scale_sec))
        # 限制在合法范围
        valid_factors = [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024]
        # 找最接近的合法值
        zoom_factor = min(valid_factors, key=lambda x: abs(x - zoom_factor))
        self.send_command(f"DISplay:WAVEView1:ZOOM:ZOOM1:HORizontal:SCALe {zoom_factor}")
        # 确保缩放窗口开启
        self.send_command('DISplay:WAVEView1:ZOOM:ZOOM1:STATe ON')
        return float(self.send_command("DISplay:WAVEView1:ZOOM:ZOOM1:HORizontal:SCALe?"))

    def horizon_zoom_set_time_position(self, pose_value: float = 0.0, pose_suffix: str = 's'):
        """
        设置缩放窗口的水平位置 (秒)

        Tektronix 4/5/6 MSO 用百分比 (0-100) 表示缩放位置

        Args:
            pose_value: 位置值 (秒)
            pose_suffix: 单位后缀
        """
        position_sec = self.set_value_to_scale(float(pose_value), pose_suffix)
        # 获取主时基位置和刻度，计算百分比
        # 简化处理：直接使用百分比值
        # 这里将秒值转换为相对位置百分比
        main_scale_sec = float(self.send_command('HORizontal:MAIn:SCAle?'))
        # 主时基满屏 = 10 * main_scale_sec
        full_screen_sec = 10 * main_scale_sec
        if full_screen_sec > 0:
            position_pct = (position_sec / full_screen_sec) * 100
            # 限制在 0-100
            position_pct = max(0, min(100, position_pct))
        else:
            position_pct = 50
        self.send_command(f"DISplay:WAVEView1:ZOOM:ZOOM1:HORizontal:POSition {position_pct}")
        return float(self.send_command("DISplay:WAVEView1:ZOOM:ZOOM1:HORizontal:POSition?"))

    # ===============================================================================
    #                              触发系统命令
    # ===============================================================================
    def trigger_set_mode(self, mode: str = 'AUTO') -> str:
        """
        设置触发模式

        Args:
            mode: 触发模式 [AUTO|NORMal]
                  AUTO - 自动模式 (无信号时显示基线)
                  NORMal - 正常模式 (无触发不扫描)
        """
        # 大小写归一化: 接受 AUTO/NORMAL/Auto/Normal 等各种写法
        mode_upper = mode.upper()
        if mode_upper in ['AUTO', 'AUTOMATIC']:
            mode_value = 'AUTO'
        elif mode_upper in ['NORMAL', 'NORM']:
            mode_value = 'NORMal'
        else:
            raise Exception(f"mode 必须是 'AUTO' 或 'NORMal'，实际传入: {mode}")
        self.send_command(f'TRIGger:A:MODe {mode_value}')
        return self.send_command(f'TRIGger:A:MODe?')

    def trigger_get_mode(self) -> str:
        """获取触发模式"""
        return self.send_command('TRIGger:A:MODe?')

    def trigger_set_type(self, trigger_type: str = 'EDGE') -> str:
        """设置触发类型"""
        if trigger_type.upper() not in self.TRIGGER_TYPES:
            raise Exception(f"trigger_type 必须是 {self.TRIGGER_TYPES} 之一")
        self.send_command(f'TRIGger:A:TYPe {trigger_type.upper()}')
        return self.send_command(f'TRIGger:A:TYPe?')

    def trigger_get_type(self) -> str:
        """获取触发类型"""
        return self.send_command('TRIGger:A:TYPe?')

    # Tektronix 触发斜率映射 (InfiniiVision -> Tektronix)
    # InfiniiVision: POSitive/NEGative/ALTernate/Either
    # Tektronix:     RISe/FALL/EITher
    TEK_SLOPE_MAP = {
        "POSitive": "RISe",
        "NEGative": "FALL",
        "ALTernate": "EITher",
        "Either": "EITher",
        # 直接接受 Tek 原生值
        "RISe": "RISe",
        "FALL": "FALL",
        "EITher": "EITher",
    }

    def trigger_set_edge_option(self, source_type: Union[SourceTriggerType, str],
                                source_number: int = None,
                                slope: Union[TriggerSlopeType, str] = TriggerSlopeType.Rising,
                                level: Union[float, str] = 0.0):
        """
        设置边沿触发参数

        Tektronix 4/5/6 MSO 命令:
            TRIGger:A:TYPe EDGE
            TRIGger:A:EDGE:SOUrce CH<x>
            TRIGger:A:EDGE:SLOPe {RISe|FALL|EITher}
            TRIGger:A:LEVel:CH<x> <NR3> (volts, 纯数值)

        Args:
            source_type: 源类型
            source_number: 源编号
            slope: 斜率 (接受 TriggerSlopeType 枚举或字符串 POSitive/NEGative/RISe/FALL/Either)
            level: 触发电平 (伏特)，可为 float 或字符串如 "500mV"、"1.5V"
        """
        if isinstance(source_type, SourceTriggerType):
            source = source_type.value
        else:
            source = source_type

        if source not in ["EXTernal", "LINE"]:
            source = self._validate_source_parameters(source, source_number)

        # 斜率归一化
        if isinstance(slope, TriggerSlopeType):
            slope_str = slope.value
        else:
            slope_str = str(slope)

        # 转换为 Tektronix 标准值
        tek_slope = self.TEK_SLOPE_MAP.get(slope_str, slope_str)
        if tek_slope not in ["RISe", "FALL", "EITher"]:
            raise Exception(f"不支持的 slope 值: {slope_str}，合法值: RISe/FALL/EITher")

        # level 转换为 float (NR3)
        if isinstance(level, str):
            level_value = change_str_value_to_scale(level)
        else:
            level_value = float(level)

        self.send_command('TRIGger:A:TYPe EDGE')
        self.send_command(f'TRIGger:A:EDGE:SOUrce {source}')
        self.send_command(f'TRIGger:A:EDGE:SLOPe {tek_slope}')
        # Tektronix: 触发电平用 NR3 (纯数值)，格式 TRIGger:A:LEVel:CH<x> <NR3>
        if source.startswith('CH'):
            ch_num = source[2:]
            # 使用科学计数法确保 NR3 格式
            self.send_command(f'TRIGger:A:LEVel:CH{ch_num} {level_value:E}')
        else:
            self.send_command(f'TRIGger:A:LEVel {level_value:E}')

    def trigger_set_level(self, level: Union[float, str],
                          source_type: Union[SourceTriggerType, str] = None,
                          source_number: int = None):
        """
        设置触发电平

        Tektronix 4/5/6 MSO 格式: TRIGger:A:LEVel:CH<x> <NR3>
        必须指定通道才能生效

        Args:
            level: 触发电平 (伏特)，可为 float 或字符串如 "500mV"
            source_type: 源类型
            source_number: 源编号
        """
        # level 转换为 float
        if isinstance(level, str):
            level_value = change_str_value_to_scale(level)
        else:
            level_value = float(level)

        if source_type is not None and source_number is not None:
            source = self._validate_source_parameters(source_type, source_number)
            if source.startswith('CH'):
                ch_num = source[2:]
                self.send_command(f'TRIGger:A:LEVel:CH{ch_num} {level_value:E}')
            else:
                self.send_command(f'TRIGger:A:LEVel:{source} {level_value:E}')
        else:
            self.send_command(f'TRIGger:A:LEVel {level_value:E}')

    def trigger_get_level(self, source_type: Union[SourceTriggerType, str] = None,
                          source_number: int = None) -> float:
        """获取触发电平"""
        if source_type is not None and source_number is not None:
            source = self._validate_source_parameters(source_type, source_number)
            if source.startswith('CH'):
                ch_num = source[2:]
                return float(self.send_command(f'TRIGger:A:LEVel:CH{ch_num}?'))
            return float(self.send_command(f'TRIGger:A:LEVel:{source}?'))
        return float(self.send_command('TRIGger:A:LEVel?'))

    def trigger_set_pulse_width(self, source_type: Union[SourceWaveformType, str],
                                source_number: int,
                                polarity: str = 'POSitive',
                                width: float = 1e-6,
                                condition: str = 'LESStHAN'):
        """设置脉宽触发"""
        source = self._validate_source_parameters(source_type, source_number)
        self.send_command('TRIGger:A:TYPe PULSe')
        self.send_command(f'TRIGger:A:PULSe:SOUrce {source}')
        self.send_command(f'TRIGger:A:PULSe:POLarity {polarity}')
        self.send_command(f'TRIGger:A:PULSe:WIDth {width}')
        self.send_command(f'TRIGger:A:PULSe:WHEN {condition}')

    # ===============================================================================
    #                              通道命令
    # ===============================================================================
    def _validate_source_parameters(self, source_type: Union[SourceWaveformType, str],
                                    source_number: Optional[int]) -> str:
        """验证源参数并返回格式化字符串"""
        if isinstance(source_type, str):
            for source in SourceWaveformType:
                if source.value.lower() == source_type.lower():
                    source_type = source
                    break
        if not isinstance(source_type, SourceWaveformType):
            raise TypeError("source_type 必须是 SourceWaveformType 枚举")

        if source_number is not None and source_number <= 0:
            raise ValueError("通道号不能低于 1")

        source_string = "CH"
        for name, string in self.SourceType.items():
            if name == source_type.value:
                source_string = string
                break

        return f"{source_string}{source_number}"

    def source_set_status(self, source_type: Union[SourceWaveformType, str],
                          source_number: int = None,
                          status: Union[str, int] = 'ON'):
        """设置通道显示状态"""
        source = self._validate_source_parameters(source_type, source_number)
        if status not in self.SOURCE_STATUS:
            raise Exception(f"status 必须是 {self.SOURCE_STATUS} 之一")
        self.send_command(f'DISplay:{self._waveview}:{source}:STATE {status}')
        return self.send_command(f'DISplay:{self._waveview}:{source}:STATE?')

    def source_get_status(self, source_type: Union[SourceWaveformType, str],
                          source_number: int = None) -> str:
        """获取通道显示状态"""
        source = self._validate_source_parameters(source_type, source_number)
        return self.send_command(f'DISplay:{self._waveview}:{source}:STATE?')

    def source_set_vertical(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                            source_number: int = None,
                            vertical_value: float = 1.0, vertical_suffix: str = 'V'):
        """设置通道垂直刻度 (伏特/格)"""
        source = self._validate_source_parameters(source_type, source_number)
        value = self.set_value_to_scale(vertical_value, vertical_suffix)
        self.send_command(f'{source}:SCAle {value}')
        return float(self.send_command(f'{source}:SCAle?'))

    def source_get_vertical(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                            source_number: int = None) -> float:
        """获取通道垂直刻度"""
        source = self._validate_source_parameters(source_type, source_number)
        return float(self.send_command(f'{source}:SCAle?'))

    def source_set_offset(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                          source_number: int = None,
                          offset_value: float = 0.0, offset_suffix: str = 'V'):
        """
        设置通道垂直偏移 (UI 上叫 offset)

        Tektronix 4/5/6 MSO:
            CH<x>:OFFSet <NR3>  - 中心电压偏置 (单位: 伏特)
            - 让波形在屏幕上明显移动 (用户输入的电压值直接作为偏移量)

        Args:
            source_type: 源类型
            source_number: 源编号
            offset_value: 偏移值 (伏特)
            offset_suffix: 单位后缀 [V|mV|uV|nV]
        """
        source = self._validate_source_parameters(source_type, source_number)
        # 将用户输入的值转换为伏特 (float)
        value_v = self.set_value_to_scale(float(offset_value), offset_suffix)

        # 使用 NR3 科学计数法格式发送，确保 Tek 接受
        nr3_value = f"{float(value_v):E}"
        self.send_command(f'{source}:OFFSet {nr3_value}')
        # 用 *OPC? 同步等待执行完成
        self.send_command('*OPC?')
        return float(self.send_command(f'{source}:OFFSet?'))

    def source_get_offset(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                          source_number: int = None) -> float:
        """获取通道偏移"""
        source = self._validate_source_parameters(source_type, source_number)
        return float(self.send_command(f'{source}:OFFSet?'))

    def source_set_position(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                            source_number: int = None,
                            position: float = 0.0):
        """设置通道垂直位置 (格数)"""
        source = self._validate_source_parameters(source_type, source_number)
        self.send_command(f'{source}:POSition {position}')
        return float(self.send_command(f'{source}:POSition?'))

    def ch_set_coupling(self, channel_number: int = 1, coupling: str = 'DC'):
        """设置通道耦合方式"""
        if coupling.upper() not in self.COUPLING_TYPES:
            raise Exception(f"coupling 必须是 {self.COUPLING_TYPES} 之一")
        self.send_command(f'CH{channel_number}:COUPling {coupling.upper()}')

    def ch_get_coupling(self, channel_number: int = 1) -> str:
        """获取通道耦合方式"""
        return self.send_command(f'CH{channel_number}:COUPling?')

    def ch_set_bandwidth(self, channel_number: int = 1, bandwidth: str = 'FULL'):
        """设置通道带宽限制"""
        if bandwidth.upper() not in self.BANDWIDTH_TYPES:
            raise Exception(f"bandwidth 必须是 {self.BANDWIDTH_TYPES} 之一")
        self.send_command(f'CH{channel_number}:BANdwidth {bandwidth.upper()}')

    def ch_get_bandwidth(self, channel_number: int = 1) -> str:
        """获取通道带宽限制"""
        return self.send_command(f'CH{channel_number}:BANdwidth?')

    def ch_set_invert(self, channel_number: int = 1, invert: bool = False):
        """设置通道反相"""
        self.send_command(f'CH{channel_number}:INVert {"ON" if invert else "OFF"}')

    def ch_get_invert(self, channel_number: int = 1) -> bool:
        """获取通道反相状态"""
        return self.send_command(f'CH{channel_number}:INVert?') == '1'

    def ch_set_probe_gain(self, channel_number: int = 1, gain: float = 1.0):
        """设置探头衰减/增益"""
        self.send_command(f'CH{channel_number}:PRObe:GAIN {gain}')

    def ch_get_probe_gain(self, channel_number: int = 1) -> float:
        """获取探头增益"""
        return float(self.send_command(f'CH{channel_number}:PRObe:GAIN?'))

    def source_set_label(self, label: str,
                         source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                         source_number: int = None):
        """
        设置通道标签

        Tektronix 4/5/6 MSO 格式: CH<x>:LABel:NAMe "<label>"
        需要先开启 label 显示

        Args:
            label: 标签文本 (1-32 字符)
            source_type: 源类型
            source_number: 源编号
        """
        source = self._validate_source_parameters(source_type, source_number)
        # Tektronix: 先开启 label 显示
        self.send_command(":DISPlay:LABel ON")
        # Tektronix: CH<x>:LABel:NAMe "<QString>"
        self.send_command(f'{source}:LABel:NAMe "{label}"')
        return self.send_command(f'{source}:LABel:NAMe?')

    def source_set_label_status(self, status: Union[str, int] = 'ON'):
        """设置 label 显示状态"""
        if status not in self.SOURCE_STATUS:
            raise Exception(f"status 必须是 {self.SOURCE_STATUS} 之一")
        self.send_command(f":DISPlay:LABel {status}")
        return self.send_command(f":DISPlay:LABel?")

    # ===============================================================================
    #                              波形数据命令
    # ===============================================================================
    def waveform_set_source(self, source_type: Union[SourceWaveformType, str],
                            source_number: int = None):
        """设置波形数据源"""
        source = self._validate_source_parameters(source_type, source_number)
        self.send_command(f'DATA:SOUrce {source}')

    def waveform_get_source(self) -> str:
        """获取波形数据源"""
        return self.send_command('DATA:SOUrce?')

    def waveform_set_encoding(self, encoding: str = 'RIBinary'):
        """
        设置波形数据编码格式

        Tektronix 4/5/6 MSO 支持的编码:
            - ASCIi - ASCII 文本
            - RIBinary - 有符号整数 (大端)
            - RPBinary - 无符号整数 (大端)
            - FPBinary - 浮点数
            - SRIbinary - 有符号整数 (小端)
            - SRPbinary - 无符号整数 (小端)
            - SFPbinary - 浮点数 (小端)

        Args:
            encoding: 编码格式，默认 RIBinary
        """
        valid_encodings = ['ASCIi', 'RIBinary', 'RPBinary', 'FPBinary',
                           'SRIbinary', 'SRPbinary', 'SFPbinary']
        if encoding not in valid_encodings:
            raise Exception(f"encoding 必须是 {valid_encodings} 之一")
        self.send_command(f'DATA:ENCdg {encoding}')

    def waveform_set_width(self, width: str = 'BYTE'):
        """设置波形数据宽度"""
        self.send_command(f'DATA:WIDTh {width}')

    def waveform_set_start_point(self, start_point: int = 1):
        """设置波形起始点"""
        self.send_command(f'DATA:STARt {start_point}')

    def waveform_set_stop_point(self, stop_point: int = 10000):
        """设置波形终止点"""
        self.send_command(f'DATA:STOP {stop_point}')

    def waveform_get_preamble(self) -> dict:
        """
        获取波形前导信息

        返回字典，键值如下:
            BYT_Nr: 每点字节数 (1/2/4/8)
            BIT_Nr: 每点位数
            ENCDG: 编码方式
            BN_FMT: 二进制格式
            BYTE_ORDER: 字节序
            PT_ORDER: 点序
            NR_PT: 点数
            WFMT: 波形格式
            XUNIT: X 单位
            XINCR: X 增量
            XZERO: X 起始值
            PT_OFF: 点偏移
            YUNIT: Y 单位
            YMULT: Y 缩放因子
            YZERO: Y 零点偏移
            YOFF: Y 偏移
        """
        response = self.send_command('WFMOutpre?')
        parts = response.split(';')
        # Tektronix preamble 字段顺序:
        # BYT_Nr;BIT_Nr;ENCDG;BN_FMT;BYTE_ORDER;PT_ORDER;NR_PT;
        # WFMT;XUNIT;XINCR;XZERO;PT_OFF;YUNIT;YMULT;YZERO;YOFF;
        # WFID;WFAVAIL;WFSAMPLE;AVAIL_MODE;ACQMODE;AVGS;WARN;RISW
        field_names = ['BYT_Nr', 'BIT_Nr', 'ENCDG', 'BN_FMT', 'BYTE_ORDER', 'PT_ORDER',
                       'NR_PT', 'WFMT', 'XUNIT', 'XINCR', 'XZERO', 'PT_OFF',
                       'YUNIT', 'YMULT', 'YZERO', 'YOFF']
        preamble = {}
        for i, part in enumerate(parts):
            if i < len(field_names):
                preamble[field_names[i]] = part.strip().strip('"')
            else:
                preamble[f'FIELD_{i}'] = part.strip().strip('"')
        return preamble

    def waveform_get_data_binary(self, source_type: Union[SourceWaveformType, str],
                                 source_number: int = None,
                                 start_point: int = 1,
                                 stop_point: int = None,
                                 timeout: int = 30000) -> tuple:
        """
        获取二进制波形数据

        Tektronix 4/5/6 MSO 波形读取流程:
            1. DATA:SOUrce <source>   - 选择源
            2. DATA:ENCdg RIBinary    - 设置编码 (有符号整数)
            3. DATA:STARt/STOP        - 设置范围
            4. WFMOutpre?             - 获取前导信息
            5. CURVe?                  - 读取数据

        Args:
            source_type: 源类型
            source_number: 源编号
            start_point: 起始点 (1-based)
            stop_point: 终止点 (None 表示全部)
            timeout: 超时时间 (ms)，默认 30000ms (30s)

        Returns:
            (voltage_data, time_data, preamble) 或 (None, None, preamble)
        """
        source = self._validate_source_parameters(source_type, source_number)
        # 1. 选择数据源
        self.send_command(f'DATA:SOUrce {source}')
        # 2. 设置编码为有符号整数 (推荐用于 Tektronix)
        self.send_command('DATA:ENCdg RIBinary')
        # 3. 设置数据范围
        self.send_command(f'DATA:STARt {start_point}')
        if stop_point:
            self.send_command(f'DATA:STOP {stop_point}')

        # 4. 获取前导信息 (确定每点字节数等)
        preamble = self.waveform_get_preamble()
        byt_nr = int(preamble.get('BYT_Nr', 1))

        # 5. 设置超时并读取数据
        # 1M 点数据读取可能较慢，需要较大超时
        original_timeout = self._virtual_device.timeout
        self._virtual_device.timeout = timeout

        try:
            # 用 *OPC? 同步等待前序命令完成
            self.send_command('*OPC?')
            # 发送 CURVe? 查询
            self._virtual_device.write('CURVe?')
            raw_data = self._virtual_device.read_raw()
        finally:
            self._virtual_device.timeout = original_timeout

        # 解析 IEEE 488.2 块数据
        if raw_data.startswith(b'#'):
            # 读取头部长度位 (第二个字符)
            header_len = int(raw_data[1:2])
            # 读取数据长度
            data_len = int(raw_data[2:2+header_len])
            data_start = 2 + header_len
            data_bytes = raw_data[data_start:data_start+data_len]

            # 根据 BYT_Nr 选择数据类型
            if byt_nr == 1:
                dtype = np.int8
            elif byt_nr == 2:
                dtype = '>i2'  # 大端有符号 16 位
            elif byt_nr == 4:
                dtype = '>i4'  # 大端有符号 32 位
            elif byt_nr == 8:
                dtype = '>i8'  # 大端有符号 64 位
            else:
                dtype = np.int8

            data = np.frombuffer(data_bytes, dtype=dtype)
            # 转为浮点数处理
            data = data.astype(np.float64)

            # 获取缩放参数
            ymult = float(preamble.get('YMULT', 1))
            yzero = float(preamble.get('YZERO', 0))
            yoff = float(preamble.get('YOFF', 0))
            xmult = float(preamble.get('XINCR', 1))
            xzero = float(preamble.get('XZERO', 0))
            pt_off = int(preamble.get('PT_OFF', 0))

            # 转换为实际电压值: voltage = (data - yoff) * ymult + yzero
            voltage_data = (data - yoff) * ymult + yzero
            # 时间轴: time = (index - pt_off) * xmult + xzero
            time_data = (np.arange(len(data)) - pt_off) * xmult + xzero

            return voltage_data, time_data, preamble

        self.logger.warning("波形数据未以 IEEE 块格式返回")
        return None, None, preamble

    def file_save_channel_waveform_to_csv(self, save_dir: Union[PathLike[str], str],
                                          source_type: Union[SourceWaveformType, str],
                                          source_number: int = 1,
                                          num_points: int = None,
                                          csv_name: str = 'waveform_data.csv'):
        """保存通道波形到 CSV 文件"""
        source = self._validate_source_parameters(source_type, source_number)
        voltage_data, time_data, preamble = self.waveform_get_data_binary(
            source_type, source_number, 1, num_points
        )

        if voltage_data is None:
            raise Exception("无法获取波形数据")

        csv_path = Path(save_dir) / csv_name
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        np.savetxt(csv_path, np.c_[time_data, voltage_data],
                   delimiter=",", header="Time(s),Voltage(V)", comments='')
        self.logger.info(f"波形数据已保存到 {csv_path}")
        return csv_path

    # ===============================================================================
    #                              测量命令
    # ===============================================================================
    # InfiniiVision 测量类型 -> Tektronix 测量类型映射
    # Tektronix 测量类型完整列表见 MEASUrement:MEAS<x>:TYPe
    MEASURE_TYPES = {
        'VPP': 'PK2PK',
        'Pk-Pk': 'PK2PK',
        'Max': 'MAXIMUM',
        'Min': 'MINIMUM',
        'Ampl': 'AMPLITUDE',
        'Top': 'TOP',
        'Base': 'BASE',
        'Overshoot': 'POVERSHOOT',
        'Preshoot': 'NOVERSHOOT',
        'Avg-Cyc': 'MEAN',
        'Avg-FS': 'MEAN',
        'DC RMS-Cyc': 'RMS',
        'DC RMS-FS': 'RMS',
        'AC RMS-Cyc': 'ACRMS',
        'AC RMS-FS': 'ACRMS',
        'Period': 'PERIOD',
        'Freq': 'FREQUENCY',
        'Counter': 'FREQUENCY',
        '+Width': 'PWIDTH',
        '-Width': 'NWIDTH',
        'Burst Width': 'BURSTWIDTH',
        '+Duty': 'PDUTY',
        '-Duty': 'NDUTY',
        'Rise': 'RISETIME',
        'Fall': 'FALLTIME',
        'Delay': 'DELAY',
        'Phase': 'PHASE',
        'Area-Cyc': 'AREA',
        'Area-FS': 'AREA',
        'Slew': 'RISESLEWRATE',
    }

    @staticmethod
    def _convert_source_string(source: str) -> str:
        """
        将 InfiniiVision 源字符串 (如 'CHANnel1') 转换为 Tektronix 格式 (如 'CH1')

        Args:
            source: 源字符串，如 'CHANnel1'、'FUNCtion1'、'WMEMory1'

        Returns:
            Tektronix 格式源字符串，如 'CH1'、'MATH1'、'REF1'
        """
        # 源类型映射
        source_map = {
            'CHANnel': 'CH',
            'FUNCtion': 'MATH',
            'WMEMory': 'REF',
            'MATH': 'MATH',
            'REF': 'REF',
            'DIGital': 'D',
            'BUS': 'BUS',
            'SBUS': 'BUS',
        }
        # 提取数字部分和类型部分
        match = re.match(r'^([a-zA-Z]+)(\d+)$', source)
        if match:
            type_part = match.group(1)
            num_part = match.group(2)
            tek_type = source_map.get(type_part, type_part)
            return f"{tek_type}{num_part}"
        return source

    def meas_set_status(self, status: Union[str, int] = 'ON') -> int:
        """
        开启/关闭测量显示

        Tektronix 4/5/6 MSO 没有全局测量开关，
        通过 MEASUrement:MEAS<x>:STATE 控制单个测量

        Args:
            status: ON/OFF
        """
        if status not in self.SOURCE_STATUS:
            raise Exception(f"status 必须是 {self.SOURCE_STATUS} 之一")
        # 这里只记录状态，实际控制需要在 meas_show_measure 中处理
        return 1

    def meas_clear_all(self) -> None:
        """清除所有测量"""
        # Tektronix: 关闭所有测量槽位并重置计数器
        for i in range(1, self.MAX_MEAS_SLOTS + 1):
            self.send_command(f'MEASUrement:MEAS{i}:STATE OFF')
        self._meas_slot_counter = 0

    def meas_show_measure(self, measure_type: str = 'ALL', source1: str = "CHANnel1",
                          source2: str = "CHANnel2", **kwargs):
        """
        添加屏幕测量

        Tektronix 4/5/6 MSO 命令:
            MEASUrement:MEAS<x>:TYPe <type>
            MEASUrement:MEAS<x>:SOUrce1 <source>
            MEASUrement:MEAS<x>:SOUrce2 <source>  (双源测量)
            MEASUrement:MEAS<x>:STATE ON

        使用轮询计数器分配槽位，避免查询 STATE? (查询很慢)

        Args:
            measure_type: 测量类型 (见 MEASURE_TYPES)
            source1: 主源 (如 'CHANnel1' 或 'CH1')
            source2: 次源 (可选，用于双源测量如 Delay/Phase)
        """
        # 'ALL' 不是 Tektronix 支持的测量类型，跳过
        if measure_type == 'ALL':
            self.logger.warning("Tektronix 不支持 ALL 测量类型，请指定具体类型")
            return

        # 转换测量类型
        tek_type = self.MEASURE_TYPES.get(measure_type)
        if not tek_type:
            tek_type = measure_type
            self.logger.warning(f"测量类型 {measure_type} 不在映射表中，直接使用原值")

        # 转换源格式
        tek_source1 = self._convert_source_string(source1)
        tek_source2 = self._convert_source_string(source2) if source2 else None

        # 用计数器轮询分配槽位 (1..MAX_MEAS_SLOTS, 然后回到 1)
        self._meas_slot_counter = (self._meas_slot_counter % self.MAX_MEAS_SLOTS) + 1
        meas_slot = self._meas_slot_counter

        # 设置测量类型
        self.send_command(f'MEASUrement:MEAS{meas_slot}:TYPe {tek_type}')
        # 设置主源
        self.send_command(f'MEASUrement:MEAS{meas_slot}:SOUrce1 {tek_source1}')
        # 双源测量时设置次源
        if tek_source2 and tek_type in ['DELAY', 'PHASE']:
            self.send_command(f'MEASUrement:MEAS{meas_slot}:SOUrce2 {tek_source2}')
        # 开启测量
        self.send_command(f'MEASUrement:MEAS{meas_slot}:STATE ON')
        self.logger.info(f"已添加测量 #{meas_slot}: {tek_type} on {tek_source1}")

    def meas_set_type(self, measure_type: str, source_type: Union[SourceWaveformType, str],
                      source_number: int = None):
        """设置立即测量类型和源"""
        source = self._validate_source_parameters(source_type, source_number)
        tek_type = self.MEASURE_TYPES.get(measure_type, measure_type)
        self.send_command(f'MEASUrement:IMMed:TYPe {tek_type}')
        self.send_command(f'MEASUrement:IMMed:SOUrce1 {source}')

    def meas_get_value(self, measure_type: str = 'FREQ',
                       source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                       source_number: int = 1) -> float:
        """获取立即测量值"""
        source = self._validate_source_parameters(source_type, source_number)
        tek_type = self.MEASURE_TYPES.get(measure_type, measure_type)
        self.send_command(f'MEASUrement:IMMed:TYPe {tek_type}')
        self.send_command(f'MEASUrement:IMMed:SOUrce1 {source}')
        return float(self.send_command('MEASUrement:IMMed:VALue?'))

    def meas_get_all(self) -> list:
        """获取所有统计测量值"""
        response = self.send_command('MEASUrement:STATistic:ALL?')
        return response.split(',')

    def meas_set_thresholds(self, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                            source_number: int = None,
                            thresholds_mode: str = 'PERCent',
                            upper_middle_lower: list = ('90%', '50%', '10%')) -> str:
        """
        设置测量阈值

        Tektronix 4/5/6 MSO:
            MEASUrement:MEAS<x>:REFLevel:METHod {PERCent|ABSolute}
            MEASUrement:MEAS<x>:REFLevel:PERCent:HIGH <NR3>
            MEASUrement:MEAS<x>:REFLevel:PERCent:MID <NR3>
            MEASUrement:MEAS<x>:REFLevel:PERCent:LOW <NR3>
        """
        source = self._validate_source_parameters(source_type, source_number)
        if thresholds_mode not in ['STANdard', 'PERCent', 'ABSolute']:
            raise Exception("thresholds_mode 只能是 ['STANdard', 'PERCent', 'ABSolute']")

        # 使用测量槽位 1 的参考电平
        if thresholds_mode == 'PERCent':
            self.send_command('MEASUrement:REFLevel:METHod PERCent')
            # 解析百分比
            high, mid, low = upper_middle_lower
            # 移除 % 符号
            high_val = float(str(high).strip('%'))
            mid_val = float(str(mid).strip('%'))
            low_val = float(str(low).strip('%'))
            self.send_command(f'MEASUrement:REFLevel:PERCent:HIGH {high_val}')
            self.send_command(f'MEASUrement:REFLevel:PERCent:MID {mid_val}')
            self.send_command(f'MEASUrement:REFLevel:PERCent:LOW {low_val}')
        elif thresholds_mode == 'ABSolute':
            self.send_command('MEASUrement:REFLevel:METHod ABSolute')

        return self.send_command('MEASUrement:REFLevel:METHod?')

    def meas_get_measure(self, measure_type: str = 'FREQ', base_unit: str = '',
                         source1: str = "CHANnel1", source2: str = "CHANnel2"):
        """
        查询指定测量类型的测量值

        Args:
            measure_type: 测量类型 (见 MEASURE_TYPES)
            base_unit: 基础单位 (用于结果缩放)
            source1: 主源
            source2: 次源 (可选)

        Returns:
            测量值 (float)
        """
        tek_type = self.MEASURE_TYPES.get(measure_type, measure_type)
        tek_source1 = self._convert_source_string(source1)

        # 使用立即测量
        self.send_command(f'MEASUrement:IMMed:TYPe {tek_type}')
        self.send_command(f'MEASUrement:IMMed:SOUrce1 {tek_source1}')
        if source2:
            tek_source2 = self._convert_source_string(source2)
            self.send_command(f'MEASUrement:IMMed:SOUrce2 {tek_source2}')

        result = self.send_command('MEASUrement:IMMed:VALue?')
        value = self.change_value_to_scale(result, base_unit)
        return float(value)

    # ===============================================================================
    #                              光标命令
    # ===============================================================================
    def cursor_set_mode(self, mode: str = 'MANual'):
        """设置光标模式"""
        valid_modes = ['OFF', 'MANual', 'WAVeform', 'HBArs', 'VBArs', 'HISTogram']
        if mode.upper() not in valid_modes:
            raise Exception(f"mode 必须是 {valid_modes} 之一")
        self.send_command(f'CURSor:MODe {mode.upper()}')

    def cursor_get_mode(self) -> str:
        """获取光标模式"""
        return self.send_command('CURSor:MODe?')

    def cursor_set_type(self, cursor_type: str = 'TIME'):
        """设置光标类型"""
        self.send_command(f'CURSor:FUNCtion:TYPE {cursor_type}')

    def cursor_set_positions(self, x1: float = None, x2: float = None,
                             y1: float = None, y2: float = None):
        """设置光标位置"""
        if x1 is not None:
            self.send_command(f'CURSor:WAVEform:APOSition {x1}')
        if x2 is not None:
            self.send_command(f'CURSor:WAVEform:BPOSition {x2}')
        if y1 is not None:
            self.send_command(f'CURSor:WAVEform:APOSition {y1}')
        if y2 is not None:
            self.send_command(f'CURSor:WAVEform:BPOSition {y2}')

    def cursor_get_delta_time(self) -> float:
        """获取时间差 (ΔX)"""
        return float(self.send_command('CURSor:WAVEform:DELTA?'))

    def cursor_get_delta_voltage(self) -> float:
        """获取电压差 (ΔY)"""
        return float(self.send_command('CURSor:WAVEform:DELTA?'))

    def cursor_get_delta_freq(self) -> float:
        """获取频率 (1/ΔX)"""
        return float(self.send_command('CURSor:WAVEform:HDELta?'))

    # ===============================================================================
    #                              数学运算命令
    # ===============================================================================
    def math_set_operation(self, math_num: int = 1, operation: str = 'ADD',
                           source1_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                           source1_number: int = 1,
                           source2_type: Union[SourceWaveformType, str] = None,
                           source2_number: int = None):
        """设置数学运算"""
        source1 = self._validate_source_parameters(source1_type, source1_number)
        source2 = self._validate_source_parameters(source2_type, source2_number) if source2_type else None

        self.send_command(f'MATH{math_num}:TYPe {operation}')
        self.send_command(f'MATH{math_num}:IN1 {source1}')
        if source2:
            self.send_command(f'MATH{math_num}:IN2 {source2}')

    def math_set_fft(self, math_num: int = 1, source_type: Union[SourceWaveformType, str] = SourceWaveformType.CH,
                     source_number: int = 1, window: str = 'RECTangular',
                     horizontal_scale: str = 'LINear'):
        """设置 FFT 运算"""
        source = self._validate_source_parameters(source_type, source_number)
        self.send_command(f'MATH{math_num}:TYPe FFT')
        self.send_command(f'MATH{math_num}:IN1 {source}')
        self.send_command(f'MATH{math_num}:FFT:WINDow {window}')
        self.send_command(f'MATH{math_num}:FFT:HSCale {horizontal_scale}')

    def math_set_status(self, math_num: int = 1, status: str = 'ON'):
        """设置数学运算显示状态"""
        self.send_command(f'MATH{math_num}:STATE {status}')

    # ===============================================================================
    #                              显示命令
    # ===============================================================================
    def display_set_persistence(self, mode: Union[str, float] = 'MINimum'):
        """设置显示余辉"""
        if mode in ['MINimum', 'INFinite']:
            self.send_command(f'DISplay:PERsistence {mode}')
        else:
            try:
                time_val = float(mode)
                self.send_command(f'DISplay:PERsistence {time_val}')
            except ValueError:
                raise Exception("mode 必须是 'MINimum'、'INFinite' 或浮点数")

    def display_clear_waveforms(self):
        """清除显示波形"""
        self.send_command('DISplay:CLEar')

    def display_set_grid(self, grid_type: str = 'FULL'):
        """设置网格显示"""
        self.send_command(f'DISplay:GRAticule {grid_type}')

    def display_set_intensity(self, waveform: float = 100, grid: float = 50, text: float = 100):
        """设置显示强度"""
        self.send_command(f'DISplay:INTENsity:WAVEform {waveform}')
        self.send_command(f'DISplay:INTENsity:GRAticule {grid}')
        self.send_command(f'DISplay:INTENsity:TEXT {text}')


class Instrument_Dryrun(OscAgnet):
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
    virtual_osc = OscAgnet('USB0::0x2A8D::0x0101::MY60009053::INSTR')
    virtual_osc.connect()
    pass
    virtual_osc.disconnect()


if __name__ == '__main__':
    main()
