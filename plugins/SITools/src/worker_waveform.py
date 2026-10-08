
from pathlib import Path
from typing import Optional, Union

from PySide6.QtCore import Signal, QEventLoop, Qt, QObject

from lib.instruments.instrument_osc import InfiniiumCatAOsc, OscAgnet
from lib.uartSerial.SerialAgent import UARTSerial
from lib.deviceCheck import check_error

from .setting import SetupData


class build_waveform_catch(QObject):
    needUserConfirmation = Signal(str, str)
    confirmationResult = Signal(bool)
    finish_signal = Signal(str, bool, str)  # type, bool, msg

    def __init__(self, parent, config: SetupData, osc_device: Optional[Union[OscAgnet, InfiniiumCatAOsc]], unit_serial: Optional[UARTSerial], data_folder: Path):
        super().__init__(parent)
        self.user_choice = None

        self.config = config
        self.osc_device = osc_device
        self.unit_serial = unit_serial
        self.data_folder = data_folder
        # 示波器配置参数
        self.vertical = self.config.Analysis.Configuration.get("voltage")
        self.osc_setting = self.config.Oscilloscope
        # 串口信息
        self.serial_en = self.config.Uart.EN
        self.init_commands = self.config.Uart.InitCommand
        self.trigger_commands = self.config.Uart.TriggerCommand

    @check_error
    def run(self):
        # 示波器初始化
        self.osc_device.connect(reset=True)
        self.osc_device.source_set_status(source_type="channel", source_number=1, status="OFF")
        horizon = self.osc_setting.Horizon.Range
        position = self.osc_setting.Horizon.Position
        # pionts = self.osc_setting.Horizon.Position
        self.osc_device.horizon_set_time_base_scale(horizon, scale_suffix="ms")
        self.osc_device.horizon_set_time_base_delay(position, delay_suffix="ms")
        for channel, ch_setting in self.osc_setting.Channel.items():
            if ch_setting.EN:
                self.osc_device.source_set_status(source_type="channel", source_number=channel, status="ON")
                self.osc_device.source_set_label(source_type="channel", source_number=channel, label=ch_setting.Label)
                self.osc_device.source_set_vertical(source_type="channel", source_number=channel, vertical_value=self.vertical*2)
                self.osc_device.source_set_offset(source_type="channel", source_number=channel, offset_value=self.vertical/2)
        if self.osc_setting.Trigger.Edge == "rising":
            slope = "POSitive"
        else:
            slope = "NEGative"
        self.osc_device.trigger_set_edge_option(source_type="channel", source_number=self.osc_setting.Trigger.Channel, slope=slope, level=self.vertical/2)

        # 初始化串口
        if self.unit_serial:
            self.unit_serial.connect()
            for cmd in self.init_commands.split("\n"):
                self.unit_serial.send_with_response(cmd.strip())

        self.osc_device.run_ctl_press_single()

        if self.unit_serial:
            for cmd in self.trigger_commands.split("\n"):
                self.unit_serial.send_with_response(cmd.strip())
        else:
            loop = QEventLoop()
            self.user_choice = None  # 用于存储用户选择

            def handleUserChoice(choice):
                self.user_choice = choice
                loop.quit()

            self.confirmationResult.connect(handleUserChoice, Qt.ConnectionType.UniqueConnection)

            self.needUserConfirmation.emit("确认", "等待用户手动抓取波形\nWaiting for the user to manually capture the waveform")
            loop.exec()
            if not self.user_choice:
                self.osc_device.run_ctl_press_stop()
                self.finish_signal.emit("OSC", False, "The user cancels the execution")
                raise Exception("The user cancels the execution")

        for channel, ch_setting in self.osc_setting.Channel.items():
            if ch_setting.EN:
                self.osc_device.file_save_channel_waveform_to_csv(
                    save_dir=self.data_folder,
                    source_type="channel",
                    source_number=channel,
                    num_points=self.osc_setting.Horizon.Points,
                    csv_name=f"{ch_setting.Net}_{channel}_waveform.csv"
                )

        self.finish_signal.emit("OSC", True, "OSC waveform catch finished.")
