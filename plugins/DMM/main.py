import csv
import logging
import re
import sys
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from logging import Logger
from os import PathLike
from pathlib import Path
from threading import Lock
from typing import Any, Optional, Union

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QDoubleValidator
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSizePolicy,
    QSpinBox, QStackedWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from lib.deviceCheck import auto_connected
from lib.customlog import create_logger
from lib.custommath import (
    get_scale_for_units, change_str_value_to_scale, set_value_to_scale_str
)
from lib.instruments.instrument import Base_Unit, check_device_module, get_device_list
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_dmm import DmmAgent, Instrument_Dryrun, MeasurementConfig, unit_from_range_or_function
from lib.qtui.custom_widget import show_toast

FUNCTION_MAP = {
    "直流电压": "VOLT:DC",
    "直流电流": "CURR:DC",
    "交流电压": "VOLT:AC",
    "交流电流": "CURR:AC",
    "两线电阻": "RES",
    "四线电阻": "FRES",
    "频率": "FREQ",
    "周期": "PER",
    "容值": "CAP",
    "通断测试": "CONT",
    "体二极值": "DIOD",
    "温度": "TEMP",
}
RANGE_LIST_MAP = {
    "直流电压": ["Auto", "100mV", "1V", "10V", "100V", "1000V"],
    "直流电流": ["Auto", "1uA", "10uA", "100uA", "1mA", "10mA", "100mA", "1A", "3A", "10A"],
    "交流电压": ["Auto", "100mV", "1V", "10V", "100V", "750V"],
    "交流电流": ["Auto", "100uA", "1mA", "10mA", "100mA", "1A", "3A"],
    "两线电阻": ["Auto", "100Ω", "1KΩ", "10KΩ", "100KΩ", "1MΩ", "10MΩ", "100MΩ", "1GΩ"],
    "四线电阻": ["Auto", "100Ω", "1KΩ", "10KΩ", "100KΩ", "1MΩ", "10MΩ", "100MΩ", "1GΩ"],
    "容值": ["Auto", "1nF", "10nF", "100nF", "1uF", "10uF", "100uF"],
    "频率": ["Auto", "100mV", "1V", "10V", "100V", "750V"],
    "周期": ["Auto", "100mV", "1V", "10V", "100V", "750V"],
    "通断测试": ["on", "off"],
    "体二极值": ["on", "off"],
    "温度": ["℃", "℉", "K"],
}
NPLC_EN_LIST = ["直流电压", "直流电流", "两线电阻", "四线电阻", "温度"]
NPLC_PRESETS = ["0.001", "0.002", "0.006", "0.02", "0.06", "0.2", "1", "10", "100"]
MAX_POWER_POINTS = 1_000_000


def _format_float(value: float) -> str:
    return f"{value:.6f}"


def _measurement_btn_style() -> str:
    return """
        QPushButton {
            background-color: #f5f5f5;
            padding: 8px 8px;
            border: 1px solid rgba(0, 123, 255, 0.5);
            border-radius: 4px;
            font-size: 12px;
        }
        QPushButton:hover { background-color: #1e8449; }
        QPushButton:disabled { background-color: #bdc3c7; }
    """


def _make_stat_line(default_text: str) -> QLineEdit:
    line = QLineEdit(default_text)
    line.setMinimumWidth(50)
    line.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    line.setReadOnly(True)
    return line


class OnlineStats:
    """O(1)在线统计，避免每次全量 statistics.mean/stdev。"""

    def __init__(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min_val: Optional[float] = None
        self.max_val: Optional[float] = None

    def clear(self) -> None:
        self.count = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.min_val = None
        self.max_val = None

    def add(self, value: float) -> None:
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2
        self.min_val = value if self.min_val is None else min(self.min_val, value)
        self.max_val = value if self.max_val is None else max(self.max_val, value)

    @property
    def std(self) -> float:
        if self.count <= 1:
            return 0.0
        return (self.m2 / (self.count - 1)) ** 0.5


class DMMSampleReadWorker(QThread):
    """单个DMM连续采样线程"""
    valueReady = Signal(list)
    error = Signal(str)
    stopped = Signal(str)

    def __init__(
            self, parent, device: DmmAgent,
            count: int = 1, delay_ms: float = 0, spacing_ms: float = 0, sample: int = 1,
            unit: str = ""
    ):
        super().__init__(parent)
        self.device = device
        self.count = max(1, int(count))
        self.delay_ms = max(0.0, float(delay_ms))
        self.spacing_ms = max(0.0, float(spacing_ms))
        self.sample = max(1, int(sample))
        self.unit = unit

    def stop(self) -> None:
        self.device.stop_action()
        self.stopped.emit("采样已停止")

    def run(self) -> None:
        try:
            values = self.device.read_multiple(
                count=self.count,
                delay_ms=self.delay_ms,
                space_ms=self.spacing_ms,
                sample=self.sample,
                unit=self.unit
            )
            self.valueReady.emit(values)
            self.stopped.emit("采样已停止")
        except Exception as e:
            self.error.emit(str(e))


class DMMInstrumentUI(QFrame):
    parameterChanged = Signal(dict)

    def __init__(
            self,
            index: int,
            devices_scan_list: list,
            pic_ptah: Path,
            logger: logging.Logger,
            dry_run: bool = False,
    ):
        super().__init__()
        self.devices_scan_list = devices_scan_list
        self.pic_ptah = pic_ptah
        self.logger = logger
        self.dryrun = dry_run
        self.measurement_active = False
        self.data_records: list[dict[str, Any]] = []
        self.stats = OnlineStats()
        self.index = index
        self.sn = ""
        self.name = ""
        self.device: Optional[DmmAgent] = None
        self.connected = False
        self.func = "直流电压"
        self.unit = "V"
        self.dmm_devices_list: dict[str, str] = {}
        self._cleaned = False
        self.config = MeasurementConfig()
        self._last_config = MeasurementConfig()
        self.sample_read_worker: Optional[DMMSampleReadWorker] = None
        self.config_busy = False

        self.setAutoFillBackground(True)
        self.palette = self.palette()
        self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
        self.setPalette(self.palette)
        self.setMinimumWidth(450)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(2)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        scan_frame = QFrame()
        scan_frame.setMinimumWidth(400)
        layout.addWidget(scan_frame)
        scan_layout = QHBoxLayout(scan_frame)
        scan_layout.setContentsMargins(5, 5, 5, 5)

        self.dmm_devices = QComboBox()
        self.dmm_devices.setEditable(False)
        self.dmm_devices.currentTextChanged.connect(self.choose_devices_list)
        scan_layout.addWidget(self.dmm_devices, 1)

        self.btn_connect = QPushButton("连接")
        self.btn_connect.clicked.connect(self.device_sate_change)
        scan_layout.addWidget(self.btn_connect)

        self.dryrun_box = QCheckBox("dryrun")
        self.dryrun_box.setChecked(dry_run)
        self.dryrun_box.stateChanged.connect(self.switch_dryrun)
        scan_layout.addWidget(self.dryrun_box)

        save_pic_btn = QPushButton("界面截图")
        save_pic_btn.clicked.connect(self.device_save_pic)
        scan_layout.addWidget(save_pic_btn)

        self.config_frame = QFrame()
        self.config_frame.setMinimumWidth(400)
        self.config_frame.setFrameStyle(QFrame.Shape.Box)
        self.config_frame.setLineWidth(1)
        layout.addWidget(self.config_frame, 1)
        config_base_layout = QVBoxLayout(self.config_frame)
        config_base_layout.setContentsMargins(5, 5, 5, 5)
        config_base_layout.setSpacing(10)

        config_layout = QHBoxLayout()
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setSpacing(5)
        config_base_layout.addLayout(config_layout)

        config_setting_layout = QVBoxLayout()
        config_setting_layout.setContentsMargins(0, 0, 0, 0)
        config_setting_layout.setSpacing(5)
        config_layout.addLayout(config_setting_layout)

        self.btn_single = QPushButton("单次测量")
        self.btn_single.setStyleSheet(_measurement_btn_style())
        self.btn_single.clicked.connect(self.measure_single)
        config_layout.addWidget(self.btn_single)

        func_row = QHBoxLayout()
        func_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        func_row.setContentsMargins(0, 0, 0, 0)
        func_row.setSpacing(5)
        config_setting_layout.addLayout(func_row)
        func_row.addWidget(QLabel("功能:"))
        self.func_mode = QComboBox()
        self.func_mode.addItems(list(FUNCTION_MAP.keys()))
        self.func_mode.currentTextChanged.connect(self.update_func_ui)
        func_row.addWidget(self.func_mode, 2)
        func_row.addStretch(1)
        func_row.addWidget(QLabel("量程:"))
        self.func_range = QComboBox()
        self.func_range.addItems(RANGE_LIST_MAP["直流电压"])
        self.func_range.currentTextChanged.connect(self.update_unit_ui)
        func_row.addWidget(self.func_range, 2)

        plc_row = QHBoxLayout()
        plc_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        plc_row.setContentsMargins(0, 0, 0, 0)
        plc_row.setSpacing(5)
        config_setting_layout.addLayout(plc_row)
        plc_row.addWidget(QLabel("周期帧:"))
        self.apt_mode = QComboBox()
        self.apt_mode.addItems(["NPLC", "Time(ms)"])
        self.apt_mode.currentTextChanged.connect(self.update_apt_ui)
        plc_row.addWidget(self.apt_mode)
        self.apt_value = QComboBox()
        self.apt_value.addItems(NPLC_PRESETS)
        self.apt_value.setCurrentIndex(6)
        self.apt_value.currentTextChanged.connect(self.update_config_apt)
        plc_row.addWidget(self.apt_value, 1)
        plc_row.addStretch(1)
        self.btn_apply_config = QPushButton("应用")
        self.btn_apply_config.clicked.connect(self.apply_config)
        plc_row.addWidget(self.btn_apply_config)
        self.btn_reset_config = QPushButton("重置")
        self.btn_reset_config.clicked.connect(self.reset_config)
        plc_row.addWidget(self.btn_reset_config)

        interval_frame = QFrame()
        interval_frame.setFrameStyle(QFrame.Shape.Box)
        interval_frame.setLineWidth(1)
        config_base_layout.addWidget(interval_frame)
        interval_row = QHBoxLayout(interval_frame)
        interval_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
        interval_row.setContentsMargins(2, 2, 2, 2)

        interval_setting_row = QVBoxLayout()
        interval_setting_row.setContentsMargins(0, 0, 0, 0)
        interval_setting_row.setSpacing(0)
        interval_row.addLayout(interval_setting_row)

        self.btn_continue = QPushButton("持续采样")
        self.btn_continue.setStyleSheet(_measurement_btn_style())
        self.btn_continue.clicked.connect(self.measure_continue)
        interval_row.addWidget(self.btn_continue)

        interval_setting_row1 = QHBoxLayout()
        interval_setting_row1.setAlignment(Qt.AlignmentFlag.AlignLeft)
        interval_setting_row1.setContentsMargins(0, 0, 0, 0)
        interval_setting_row1.setSpacing(5)
        interval_setting_row.addLayout(interval_setting_row1)

        interval_setting_row1.addWidget(QLabel("连续采样"))
        self.interval_count = QSpinBox(minimum=1, maximum=1_000_000_000)
        self.interval_count.setMinimumWidth(20)
        self.interval_count.setValue(1)
        interval_setting_row1.addWidget(self.interval_count)
        interval_setting_row1.addWidget(QLabel("次"))
        interval_setting_row1.addStretch(1)
        interval_setting_row1.addWidget(QLabel("每轮延迟(ms):"))
        self.interval_delay = QDoubleSpinBox(minimum=0, maximum=3_600_000)
        self.interval_delay.setDecimals(4)
        self.interval_delay.setMinimumWidth(30)
        self.interval_delay.setValue(1000)
        self.interval_delay.setSingleStep(0.001)
        interval_setting_row1.addWidget(self.interval_delay)

        interval_setting_row2 = QHBoxLayout()
        interval_setting_row2.setAlignment(Qt.AlignmentFlag.AlignLeft)
        interval_setting_row2.setContentsMargins(0, 0, 0, 0)
        interval_setting_row2.setSpacing(5)
        interval_setting_row.addLayout(interval_setting_row2)

        interval_setting_row2.addWidget(QLabel("每轮采样"))
        self.interval_sample = QSpinBox(minimum=1, maximum=1_000_000_000)
        self.interval_sample.setMinimumWidth(20)
        self.interval_sample.setValue(1)
        interval_setting_row2.addWidget(self.interval_sample)
        interval_setting_row2.addWidget(QLabel("点"))
        interval_setting_row2.addStretch(1)
        interval_setting_row2.addWidget(QLabel("采点间隔(ms):"))
        self.interval_spin = QDoubleSpinBox(minimum=0.0405, maximum=3_600_000)
        self.interval_spin.setDecimals(4)
        self.interval_spin.setMinimumWidth(30)
        self.interval_spin.setValue(0.0405)
        self.interval_spin.setSingleStep(0.001)
        interval_setting_row2.addWidget(self.interval_spin)

        measure_frame = QFrame()
        measure_frame.setFrameStyle(QFrame.Shape.Box)
        measure_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        measure_frame.setLineWidth(1)
        layout.addWidget(measure_frame, 1)
        measure_layout = QVBoxLayout(measure_frame)
        measure_layout.setContentsMargins(5, 5, 5, 5)
        measure_layout.setSpacing(5)

        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(5)
        measure_layout.addLayout(value_row)

        self.lbl_value = QLineEdit("---.------")
        self.lbl_value.setStyleSheet(
            """
            font-size: 50px;
            font-family: 'Courier New', monospace;
            color: #2C3E50;
            font-weight: bold;
            padding: 3px;
            border-radius: 5px;
            """
        )
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl_value.setReadOnly(True)
        value_row.addWidget(self.lbl_value, 1)
        self.lbl_unit = QLabel("V")
        self.lbl_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.lbl_unit.setStyleSheet("font-size: 28px; color: #7F8C8D;")
        value_row.addWidget(self.lbl_unit)
        btn_frame = QFrame()
        value_row.addWidget(btn_frame)
        btn_layout = QVBoxLayout(btn_frame)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(5)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_frame = QFrame()
        measure_layout.addWidget(title_frame, 1)
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for title in ["平均值", "标准差", "最小值", "最大值", "数据量"]:
            label = QLabel(title)
            label.setMinimumWidth(50)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            title_layout.addWidget(label, 1)
        self.btn_clear = QPushButton("清除数据")
        self.btn_clear.clicked.connect(self.clear_data)
        title_layout.addWidget(self.btn_clear)

        value_stats_frame = QFrame()
        measure_layout.addWidget(value_stats_frame, 1)
        stats_layout = QHBoxLayout(value_stats_frame)
        stats_layout.setContentsMargins(0, 0, 0, 0)
        stats_layout.setSpacing(5)
        stats_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.avg_value = _make_stat_line("---.---")
        self.std_value = _make_stat_line("---.---")
        self.min_value = _make_stat_line("---.---")
        self.max_value = _make_stat_line("---.---")
        self.count_value = _make_stat_line("------")
        for widget in [self.avg_value, self.std_value, self.min_value, self.max_value, self.count_value]:
            stats_layout.addWidget(widget, 1)
        self.btn_save = QPushButton("保存数据")
        self.btn_save.clicked.connect(self.save_data)
        self.btn_save.setEnabled(False)
        stats_layout.addWidget(self.btn_save)

        self.refresh_devices_list()
        self.logger.info(f"插件{self.index}初始化完成")

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleaned = True
        try:
            self.stop_continuous_measurement(wait_ms=1500)
            if self.device and self.connected:
                self.logger.info(f"[DMM{self.index}]{self.name}({self.sn})设备未断开，将自动断开连接")
                self.device.disconnect()
                self.connected = False
                self.device = None
        except Exception as e:
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
        finally:
            self.logger.info(f"插件{self.index}关闭")

    def closeEvent(self, event):
        self.cleanup()
        event.accept()

    def choose_devices_list(self):
        current_text = self.dmm_devices.currentText()
        if current_text == "刷新列表":
            self.refresh_devices_list()
            return
        if current_text and ": " in current_text:
            info = current_text.split(": ", 1)
            self.name = info[0]
            self.sn = info[1]
            self.logger.info(f"插件{self.index}用户选择了{info}")
            return
        self.sn = ""
        self.name = ""
        self.logger.debug(f"插件{self.index}选择了无效选项: {current_text}")

    def refresh_devices_list(self):
        if self.device and self.connected:
            self.disconnect_device()
        self.logger.info(f"插件{self.index}开始刷新列表")
        self.dmm_devices_list = {}
        self.dmm_devices.blockSignals(True)
        self.dmm_devices.clear()
        try:
            devices = get_device_list()
        except Exception as e:
            devices = []
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
            QMessageBox.warning(self, "错误", "刷新仪器列表失败，请检查 VISA/USB 连接")

        sn_list = [""]
        for index, address in enumerate(devices):
            ok, class_name, sn = check_device_module(address, self.devices_scan_list)
            self.logger.debug(f"{index}.{sn}: {class_name}")
            if ok:
                sn_list.append(class_name + ": " + sn)
                self.dmm_devices_list[sn] = address
                self.logger.debug(f"{class_name}为所需仪器，加入列表")
        self.logger.info(f"当前识别到了{len(sn_list) - 1}个仪器")
        if self.dryrun:
            demo_sn = f"MY114514{self.index}"
            sn_list.append(f"KeysightTechnologies34465A(demo): {demo_sn}")
            self.dmm_devices_list[demo_sn] = f"USB0::0x2A8D::0x0101::{demo_sn}:INSTR"
        sn_list.append("刷新列表")
        self.dmm_devices.addItems(sn_list)
        self.dmm_devices.setCurrentText("")
        self.dmm_devices.blockSignals(False)
        self.sn = ""
        self.name = ""

    def switch_dryrun(self):
        self.dryrun = self.dryrun_box.isChecked()
        self.refresh_devices_list()

    def device_sate_change(self):
        if not self.connected:
            self.logger.info(f"连接设备:{self.name} {self.sn}")
            self.connect_device()
        else:
            self.logger.info(f"断开设备:{self.name} {self.sn}")
            self.disconnect_device()

    @auto_connected
    def device_save_pic(self):
        try:
            if self.dryrun and "demo" in self.name:
                with open(Path(__file__).parent / "logo.png", "rb") as img_file:
                    img_data = img_file.read()
                file_name, _ = QFileDialog.getSaveFileName(
                    self, "选择文件", self.pic_ptah.as_posix(), "图片格式 (*.png)"
                )
                if not file_name:
                    return
                if not file_name.endswith(".png"):
                    file_name += ".png"
            else:
                self.logger.info("正在截取屏幕")
                img_data = self.device.get_screen_image()
                file_name, _ = QFileDialog.getSaveFileName(
                    self, "选择文件", self.pic_ptah.as_posix(), "图片格式 (*.bmp)"
                )
                if not file_name:
                    return
                if not file_name.endswith(".bmp"):
                    file_name += ".bmp"
            with open(file_name, "wb") as pic_file:
                pic_file.write(img_data)
            self.logger.info(f"保存截图到: {file_name}")
            show_toast(self, f"截图已保存至:\n{file_name}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(self, "错误", f"截图保存失败: {e}")

    def connect_device(self):
        if not self.sn:
            QMessageBox.warning(self, "提示", "请先选择DMM设备")
            return
        try:
            if "demo" in self.name:
                self.logger.info("enter DEMO device.")
                self.device = Instrument_Dryrun(self.dmm_devices_list[self.sn], logger=self.logger)
            else:
                self.device = DmmAgent(self.dmm_devices_list[self.sn], logger=self.logger)
            self.device.connect()
            self.btn_connect.setText("断开")
            self.dmm_devices.setEnabled(False)
            self.palette.setColor(self.backgroundRole(), QColor("#B1D85C"))
            self.setPalette(self.palette)
            self.connected = True
            config = self.device.get_measurement_info()
            self.config = MeasurementConfig(**config)
            self.update_config_to_ui()
            self._last_config = None
            self.parameterChanged.emit({"index": self.index, "info": "连接"})
        except Exception as e:
            self.connected = False
            self.device = None
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "连接失败", str(e))

    def disconnect_device(self):
        if self.device and self.connected:
            try:
                self.device.disconnect()
                self.device = None
                self.connected = False
            except Exception as e:
                QMessageBox.critical(self, "断开失败", str(e))
                self.logger.error(traceback.format_exc())
                return
            self.btn_connect.setText("连接")
            self.dmm_devices.setEnabled(True)
            self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
            self.setPalette(self.palette)
            self.parameterChanged.emit({"index": self.index, "info": "断开"})

    def update_func_ui(self, current_text):
        # current_text = self.func_mode.currentText()
        self.func = current_text
        self.config.function = FUNCTION_MAP[self.func]
        self.logger.info(f"user change func mode to {current_text} [ {self.config.function} ]")
        self.func_range.clear()
        self.func_range.addItems(RANGE_LIST_MAP[current_text])
        self.func_range.setCurrentIndex(0)

    def update_unit_ui(self, range_str):
        # range_str = self.func_range.currentText()
        self.clear_data()
        range_value = re.sub(r'[^-+\d.]+', '', range_str)
        if self.func in ["通断测试", "体二极值"]:
            self.config.manual_range = range_str
        elif self.func in ["温度"]:
            data = {
                "℃": "C",
                "℉": "F",
                "K": "K",
            }
            self.config.manual_range = data.get(range_str)
        elif range_value == "":
            self.config.auto_range = True
        else:
            self.config.auto_range = False
            self.config.manual_range = change_str_value_to_scale(range_str)
        self.unit = unit_from_range_or_function(self.config.function, range_str)
        self.lbl_unit.setText(self.unit)

    def update_apt_ui(self, current_text):
        # current_text = self.apt_mode.currentText()
        self.logger.info(f"user change apt mode to {current_text}")
        self.apt_value.clear()
        if current_text == "NPLC":
            self.apt_value.setEditable(False)
            self.apt_value.setValidator(QDoubleValidator(bottom=0.001, top=100.0, decimals=3))
            self.apt_value.setMaxVisibleItems(10)
            self.apt_value.addItems(NPLC_PRESETS)
            self.apt_value.setCurrentIndex(6)
        else:
            self.apt_value.setEditable(True)
            self.apt_value.setCurrentText("100.000")
            self.apt_value.setValidator(QDoubleValidator(bottom=0.02, top=1000.0, decimals=3))
        self.config.aperture_mode = current_text

    def update_config_apt(self, current_text):
        # current_text = self.apt_value.currentText()
        self.logger.info(f"user change apt value to {current_text}")
        self.config.aperture_value = round(float(current_text), 9)

    @auto_connected
    def apply_config(self):
        """应用DMM基础配置。"""
        self.logger.info("pending apply the user config")
        if self.measurement_active:
            QMessageBox.warning(self, "提示", f"[DMM{self.index}]{self.name}({self.sn})正在采样，停止后再修改配置")
            return
        try:
            if self.config == self._last_config:
                self.parameterChanged.emit({"index": self.index, "info": "更新配置"})
                self.logger.info(f"[DMM{self.index}]{self.name}({self.sn}): 配置未变化，跳过重复SCPI下发")
                show_toast(self.config_frame, f"[DMM{self.index}]{self.name}({self.sn})配置未变化", color="yellow")
                return

            self.device.stop_action()

            self.device.set_measurement_function(self.config.function)

            if self.func in ["通断测试", "体二极值"]:
                self.device.send_command(f"SYSTem:BEEPer:STATe {self.config.manual_range}")
            elif self.func == "温度":
                self.device.send_command(f"UNIT:TEMPerature {self.config.manual_range}")
            else:
                if self.config.auto_range:
                    self.device.set_range("Auto")
                else:
                    self.device.set_range(self.config.manual_range)

            if self.func in NPLC_EN_LIST:
                self.device.set_aperture(self.config.aperture_mode, self.config.aperture_value)

            self._last_config = MeasurementConfig(**self.device.get_measurement_info())
            show_toast(self.config_frame, "应用成功", color="green")
            self.parameterChanged.emit({"index": self.index, "info": "更新配置"})
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "配置失败", f"[DMM{self.index}]{self.name}({self.sn}): 保存错误,{e}")

    @auto_connected
    def reset_config(self):
        self.logger.info("pending reset to default config")
        if self.measurement_active:
            QMessageBox.warning(self, "提示", "当前DMM正在采样，停止后再重置")
            return
        try:
            self.device.reset()
            self.config = MeasurementConfig(**self.device.get_measurement_info())
            self.update_config_to_ui()
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "重置失败", f"[DMM{self.index}]{self.name}({self.sn}): 保存错误,{e}")

    def update_config_to_ui(self):
        self.func_mode.setCurrentText(self.config.function)
        if self.config.auto_range:
            self.func_range.setCurrentText("Auto")
        else:
            range_value = self.config.manual_range
            range_str = set_value_to_scale_str(range_value)
            self.unit = unit_from_range_or_function(self.config.function, range_str)
            self.func_range.setCurrentText(range_str)
        self.apt_mode.setCurrentText(self.config.aperture_mode)
        self.apt_value.setCurrentText(str(self.config.aperture_value))
        self.interval_count.setValue(self.config.sample)
        self.interval_delay.setValue(self.config.trigger_delay)
        self.interval_spin.setValue(self.config.sample_spin)
        self.interval_sample.setValue(self.config.sample_count)
        self.lbl_unit.setText(self.unit)

    def clear_data(self):
        self.data_records = []
        self.stats.clear()
        self._update_stats()
        self.btn_save.setEnabled(False)

    def save_data(self):
        if not self.data_records:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存数据", "", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            if not path.endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as save_file:
                writer = csv.writer(save_file)
                writer.writerow(["Info", "SN", "Function"])
                writer.writerow([self.name, self.sn, self.func])
                writer.writerow(["Timestamp", "value", "Unit"])
                for record in self.data_records:
                    writer.writerow([
                        record["timestamp"].strftime("%Y-%m-%d %H:%M:%S.%f"),
                        record["value"],
                        record["Unit"],
                    ])
            QMessageBox.information(self, "保存成功", f"[DMM{self.index}]{self.name}({self.sn}): 数据已保存至\n{path}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "保存失败", f"[DMM{self.index}]{self.name}({self.sn}): 保存错误,{e}")

    def set_busy_controls(self, busy: bool) -> None:
        self.measurement_active = busy
        for widget in [
            self.btn_single,
            self.btn_connect,
            self.dmm_devices,
            self.dryrun_box,
            self.func_mode,
            self.func_range,
            self.apt_mode,
            self.apt_value,
            self.interval_count,
            self.interval_delay,
            self.interval_spin,
            self.interval_sample,
            self.btn_apply_config,
            self.btn_reset_config,
        ]:
            widget.setEnabled(not busy)
        self.btn_continue.setEnabled(True)

    def stop_continuous_measurement(self, wait_ms: int = 1500) -> None:
        if self.sample_read_worker and self.sample_read_worker.isRunning():
            self.sample_read_worker.stop()
            self.sample_read_worker.wait(wait_ms)
        self.sample_read_worker = None
        self.btn_continue.setText("持续采样")
        self.set_busy_controls(False)

    @auto_connected
    def measure_single(self):
        try:
            value = self.device.read_measurement(self.unit)
            self._display_value(value)
            self._record_data(value)
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "测量失败", f"[DMM{self.index}]{self.name}({self.sn}): {e}")

    @auto_connected
    def measure_continue(self):
        """后台连续采样，逐点更新DMM UI。"""
        if self.sample_read_worker and self.sample_read_worker.isRunning():
            self.stop_continuous_measurement()
            return

        count = self.interval_count.value()
        delay = self.interval_delay.value()
        spacing = self.interval_spin.value()
        sample = self.interval_sample.value()

        try:
            self.sample_read_worker = DMMSampleReadWorker(
                parent=self,
                device=self.device,
                count=count, delay_ms=delay,
                spacing_ms=spacing, sample=sample,
            )
            self.sample_read_worker.valueReady.connect(self._on_continuous_value)
            self.sample_read_worker.error.connect(self._on_continuous_error)
            self.sample_read_worker.stopped.connect(self._on_continuous_stopped)
            self.set_busy_controls(True)
            self.btn_continue.setText("停止采样")
            self.sample_read_worker.start()
            self.logger.info(f"[DMM{self.index}]{self.name}({self.sn}): 开始连续采样数据")
        except Exception as e:
            self.set_busy_controls(False)
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "连续采样失败", f"[DMM{self.index}]{self.name}({self.sn}): {e}")

    @Slot(float, object)
    def _on_continuous_value(self, values: list):
        self._display_value(values[-1])
        for value in values:
            self._record_data(value)

    @Slot(str)
    def _on_continuous_error(self, message: str):
        self.logger.error(f"[DMM{self.index}]{self.name}({self.sn}): 连续采样失败: {message}")
        self.stop_continuous_measurement()
        QMessageBox.warning(self, "连续采样停止", f"[DMM{self.index}]{self.name}({self.sn}): {message}")

    @Slot(str)
    def _on_continuous_stopped(self, message: str):
        self.logger.info(f"[DMM{self.index}]{self.name}({self.sn}): {message}")
        self.stop_continuous_measurement(wait_ms=100)

    def _display_value(self, value: float):
        self.lbl_value.setText(_format_float(value))

    def _record_data(self, value: float, timestamp: Optional[datetime] = None) -> None:
        record = {"timestamp": timestamp or datetime.now(), "value": value, "Unit": self.unit}
        self.data_records.append(record)
        self.stats.add(value)
        self._update_stats()
        self.btn_save.setEnabled(True)

    def _update_stats(self) -> None:
        if self.stats.count == 0:
            for widget in [self.lbl_value, self.avg_value, self.std_value, self.min_value, self.max_value]:
                widget.setText("---.----")
            self.count_value.setText("------")
            return
        self.avg_value.setText(_format_float(self.stats.mean))
        self.std_value.setText(_format_float(self.stats.std))
        self.min_value.setText(_format_float(self.stats.min_val or 0.0))
        self.max_value.setText(_format_float(self.stats.max_val or 0.0))
        self.count_value.setText(str(self.stats.count))


class DynamicWidgetArea(QWidget):
    allParametersChanged = Signal(list)

    def __init__(self, devices_scan_list: list, pic_path: Path, logger: logging.Logger, max_widgets: int = 6,
                 dry_run: bool = False):
        super().__init__()
        self.devices_scan_list = devices_scan_list
        self.pic_path = pic_path
        self.logger = logger
        self.dryrun = dry_run
        self.max_widgets = max_widgets
        self.current_widgets = 0
        self.widgets: list[DMMInstrumentUI] = []

        self.grid_layout = QGridLayout()
        self.grid_layout.setSpacing(10)
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.add_button = QPushButton("添加DMM")
        self.remove_button = QPushButton("移除DMM")
        self.add_button.clicked.connect(self.add_widget)
        self.remove_button.setEnabled(False)
        self.remove_button.clicked.connect(self.remove_widget)
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addStretch()

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        main_layout.addLayout(button_layout, 0)
        main_layout.addLayout(self.grid_layout, 1)
        main_layout.addStretch()
        self.add_widget()

    def add_widget(self):
        if self.current_widgets >= self.max_widgets:
            self.add_button.setEnabled(False)
            return
        widget = DMMInstrumentUI(
            index=self.current_widgets + 1,
            devices_scan_list=self.devices_scan_list,
            pic_ptah=self.pic_path,
            logger=self.logger,
            dry_run=self.dryrun,
        )
        widget.parameterChanged.connect(self.on_widget_parameter_changed)
        row = self.current_widgets // 3
        col = self.current_widgets % 3
        self.grid_layout.addWidget(widget, row, col)
        self.widgets.append(widget)
        self.current_widgets += 1
        self.add_button.setEnabled(self.current_widgets < self.max_widgets)
        self.remove_button.setEnabled(self.current_widgets > 1)
        self.logger.info(f"窗口{self.current_widgets}添加成功")

    def remove_widget(self):
        if self.current_widgets <= 1:
            return
        widget = self.widgets.pop()
        self.grid_layout.removeWidget(widget)
        widget.setHidden(True)
        widget.cleanup()
        widget.deleteLater()
        self.current_widgets -= 1
        self.add_button.setEnabled(self.current_widgets < self.max_widgets)
        self.remove_button.setEnabled(self.current_widgets > 1)
        self.updateGeometry()
        parent_window = self.window()
        if parent_window and parent_window.layout():
            parent_window.layout().activate()
            parent_window.resize(parent_window.minimumSizeHint())
        self.update_widget_info()

    @Slot(dict)
    def on_widget_parameter_changed(self, info: dict):
        self.logger.info(f"窗口{info.get('index')}更新状态:{info.get('info')}")
        self.update_widget_info()

    def update_widget_info(self):
        dmm_list = [widget for widget in self.widgets if widget.connected]
        self.allParametersChanged.emit(dmm_list)

    def cleanup(self) -> None:
        for widget in self.widgets:
            widget.cleanup()


class CheckBoxWidget(QWidget):
    parametersChanged = Signal(list)

    def __init__(self):
        super().__init__()
        self.checkboxes: list[QCheckBox] = []
        self.checkbox_layout = QGridLayout(self)
        self.checkbox_layout.setContentsMargins(5, 5, 5, 5)
        self.current_checkbox = 0
        self.add_function_btn()

    def add_function_btn(self):
        for i in range(6):
            box = QCheckBox("")
            box.stateChanged.connect(self.update_status)
            y = i % 4
            x = i // 4
            self.checkbox_layout.addWidget(box, x, y)
            self.checkboxes.append(box)
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(self.select_all)
        select_clr_btn = QPushButton("清空")
        select_clr_btn.clicked.connect(self.clear_all)
        self.checkbox_layout.addWidget(select_all_btn, 1, 2)
        self.checkbox_layout.addWidget(select_clr_btn, 1, 3)

    def del_checkbox(self):
        self.checkboxes = []
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.add_function_btn()
        self.checkbox_layout.update()

    def add_checkbox(self, text: str, index: int, sn: str = "", widget_index: int = -1):
        checkbox = self.checkboxes[index]
        checkbox.setText(text)
        checkbox.setProperty("sn", sn)
        checkbox.setProperty("widget_index", widget_index)

    def update_status(self):
        selected = []
        for cb in self.checkboxes:
            if cb.isChecked():
                selected.append(
                    {"text": cb.text(), "sn": cb.property("sn"), "widget_index": cb.property("widget_index")})
        self.parametersChanged.emit(selected)

    def select_all(self):
        for checkbox in self.checkboxes:
            text = checkbox.text()
            if text != "":
                checkbox.setChecked(True)
        self.update_status()

    def clear_all(self):
        for checkbox in self.checkboxes:
            checkbox.setChecked(False)
        self.update_status()


class DataTreeview(QWidget):
    dmm_choose_list = Signal(list)
    measurementReady = Signal(dict)
    measurementFailed = Signal(str)
    batchFinished = Signal()

    def __init__(self, logger: logging.Logger):
        super().__init__()
        self.logger = logger
        self.dmm_list: dict[str, DMMInstrumentUI] = {}
        self.dmm_choose: dict[int, DMMInstrumentUI] = {}
        self.data_treeview: dict[int, QTreeWidgetItem] = {}
        self.data: dict[str, list] = {}
        self.stats_map: dict[int, OnlineStats] = {}
        self.executor = ThreadPoolExecutor(max_workers=6)
        self._pending = False
        self._pending_lock = Lock()
        self._pending_count = 0

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        self.checkbox = CheckBoxWidget()
        self.checkbox.parametersChanged.connect(self.update_select)
        main_layout.addWidget(self.checkbox)

        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(btn_layout)
        self.test_btn = QPushButton("测量")
        self.test_btn.setStyleSheet(_measurement_btn_style())
        self.test_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.test_btn.clicked.connect(self.start_measure)
        btn_layout.addWidget(self.test_btn, 1)
        data_btn_layout = QVBoxLayout()
        btn_layout.addLayout(data_btn_layout)
        clear_btn = QPushButton("清空数据")
        clear_btn.clicked.connect(self.clear_measure)
        data_btn_layout.addWidget(clear_btn)
        save_btn = QPushButton("保存数据")
        save_btn.clicked.connect(self.save_measure)
        data_btn_layout.addWidget(save_btn)

        self.treeview = QTreeWidget()
        self.treeview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.treeview.setHeaderLabels(["DMM", "Func", "Count", "Max", "Min", "Avg", "Std", "Unit"])
        self.treeview.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.treeview.header().setStretchLastSection(False)
        main_layout.addWidget(self.treeview, 1)
        self.initialize_row()

        self.timer = QTimer(self)
        self.timer.setInterval(10)
        self.timer.timeout.connect(self.add_data)
        self.is_measuring = False
        self.measurementReady.connect(self._update_ui_simple)
        self.measurementFailed.connect(self._on_measurement_failed)
        self.batchFinished.connect(self._on_batch_finished)

    def cleanup(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def closeEvent(self, event):
        self.cleanup()
        super().closeEvent(event)

    def start_measure(self):
        if self.is_measuring:
            self.timer.stop()
            self.is_measuring = False
            self.test_btn.setText("测量")
            return
        if not self.dmm_choose:
            QMessageBox.warning(self, "提示", "请先选择至少一个DMM")
            return
        self.timer.start()
        self.is_measuring = True
        self.test_btn.setText("停止")

    def clear_measure(self):
        self.data = {}
        self.stats_map.clear()
        self.treeview.clear()
        self.initialize_row()

    def save_measure(self):
        if not self.data:
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存数据", "", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            if not path.endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as save_file:
                max_rows = max(len(data_list) for data_list in self.data.values())
                headers = list(self.data.keys())
                writer = csv.writer(save_file)
                writer.writerow(headers)
                for i in range(max_rows):
                    row = [self.data[key][i] if i < len(self.data[key]) else "" for key in headers]
                    writer.writerow(row)
            QMessageBox.information(self, "保存成功", f"数据已保存至 {path}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "保存失败", f"保存错误: {e}")

    def initialize_row(self):
        self.data.clear()
        self.data_treeview = {}
        self.stats_map.clear()
        self.treeview.clear()
        for index, dmm in self.dmm_choose.items():
            sn = dmm.sn
            func = dmm.func
            unit = dmm.unit
            new_item = QTreeWidgetItem([sn, func, "0", "0.00", "0.00", "0.00", "0.00", unit])
            self.data_treeview[index] = new_item
            self.stats_map[index] = OnlineStats()
            self.treeview.addTopLevelItem(new_item)

    @staticmethod
    def _read_dmm_payload(index: int, dmm: DMMInstrumentUI) -> dict:
        value = dmm.device.read_measurement(dmm.unit)
        return {"index": index, "sn": dmm.sn, "func": dmm.func, "unit": dmm.unit, "value": value}

    def add_data(self):
        if self._pending or not self.dmm_choose:
            return
        self._pending = True
        timestamp_list = self.data.get("Timestamp", [])
        timestamp_list.append(datetime.now())
        self.data["Timestamp"] = timestamp_list

        chosen = list(self.dmm_choose.items())
        with self._pending_lock:
            self._pending_count = len(chosen)

        for index, dmm in chosen:
            if not dmm.device:
                self.measurementFailed.emit(f"DMM{index}:{dmm.sn} 未连接")
                self._mark_one_future_finished()
                continue
            future = self.executor.submit(self._read_dmm_payload, index, dmm)
            future.add_done_callback(self._future_done)

    def _future_done(self, future):
        try:
            payload = future.result()
            self.measurementReady.emit(payload)
        except Exception as e:
            self.measurementFailed.emit(str(e))
        finally:
            self._mark_one_future_finished()

    def _mark_one_future_finished(self):
        with self._pending_lock:
            self._pending_count -= 1
            if self._pending_count <= 0:
                self.batchFinished.emit()

    @Slot()
    def _on_batch_finished(self):
        self._pending = False

    @Slot(str)
    def _on_measurement_failed(self, message: str):
        self.logger.error(f"读取DMM数据失败: {message}")

    @Slot(dict)
    def _update_ui_simple(self, payload: dict):
        index = payload["index"]
        value = payload["value"]
        data_key = f"{payload['func']}-{payload['unit']}\n{payload['sn']}"
        data = self.data.get(data_key, [])
        data.append(value)
        self.data[data_key] = data

        stats = self.stats_map.setdefault(index, OnlineStats())
        stats.add(value)
        item = self.data_treeview.get(index)
        if item:
            item.setText(2, str(stats.count))
            item.setText(3, _format_float(stats.max_val or 0.0))
            item.setText(4, _format_float(stats.min_val or 0.0))
            item.setText(5, _format_float(stats.mean))
            item.setText(6, _format_float(stats.std))

    def update_dmm_list(self, widgets: list):
        self.checkbox.del_checkbox()
        self.dmm_list.clear()
        self.dmm_choose = {}
        for index, widget in enumerate(widgets):
            self.dmm_list[widget.sn] = widget
            self.checkbox.add_checkbox(
                f"{widget.index}.{widget.name}-{widget.sn}",
                index=index, sn=widget.sn, widget_index=widget.index
            )
        self.initialize_row()

    @Slot(list)
    def update_select(self, checkbox_list: list[dict]):
        if self.is_measuring:
            self.timer.stop()
            self.is_measuring = False
            self.test_btn.setText("测量")
        self.dmm_choose = {}
        for index, checkbox_info in enumerate(checkbox_list):
            sn = checkbox_info.get("sn")
            if sn in self.dmm_list:
                self.dmm_choose[index] = self.dmm_list[sn]
        self.clear_measure()


class DMMContinuousWorker(QThread):
    valueReady = Signal(tuple)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, vol_dmm: DMMInstrumentUI, cur_dmm: DMMInstrumentUI, parent=None):
        super().__init__(parent)
        self.vol_dmm = vol_dmm
        self.cur_dmm = cur_dmm
        self._running = True

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        try:
            while True:
                if not self._running:
                    break
                vol_value = self.vol_dmm.device.read_measurement(self.vol_dmm.unit)
                cur_value = self.cur_dmm.device.read_measurement(self.cur_dmm.unit)
                self.valueReady.emit((
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                    vol_value,
                    cur_value,
                ))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.stopped.emit()


class DMMContinuousSyncWorker(QThread):
    valueReady = Signal(tuple)
    error = Signal(str)
    stopped = Signal()

    def __init__(self, vol_dmm: DMMInstrumentUI, cur_dmm: DMMInstrumentUI, mode: str, slope: str, parent=None):
        super().__init__(parent)
        self.logger = getattr(parent, "logger")
        self.vol_dmm = vol_dmm
        self.cur_dmm = cur_dmm
        self.mode = mode
        self.slope = slope
        self._running = True
        self._get_data = False

    def stop(self) -> None:
        self._running = False

    def run(self) -> None:
        """硬件同步动态功耗。

        接线：Master后面板 Trig Out -> Slave后面板 Ext Trig In。
        顺序：先配置并启动Slave等待外触发，再启动Master。Master INIT后输出触发，Slave被触发采样。
        """
        if self.mode == "电压Master→电流Slave":
            master = self.vol_dmm
            slave = self.cur_dmm
            master_role = "vol"
        elif self.mode == "电流Master→电压Slave":
            master = self.cur_dmm
            slave = self.vol_dmm
            master_role = "cur"
        else:
            raise RuntimeError(f"未知同步模式: {self.mode}")
        if master is None or slave is None:
            raise RuntimeError("硬件同步需要两台DMM")

        self.logger.info(f"动态功耗硬件同步开始：{self.mode}, slope={self.slope}")
        # 配置阶段：Slave外触发，Master立即触发并打开Trig Out。
        slave.device.set_dynamic_capture(
            trigger_source="EXT", trigger_slope=self.slope, enable_trigger_out=False
        )
        master.device.set_dynamic_capture(
            trigger_source="IMM", trigger_slope=self.slope, enable_trigger_out=True
        )

        # slave_result: dict[str, Any] = {}

        # def slave_task():
        #     try:
        #         while True:
        #             if self._get_data:
        #                 slave_result["values"] = slave.device.read_fetch(slave.unit)
        #                 self._get_data = False
        #             time.sleep(0.001)
        #     except Exception as exc:
        #         slave_result["error"] = exc

        try:
            # # 先让Slave进入等待外触发状态
            # slave_thread = Thread(target=slave_task, daemon=True)
            # slave_thread.start()
            # time.sleep(0.5)  # 确保Slave已INIT并等待触发
            # self.logger.info("Slave已启动等待外触发，现在启动Master")
            while self._running:
                # self._get_data = True
                master_values = master.device.read_fetch(master.unit)
                # slave_thread.join(timeout=0.5)
                # if slave_thread.is_alive():
                #     raise RuntimeError("Slave等待触发/采样超时：检查Trig Out -> Ext Trig接线、边沿、后面板端口设置")
                # if "error" in slave_result:
                #     raise slave_result["error"]
                # slave_values = slave_result.get("values", [])
                slave_values = slave.device.read_fetch(slave.unit)

                if master_role == "vol":
                    vol_values, cur_values = master_values, slave_values
                else:
                    vol_values, cur_values = slave_values, master_values
                self.valueReady.emit((
                    datetime.now(),
                    vol_values,
                    cur_values,
                ))
        except Exception as e:
            self.error.emit(str(e))
        finally:
            self.stopped.emit()
            master.device.restore_dynamic_capture()
            slave.device.restore_dynamic_capture()


class PowerWidget(QWidget):

    def __init__(self, logger: logging.Logger):
        super().__init__()
        self.logger = logger
        self.data_treeview: dict[str, QTreeWidgetItem] = {}
        self.dmm_list: dict[str, DMMInstrumentUI] = {}
        self.vol_dmm: Optional[DMMInstrumentUI] = None
        self.cur_dmm: Optional[DMMInstrumentUI] = None
        self.unit = "W"
        self.data_lock = Lock()
        self.raw_data = self._new_raw_data()
        self.measurement_thread: Optional[DMMContinuousWorker, DMMContinuousSyncWorker] = None
        self.is_measuring = False
        self.power_stats = {"vol": OnlineStats(), "cur": OnlineStats(), "pwr": OnlineStats()}

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 设备选择
        dmm_layout = QHBoxLayout()
        dmm_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(dmm_layout)
        dmm_layout.addWidget(QLabel("电压设备:"))
        self.vol_box = QComboBox()
        dmm_layout.addWidget(self.vol_box, 2)
        dmm_layout.addStretch(1)
        dmm_layout.addWidget(QLabel("电流设备:"))
        self.cur_box = QComboBox()
        dmm_layout.addWidget(self.cur_box, 2)

        # 配置行
        config_layout = QHBoxLayout()
        config_layout.setContentsMargins(0, 0, 0, 0)
        config_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        main_layout.addLayout(config_layout)

        config_layout.addWidget(QLabel("硬件同步:"))
        self.sync_mode = QComboBox()
        self.sync_mode.addItems(["不同步", "电压Master→电流Slave", "电流Master→电压Slave"])
        config_layout.addWidget(self.sync_mode)

        config_layout.addWidget(QLabel("边沿:"))
        self.trigger_slope = QComboBox()
        self.trigger_slope.addItems(["POS", "NEG"])
        self.trigger_slope.setToolTip("Slave的Ext Trig触发边沿；通常先用POS上升沿")
        config_layout.addWidget(self.trigger_slope)

        # config_layout.addWidget(QLabel("点数:"))
        # self.power_count = QSpinBox(minimum=1, maximum=1_000_000)
        # self.power_count.setValue(200)
        # config_layout.addWidget(self.power_count)
        # config_layout.addWidget(QLabel("间隔:"))
        # self.power_interval = QDoubleSpinBox(minimum=0.02, maximum=3_600_000)
        # self.power_interval.setDecimals(4)
        # self.power_interval.setValue(100.0)
        # self.power_interval.setSingleStep(1.0)
        # config_layout.addWidget(self.power_interval)
        # config_layout.addWidget(QLabel("ms/point"))

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(btn_layout)
        self.test_btn = QPushButton("开始功耗测量")
        self.test_btn.setStyleSheet(_measurement_btn_style())
        self.test_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.test_btn.clicked.connect(self.start_measure)
        btn_layout.addWidget(self.test_btn, 1)
        data_btn_layout = QVBoxLayout()
        btn_layout.addLayout(data_btn_layout)
        clear_btn = QPushButton("清空数据")
        data_btn_layout.addWidget(clear_btn)
        save_btn = QPushButton("保存数据")
        save_btn.clicked.connect(self.save_measure)
        data_btn_layout.addWidget(save_btn)

        # 树形视图
        self.treeview = QTreeWidget()
        self.treeview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.treeview.setHeaderLabels(["DMM", "Func", "Count", "Max", "Min", "Avg", "Std", "Unit"])
        self.treeview.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.treeview.header().setStretchLastSection(False)
        main_layout.addWidget(self.treeview, 1)
        self._rebuild_treeview()
        self.vol_box.currentTextChanged.connect(self.update_device_choose)
        self.cur_box.currentTextChanged.connect(self.update_device_choose)
        clear_btn.clicked.connect(self._rebuild_treeview)

        # 定时器（仅用于动态功耗的定期刷新，静态功耗由信号驱动）
        self.ui_update_timer = QTimer(self)
        self.ui_update_timer.setInterval(500)
        self.ui_update_timer.timeout.connect(self.update_ui)

    @staticmethod
    def _new_raw_data() -> dict[str, deque]:
        return {
            "time": deque(maxlen=MAX_POWER_POINTS),
            "voltage": deque(maxlen=MAX_POWER_POINTS),
            "current": deque(maxlen=MAX_POWER_POINTS),
            "power": deque(maxlen=MAX_POWER_POINTS),
        }

    def update_device_choose(self):
        if self.is_measuring:
            return
        self.clear_measure()
        self.vol_dmm = None
        self.cur_dmm = None

        vol_choose = self.vol_box.currentText()
        if vol_choose:
            vol_sn = vol_choose.rsplit("-", 1)[-1]
            self.vol_dmm = self.dmm_list.get(vol_sn)

        cur_choose = self.cur_box.currentText()
        if cur_choose:
            cur_sn = cur_choose.rsplit("-", 1)[-1]
            self.cur_dmm = self.dmm_list.get(cur_sn)
        self._rebuild_treeview()

    def _rebuild_treeview(self):
        self.treeview.clear()
        self.data_treeview.clear()

        vol_sn = self.vol_dmm.sn if self.vol_dmm else ""
        vol_unit = self.vol_dmm.unit if self.vol_dmm else "V"
        vol_item = QTreeWidgetItem([vol_sn, "Voltage", "0", "0.00", "0.00", "0.00", "0.00", vol_unit])
        self.data_treeview["vol"] = vol_item
        self.treeview.addTopLevelItem(vol_item)

        cur_sn = self.cur_dmm.sn if self.cur_dmm else ""
        cur_unit = self.cur_dmm.unit if self.cur_dmm else "A"
        cur_item = QTreeWidgetItem([cur_sn, "Current", "0", "0.00", "0.00", "0.00", "0.00", cur_unit])
        self.data_treeview["cur"] = cur_item
        self.treeview.addTopLevelItem(cur_item)

        vol_scale = get_scale_for_units(vol_unit)
        cur_scale = get_scale_for_units(cur_unit)
        pwr_scale = vol_scale * cur_scale
        unit = "W"
        if pwr_scale != 1:
            for key, value in Base_Unit.items():
                if 1 / pwr_scale == value:
                    unit = key + "W"
                    break
        pwr_item = QTreeWidgetItem(["---", "Power", "0", "0.00", "0.00", "0.00", "0.00", unit])
        self.data_treeview["pwr"] = pwr_item
        self.treeview.addTopLevelItem(pwr_item)

    def _on_mode_changed(self, mode: str) -> None:
        self.is_dynamic = (mode == "动态功耗")
        self.logger.info(f"user choose power mode to {mode}")
        self.sync_mode.setEnabled(self.is_dynamic)
        self.trigger_slope.setEnabled(self.is_dynamic)
        if self.is_dynamic:
            self.ui_update_timer.setInterval(500)
            # self.power_count.setValue(min(self.power_count.value(), 10_000))
            # self.power_interval.setValue(max(self.power_interval.value(), 100.0))
        else:
            self.ui_update_timer.setInterval(300)
            # if self.power_count.value() < 1000:
            #     self.power_count.setValue(5000)
            # if self.power_interval.value() > 10.0:
            #     self.power_interval.setValue(1.0)

    def update_dmm_list(self, widgets: list):
        self.logger.info(f"更新{len(widgets)}个仪器")
        self.dmm_list.clear()
        sn_list = [""]
        for widget in widgets:
            self.dmm_list[widget.sn] = widget
            sn_list.append(f"{widget.func}-{widget.sn}")
        self.vol_box.blockSignals(True)
        self.cur_box.blockSignals(True)
        current_vol = self.vol_box.currentText()
        current_cur = self.cur_box.currentText()
        self.vol_box.clear()
        self.vol_box.addItems(sn_list)
        self.cur_box.clear()
        self.cur_box.addItems(sn_list)
        if current_vol in sn_list:
            self.vol_box.setCurrentText(current_vol)
        else:
            self.vol_box.setCurrentText("")
        if current_cur in sn_list:
            self.cur_box.setCurrentText(current_cur)
        else:
            self.cur_box.setCurrentText("")
        self.vol_box.blockSignals(False)
        self.cur_box.blockSignals(False)
        # self._rebuild_treeview()

    def _validate_power_dmm(self) -> bool:
        if not self.vol_dmm or not self.cur_dmm:
            QMessageBox.warning(self, "提示", "请先选择电压DMM和电流DMM")
            return False
        if self.vol_dmm is self.cur_dmm:
            QMessageBox.warning(self, "提示", "电压和电流必须使用两台不同DMM；一台34465A不能同时测V和I")
            return False
        if not self.vol_dmm.device or not self.cur_dmm.device:
            QMessageBox.warning(self, "提示", "DMM未连接")
            return False
        if "电压" not in self.vol_dmm.func or "电流" not in self.cur_dmm.func:
            QMessageBox.warning(self, "提示", "建议电压设备配置为电压功能，电流设备配置为电流功能后再测功耗")
            return False
        return True

    def start_measure(self):
        if self.is_measuring:
            self.stop_measurement()
            return
        if not self._validate_power_dmm():
            return
        self.clear_measure()
        self._rebuild_treeview()
        self.is_measuring = True
        self.test_btn.setText("停止功耗测量")
        self.vol_box.setEnabled(False)
        self.cur_box.setEnabled(False)
        self.sync_mode.setEnabled(False)
        self.trigger_slope.setEnabled(False)
        self.ui_update_timer.start(300)

        sync_mode = self.sync_mode.currentText()
        if sync_mode == "不同步":
            self.measurement_thread = DMMContinuousWorker(parent=self, vol_dmm=self.vol_dmm, cur_dmm=self.cur_dmm)
            self.measurement_thread.valueReady.connect(self._append_power_sample)
        else:
            slope = self.trigger_slope.currentText() or "POS"
            self.measurement_thread = DMMContinuousSyncWorker(
                parent=self, vol_dmm=self.vol_dmm, cur_dmm=self.cur_dmm,
                mode=sync_mode, slope=slope
            )
            self.measurement_thread.valueReady.connect(self._append_dynamic_arrays)
        self.measurement_thread.error.connect(self._on_continuous_error)
        self.measurement_thread.stopped.connect(self.stop_measurement)
        self.measurement_thread.start()

    @Slot(str)
    def _on_continuous_error(self, message: str):
        self.logger.error(f"连续采样失败: {message}")
        self.stop_measurement()
        QMessageBox.warning(self, "连续采样停止", message)

    def stop_measurement(self):
        self.is_measuring = False
        if self.measurement_thread and self.measurement_thread.isRunning():
            self.measurement_thread.stop()
            self.measurement_thread.wait(2)
        self.measurement_thread = None
        self.ui_update_timer.stop()
        self.test_btn.setText("开始功耗测量")
        self.vol_box.setEnabled(True)
        self.cur_box.setEnabled(True)
        self.sync_mode.setEnabled(True)
        self.trigger_slope.setEnabled(True)
        # self.power_count.setEnabled(True)
        # self.power_interval.setEnabled(True)

    def cleanup(self) -> None:
        self.stop_measurement()

    def clear_measure(self):
        with self.data_lock:
            self.raw_data = self._new_raw_data()
            self.power_stats = {"vol": OnlineStats(), "cur": OnlineStats(), "pwr": OnlineStats()}
        self._rebuild_treeview()

    def save_measure(self):
        with self.data_lock:
            if not self.raw_data["time"]:
                return
            save_data = {
                "Time": list(self.raw_data["time"]),
                f"Voltage({self.vol_dmm.unit if self.vol_dmm else 'V'})": list(self.raw_data["voltage"]),
                f"Current({self.cur_dmm.unit if self.cur_dmm else 'A'})": list(self.raw_data["current"]),
                f"Power({self.unit})": list(self.raw_data["power"]),
                "SyncMode": [self.sync_mode.currentText()] * len(self.raw_data["time"]),
            }
        path, _ = QFileDialog.getSaveFileName(self, "保存数据", "", "CSV文件 (*.csv)")
        if not path:
            return
        try:
            if not path.endswith(".csv"):
                path += ".csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as save_file:
                max_rows = max(len(data_list) for data_list in save_data.values())
                headers = list(save_data.keys())
                writer = csv.writer(save_file)
                writer.writerow(headers)
                for i in range(max_rows):
                    row = [save_data[key][i] if i < len(save_data[key]) else "" for key in headers]
                    writer.writerow(row)
            QMessageBox.information(self, "保存成功", f"数据已保存至 {path}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, "保存失败", f"保存错误: {e}")

    @Slot(tuple)
    def _append_power_sample(self, data: tuple) -> None:
        timestamp, vol_value, cur_value = data
        pwr_value = vol_value * cur_value
        with self.data_lock:
            self.raw_data["time"].append(timestamp)
            self.raw_data["voltage"].append(vol_value)
            self.raw_data["current"].append(cur_value)
            self.raw_data["power"].append(pwr_value)
            self.power_stats["vol"].add(vol_value)
            self.power_stats["cur"].add(cur_value)
            self.power_stats["pwr"].add(pwr_value)

    @Slot(tuple)
    def _append_dynamic_arrays(self, data: tuple):
        base, vol_values, cur_values = data
        n = min(len(vol_values), len(cur_values))
        if n == 0:
            raise RuntimeError("动态采样没有返回有效数据")
        with self.data_lock:
            for i in range(n):
                timestamp = (base + timedelta(seconds=i)).strftime("%Y-%m-%d %H:%M:%S.%f")
                vol_value = vol_values[i]
                cur_value = cur_values[i]
                pwr_value = vol_value * cur_value
                self.raw_data["time"].append(timestamp)
                self.raw_data["voltage"].append(vol_value)
                self.raw_data["current"].append(cur_value)
                self.raw_data["power"].append(pwr_value)
                self.power_stats["vol"].add(vol_value)
                self.power_stats["cur"].add(cur_value)
                self.power_stats["pwr"].add(pwr_value)
        self.logger.info(f"动态功耗写入{n}点")

    def update_ui(self):
        if not self.is_measuring:
            return
        with self.data_lock:
            stats_snapshot = {
                key: (stats.count, stats.max_val or 0.0, stats.min_val or 0.0, stats.mean, stats.std)
                for key, stats in self.power_stats.items()
            }
        self.update_treeview_item("vol", *stats_snapshot["vol"])
        self.update_treeview_item("cur", *stats_snapshot["cur"])
        self.update_treeview_item("pwr", *stats_snapshot["pwr"])
        self.treeview.repaint()

    def update_treeview_item(self, key, count, max_val, min_val, avg_val, std_val):
        item = self.data_treeview.get(key)
        if item:
            item.setText(2, str(count))
            item.setText(3, _format_float(max_val))
            item.setText(4, _format_float(min_val))
            item.setText(5, _format_float(avg_val))
            item.setText(6, _format_float(std_val))


class MainWindow(QMainWindow):
    def __init__(
            self,
            name: str,
            version: str = "1.0.0",
            logger: Optional[Logger] = None,
            data_path: Union[PathLike[str], str, None] = None,
            dryrun: bool = False,
            *args,
            **kwargs,
    ):
        super().__init__()
        self.widget_name = name
        self.logger = logger
        self.data_path = Path.cwd()
        if data_path:
            self.data_path = Path(data_path)
        self.data_path.mkdir(exist_ok=True)
        if not self.logger:
            log_path = self.data_path / "script_log"
            log_path.mkdir(exist_ok=True)
            self.logger = create_logger(name=name, level=logging.DEBUG, log_path=log_path)
        self.logger.info(f"{name} logging started")
        self.pic_dir = self.data_path / "pictures"
        self.pic_dir.mkdir(exist_ok=True)
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外kwargs参数：{kwargs}")
        self.devices_scan_list = get_device_patterns("DMM")

        self.setWindowTitle(f"台式万用表控制器V{version}")
        self.resize(600, 500)

        self.current_area = 0
        self.last_area = 0

        main_widget = QFrame()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        switch_layout = QHBoxLayout()
        self.setup_button = QPushButton("设备setup")
        self.setup_button.clicked.connect(self.switch_setup)
        self.setup_button.setDisabled(True)
        switch_layout.addWidget(self.setup_button)
        self.switch_button = QPushButton("多台连续测试")
        self.switch_button.clicked.connect(self.switch_area)
        switch_layout.addWidget(self.switch_button)
        switch_layout.addStretch()

        self.stacked_widget = QStackedWidget()
        self.drive_area = DynamicWidgetArea(
            devices_scan_list=self.devices_scan_list,
            pic_path=self.pic_dir,
            logger=self.logger,
            dry_run=dryrun,
        )
        self.tree_area = DataTreeview(logger=self.logger)
        self.power_area = PowerWidget(logger=self.logger)
        self.stacked_widget.addWidget(self.drive_area)
        self.stacked_widget.addWidget(self.tree_area)
        self.stacked_widget.addWidget(self.power_area)

        main_layout.addLayout(switch_layout)
        main_layout.addWidget(self.stacked_widget, 1)

        self.drive_area.allParametersChanged.connect(self.update_info)

    def cleanup(self) -> None:
        self.drive_area.cleanup()
        self.tree_area.cleanup()
        self.power_area.cleanup()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def switch_setup(self):
        self.logger.info(f"user choose ui to DMM配置")
        self.update_area(0)

    def switch_area(self):
        area_index = self.current_area + 1
        if self.current_area == 0 and self.last_area != 0:
            area_index = self.last_area
        if area_index > 2:
            area_index = 1
        self.update_area(area_index)

    def update_area(self, index):
        if index == self.current_area:
            return
        if self.tree_area.is_measuring:
            self.tree_area.start_measure()
        if self.power_area.is_measuring:
            self.power_area.start_measure()
        self.last_area = self.current_area
        self.stacked_widget.setCurrentIndex(index)
        self.current_area = index
        if index == 0:
            self.setup_button.setDisabled(True)
        else:
            self.setup_button.setDisabled(False)
        if index == 1 or (index == 0 and self.last_area == 2):
            self.logger.info(f"user choose ui to 连续测量")
            self.switch_button.setText("切至功耗测试")
        elif index == 2 or (index == 0 and self.last_area == 1):
            self.logger.info(f"user choose ui to 功耗测试")
            self.switch_button.setText("切至连续测量")

    def deleteLater(self, /):
        self.cleanup()

    def closeEvent(self, event):
        self.cleanup()
        event.accept()

    def update_info(self, widgets: list):
        self.tree_area.update_dmm_list(widgets)
        self.power_area.update_dmm_list(widgets)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="DMM", version="0.2.0-power-refactor", logger=None, dryrun=True)
    window.show()
    sys.exit(app.exec())
