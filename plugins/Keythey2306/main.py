
import logging
import sys
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Union, Optional

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel,
                               QFrame, QComboBox, QSizePolicy, QLineEdit,
                               QCheckBox, QSplitter)
from PySide6.QtCore import Qt, QTimer

from lib.custommath import change_value_to_scale
from lib.deviceCheck import auto_connected, check_error
from lib.qtui.custom_widget import CHANNEL_COLORS, LineWidget, SwitchButton
from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_2306 import Keithley2306Agent, Instrument_Dryrun


class ChannelWidget(QFrame):
    def __init__(self, index: int, device: Keithley2306Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.device = device
        self.logger = logger
        self.black_color = CHANNEL_COLORS[index]
        self.meas_timer = QTimer()
        self.meas_timer.timeout.connect(self.get_meas_value)

        self.setObjectName("ModuleUI")
        self.setStyleSheet("""
            QFrame#ModuleUI {
                background-color: %s;
                padding: 2px 4px;
                border: 1px solid %s;
                border-radius: 5px;
            }
            QLabel {
                color: white;
            }
        """ % (self.black_color, self.black_color))

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

        tittle_widget = QWidget()
        tittle_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(tittle_widget)
        tittle_layout = QHBoxLayout(tittle_widget)
        tittle_layout.setContentsMargins(0, 0, 0, 0)
        tittle_layout.setSpacing(5)
        index_label = QLabel(str(self.index))
        index_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        index_label.setStyleSheet(
            "background-color: %s;border: 1px solid;border-radius: 5px;font-size: 32px;color: black;" % self.black_color
        )
        tittle_layout.addWidget(index_label)
        tittle_layout.addStretch(1)
        view_btn = QPushButton("Main View")
        view_btn.clicked.connect(self.set_to_view)
        tittle_layout.addWidget(view_btn)

        base_view_widget = QWidget()
        base_view_widget.setObjectName("background")
        base_view_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        base_view_widget.setStyleSheet("QWidget#background {background-color: %s;}" % CHANNEL_COLORS[0])
        layout.addWidget(base_view_widget, 1)
        base_view_layout = QHBoxLayout(base_view_widget)
        base_view_layout.setContentsMargins(5, 5, 5, 5)
        base_view_layout.setSpacing(10)

        meas_value_layout = QVBoxLayout()
        meas_value_layout.setContentsMargins(0, 0, 0, 0)
        meas_value_layout.setSpacing(5)
        base_view_layout.addLayout(meas_value_layout, 1)
        meas_vol_layout = QHBoxLayout()
        meas_vol_layout.setContentsMargins(5, 5, 5, 5)
        meas_vol_layout.setSpacing(5)
        meas_value_layout.addLayout(meas_vol_layout)
        self.meas_vol_value = QLineEdit("---.----")
        self.meas_vol_value.setStyleSheet(
            "background-color: %s;border: None;font-size: 32px;color: white;" % CHANNEL_COLORS[0]
        )
        self.meas_vol_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.meas_vol_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.meas_vol_value.setReadOnly(True)
        meas_vol_layout.addWidget(self.meas_vol_value)
        self.meas_vol_unit = QLabel("V")
        self.meas_vol_unit.setStyleSheet("font-size: 32px;")
        self.meas_vol_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        meas_vol_layout.addWidget(self.meas_vol_unit)
        line = LineWidget(color=QColor(self.black_color), margin=5)
        line.setFixedHeight(5)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        meas_value_layout.addWidget(line)
        meas_next_layout = QHBoxLayout()
        meas_next_layout.setContentsMargins(5, 5, 5, 5)
        meas_next_layout.setSpacing(5)
        meas_value_layout.addLayout(meas_next_layout)
        self.meas_cur_value = QLineEdit("---.----")
        self.meas_cur_value.setStyleSheet(
            "background-color: %s;border: None;font-size: 32px;color: white;" % CHANNEL_COLORS[0]
        )
        self.meas_cur_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.meas_cur_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.meas_cur_value.setReadOnly(True)
        meas_next_layout.addWidget(self.meas_cur_value)
        self.meas_cur_unit = QLabel("A")
        self.meas_cur_unit.setStyleSheet("font-size: 32px;")
        self.meas_cur_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        meas_next_layout.addWidget(self.meas_cur_unit)

        line = LineWidget(color=QColor(self.black_color), direction="V", margin=5)
        line.setFixedWidth(5)
        line.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        base_view_layout.addWidget(line)

        setting_layout = QVBoxLayout()
        setting_layout.setContentsMargins(0, 0, 0, 0)
        setting_layout.setSpacing(5)
        base_view_layout.addLayout(setting_layout)

        setting_vol_layout = QHBoxLayout()
        setting_vol_layout.setContentsMargins(0, 0, 0, 0)
        setting_vol_layout.setSpacing(0)
        setting_layout.addLayout(setting_vol_layout)
        self.vol_setting_value = QLineEdit("0.000")
        setting_vol_layout.addWidget(self.vol_setting_value, 1)
        self.vol_setting_unit = QComboBox()
        self.vol_setting_unit.addItems(["V", "mV"])
        setting_vol_layout.addWidget(self.vol_setting_unit)

        setting_cur_layout = QHBoxLayout()
        setting_cur_layout.setContentsMargins(0, 0, 0, 0)
        setting_cur_layout.setSpacing(0)
        setting_layout.addLayout(setting_cur_layout)
        self.cur_limit_value = QLineEdit("0.000")
        setting_cur_layout.addWidget(self.cur_limit_value, 1)
        self.cur_limit_unit = QComboBox()
        self.cur_limit_unit.addItems(["A", "mA", "uA"])
        setting_cur_layout.addWidget(self.cur_limit_unit)

        setting_apply_btn = QPushButton("Apply")
        setting_apply_btn.clicked.connect(self.apply_setting)
        setting_layout.addWidget(setting_apply_btn)

        setting_state_layout = QHBoxLayout()
        setting_state_layout.setContentsMargins(0, 0, 0, 0)
        setting_state_layout.setSpacing(5)
        setting_layout.addLayout(setting_state_layout)
        setting_state_layout.addWidget(QLabel("Output Sate"), alignment=Qt.AlignmentFlag.AlignRight)
        switch_btn = SwitchButton()
        switch_btn.clicked.connect(self.output_channel)
        setting_state_layout.addWidget(switch_btn, 1)

    def update_device(self, device):
        self.device = device

    @check_error
    def apply_setting(self):
        vol_value = float(self.vol_setting_value.text())
        vol_unit = self.vol_setting_unit.currentText()
        vol = change_value_to_scale(vol_value, vol_unit)
        cur_value = float(self.cur_limit_value.text())
        cur_unit = self.cur_limit_unit.currentText()
        cur = change_value_to_scale(cur_value, cur_unit)

        self.device.set_ch_voltage(self.index, voltage=vol)
        self.device.set_ch_current(self.index, current=cur)
        self.meas_vol_unit.setText(vol_unit)
        self.meas_cur_unit.setText(cur_unit)

    @check_error
    def output_channel(self, state: bool):
        self.device.set_ch_output_state(self.index, state=state)
        if state:
            self.meas_timer.start(300)
        else:
            self.meas_timer.stop()
            self.meas_vol_value.setText("---.----")
            self.meas_cur_value.setText("---.----")

    @check_error
    def set_to_view(self):
        self.device.set_ch_to_view(self.index)

    @check_error
    def get_meas_value(self):
        vol_unit = self.meas_vol_unit.text()
        cur_unit = self.meas_cur_unit.text()
        vol_value = self.device.measure_ch_voltage(self.index, vol_unit)
        cur_value = self.device.measure_ch_current(self.index, cur_unit)
        self.meas_vol_value.setText("%7f" % vol_value)
        self.meas_cur_value.setText("%7f" % cur_value)


class MainWindow(QMainWindow):
    def __init__(
            self, name: str, version: str = '1.0.0', logger: Logger = None, dry_run=False,
            data_path: Union[PathLike[str], str, None] = None, *args, **kwargs
    ):
        super().__init__()
        self.widget_name = name
        self.dryrun = dry_run
        self.logger = logger
        self.data_path = Path.cwd()
        if data_path:
            self.data_path = Path(data_path)
        if not self.data_path.exists():
            self.data_path.mkdir()
        if not self.logger:
            log_path = self.data_path / "script_log"
            if not log_path.exists():
                log_path.mkdir()
            self.logger = create_logger(name=name, level=logging.DEBUG, log_path=log_path)
        self.logger.info(f"{name} logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")
        self.pic_dir = self.data_path / "pictures"
        if not self.pic_dir.exists():
            self.pic_dir.mkdir()
        self.devices_scan_list = get_device_patterns("2306")
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[Keithley2306Agent] = None
        self.connected = False

        self.setWindowTitle(f"B29xx系列直流电源分析仪控制器V{version}")
        self.resize(800, 600)

        main_widget = QFrame()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        scan_frame = QFrame()
        scan_frame.setMinimumWidth(400)
        main_layout.addWidget(scan_frame)
        scan_layout = QHBoxLayout()
        scan_layout.setContentsMargins(5, 5, 5, 5)
        scan_frame.setLayout(scan_layout)
        self.devices_box = QComboBox()
        self.devices_box.setEditable(False)
        self.devices_box.currentTextChanged.connect(self.choose_devices_list)
        scan_layout.addWidget(self.devices_box, 1)
        self.refresh_devices_list()
        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.device_sate_change)
        scan_layout.addWidget(self.btn_connect)
        self.dryrun_box = QCheckBox("dryrun")
        self.dryrun_box.setChecked(dry_run)
        self.dryrun_box.stateChanged.connect(self.switch_dryrun)
        scan_layout.addWidget(self.dryrun_box)
        scan_layout.addStretch(1)
        view_layout = QHBoxLayout()
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.setSpacing(0)
        scan_layout.addLayout(view_layout)
        view_layout.addWidget(QLabel("窗口"))
        self.view_box = QComboBox()
        self.view_box.setEditable(False)
        self.view_box.addItems(['1', '2', "ON", "OFF"])
        view_layout.addWidget(self.view_box)
        view_btn = QPushButton("应用")
        view_btn.clicked.connect(self.device_change_view)
        view_layout.addWidget(view_btn)

        splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(splitter, 1)

        self.left_panel = ChannelWidget(index=1, device=self.device, logger=self.logger)
        self.right_panel = ChannelWidget(index=2, device=self.device, logger=self.logger)

        splitter.addWidget(self.left_panel)
        splitter.addWidget(self.right_panel)

    def deleteLater(self, /):
        if self.device or self.connected:
            self.logger.info(f"设备未断开，将自动断开连接")
            self.device.disconnect()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        if self.device or self.connected:
            self.logger.info(f"设备未断开，将自动断开连接")
            self.device.disconnect()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()

    def choose_devices_list(self):
        self.devices_box.blockSignals(True)
        current_text = self.devices_box.currentText()
        if current_text and current_text != "刷新列表":
            info = current_text.split(": ")
            self.name = info[0]
            self.sn = info[1]
            self.logger.info(f"用户选择了{info}")
        else:
            self.refresh_devices_list()
        self.devices_box.blockSignals(False)

    def refresh_devices_list(self):
        if self.device and self.connected:
            self.disconnect_device()
        self.logger.info(f"刷新列表")
        self.devices_list = {}
        self.devices_box.clear()
        devices = get_device_list()
        sn_list = [""]
        for index, address in enumerate(devices):
            ok, class_name, sn = check_device_module(address, self.devices_scan_list)
            self.logger.debug(f"{index}.{sn}: {class_name}")
            if ok:
                sn_list.append(class_name + ": " + sn)
                self.devices_list[sn] = address
                self.logger.debug(f"{class_name}为所需仪器，加入列表")
        self.logger.info(f"当前识别到了{len(sn_list)-1}个仪器")
        if self.dryrun:
            sn_list.append("KeysightTechnologiesN6705C(demo): MY114514")
            self.devices_list["MY114514"] = "USB0::0x2A8D::0x0F02::MY11551419::INSTR"
        sn_list.append("刷新列表")
        self.devices_box.addItems(sn_list)
        self.devices_box.setCurrentText("")
        self.sn = ""

    def switch_dryrun(self):
        self.dryrun = not self.dryrun
        self.refresh_devices_list()

    def device_sate_change(self):
        if not self.connected:
            self.logger.info(f"连接设备:{self.name} {self.sn}")
            self.connect_device()
        else:
            self.logger.info(f"断开设备:{self.name} {self.sn}")
            self.disconnect_device()

    @check_error
    def connect_device(self):
        if not self.sn:
            raise Exception("请先选择设备")
        if self.dryrun and "demo" in self.name:
            self.device = Instrument_Dryrun(instrument_address=self.devices_list[self.sn], logger=self.logger)
        else:
            self.device = Keithley2306Agent(instrument_address=self.devices_list[self.sn], logger=self.logger)
        self.device.connect(reset=True)
        self.btn_connect.setText("Disconnect")
        self.devices_box.setEnabled(False)
        self.connected = True
        self.left_panel.update_device(self.device)
        self.right_panel.update_device(self.device)

    @check_error
    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.devices_box.setEnabled(True)
            self.device = None
            self.connected = False
            self.left_panel.update_device(self.device)
            self.right_panel.update_device(self.device)

    @auto_connected
    def device_change_view(self, mode):
        self.device.set_ch_to_view(mode)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="2306", version="0.0.1", logger=None, dry_run=True)
    window.show()
    sys.exit(app.exec())
