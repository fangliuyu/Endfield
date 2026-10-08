import csv
import logging
import traceback
import os
import subprocess
import sys
import time
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Union, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QFrame, QHBoxLayout,
    QVBoxLayout, QComboBox, QCheckBox, QPushButton,
    QLabel, QLineEdit, QGridLayout, QMessageBox
)

import numpy as np
import matplotlib.ticker as ticker
from matplotlib.figure import Figure
from matplotlib.backends import backend_svg  # NOQA
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_n6700 import N6700Agent
from lib.instruments.instrument_b2900 import B2900Agent, Instrument_Dryrun
from lib.filetools import read_data_from_yaml, save_data_to_yaml
from lib.qtui.custom_widget import build_group_box


def _check_device_type(info: str, type_list: list[str]) -> bool:
    for name in type_list:
        if name.lower() in info.lower():
            return True
    return False


def create_device(osc_info: str, address: str, n6700_list: list[str], b2900_list: list[str], logger=None):
    if _check_device_type(osc_info, n6700_list):
        if "demo" in osc_info:
            from lib.instruments.instrument_n6700 import Instrument_Dryrun as N6700Agent_DryRUN
            return N6700Agent_DryRUN(instrument_address=address, logger=logger)
        return N6700Agent(instrument_address=address, logger=logger)
    elif _check_device_type(osc_info, b2900_list):
        if "demo" in osc_info:
            from lib.instruments.instrument_b2900 import Instrument_Dryrun as B2900Agent_DryRUN
            return B2900Agent_DryRUN(instrument_address=address, logger=logger)
        return B2900Agent(instrument_address=address, logger=logger)
    else:
        return Instrument_Dryrun(instrument_address=address, logger=logger)


Color_List = ['green', 'red', 'blue', 'yellow', 'cyan', 'magenta', 'grey', 'black']


class TestWorker(QThread):
    """测试工作线程"""
    progress = Signal(float, float)  # 电压，电流
    finished = Signal(bool, str)  # 成功标志，错误信息

    def __init__(self, device, run_type, settings, logger: logging.Logger, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.device: Optional[N6700Agent, B2900Agent] = device
        self.run_type = run_type
        self.settings = settings
        self.n6700 = (self.settings["device"] == "N6700")
        self._is_running = True

    def stop(self):
        """停止测试"""
        self._is_running = False

    def run(self):
        """主测试逻辑"""

        self.logger.info("解析设置:")
        self.logger.info(f"模式:{self.run_type}")
        psu_vol = True if self.run_type == 'I-V' else False

        # 解析设置
        channel = int(self.settings['channel'])
        sleep_time = round(float(self.settings['sample_time']), 3) / 1000
        self.logger.info(f"仪器通道:{channel}")
        self.logger.info(f"仪器读取间隔:{sleep_time}s/point")

        if psu_vol:
            value_start = round(float(self.settings['start']), 6) / 1000
            value_end = round(float(self.settings['end']), 6) / 1000
            value_step = round(float(self.settings['step']), 6) / 1000
            limit = float(self.settings['limit'])
            self.logger.info(f"电压限制至: {limit}V")
            self.logger.info(f"电流设置: 从 {value_start}mA 到 {value_step}mA, 以 {value_step}mA 为步进")
        else:
            value_start = float(self.settings['start'])
            value_end = float(self.settings['end'])
            value_step = float(self.settings['step'])
            limit = round(float(self.settings['limit']), 6) / 1000
            self.logger.info(f"电压设置: 从 {value_start}V 到 {value_step}V, 以 {value_step}V 为步进")
            self.logger.info(f"电流限制至: {limit}mA")

        try:
            # 初始化设备
            self.logger.info("初始化设备...")
            if self.n6700:
                self.device.set_ch_emulation(channel=channel, emulation='PS4Q')
                self.logger.info("将6705设置为四象电源")
            if psu_vol:
                if self.n6700:
                    self.device.set_ch_operating(channel=channel, operating='CURRent')
                    self.device.set_ch_current(current=value_start, channel=channel)
                    self.device.set_ch_voltage_limit(limit=limit, channel=channel)
                else:
                    self.device.set_source_mode(channel=channel, mode='CURRent')
                    self.device.set_ch_current(current=value_start, channel=channel)
                    self.device.set_ch_voltage(voltage=limit, channel=channel)
                self.logger.info("设置为电流源")
            else:
                if self.n6700:
                    self.device.set_ch_operating(channel=channel, operating='VOLTage')
                    self.device.set_ch_voltage(voltage=value_start, channel=channel)
                    self.device.set_ch_current_limit(limit=limit, channel=channel)
                else:
                    self.device.set_ch_operating(channel=channel, operating='VOLTage')
                    self.device.set_ch_voltage(voltage=value_start, channel=channel)
                    self.device.set_ch_current(current=limit, channel=channel)
                self.logger.info("设置为电压源")

            # 生成测试点
            all_step = []
            value = value_start
            while value < value_end:
                all_step.append(round(value, 6))
                value += value_step
            all_step.append(value_end)

            total_steps = len(all_step)

            # 执行测试
            self.device.set_ch_output_state(state=True, channel=channel)
            time.sleep(2)
            self.logger.info("开始输出")
            for i, value in enumerate(all_step):
                if not self._is_running:
                    break

                self.logger.info("=" * 100)
                self.logger.info(f"测试进程[{i + 1}/{total_steps}]")

                # 设置值
                if psu_vol:
                    self.logger.info(f"设置当前电流 {value}")
                    self.device.set_ch_current(current=value, channel=channel)
                else:
                    self.logger.info(f"设置当前电压 {value}")
                    self.device.set_ch_voltage(voltage=value, channel=channel)

                time.sleep(sleep_time)
                # 测量
                voltage = self.device.measure_ch_voltage(channel=channel)
                current = self.device.measure_ch_current(channel=channel, unit='m')
                self.logger.info(f"读取当前电压 {voltage}V; 当前电流 {current}mA")

                # 发送进度信号
                self.progress.emit(voltage, current)

            if self._is_running:
                self.finished.emit(True, "测试完成")
            else:
                self.finished.emit(False, "测试被取消")

        except Exception as e:
            self.logger.exception(traceback.format_exc())
            self.finished.emit(False, str(e))
        finally:
            # 关闭设备输出
            self.device.set_ch_output_state(state=False, channel=channel)


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: logging.Logger = None, dry_run=False,
                 data_path: Union[PathLike[str], str, None] = None, *args, **kwargs):
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
        self.data_dir = self.data_path / "result"
        if not self.data_dir.exists():
            self.data_dir.mkdir()
        self.setting_file = self.data_path / "setting.yaml"
        self.b2900_list = []
        self.n6700_list = []
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[Union[N6700Agent, B2900Agent]] = None
        self.connected = False
        self.run_status = False
        self.worker: Optional[TestWorker] = None
        self.run_type = 'I-V'
        self.new_turn = True
        self.test_times = -1
        self.last_label = ''
        self.curve_data = {}  # {label: (x_data, y_data, line_object)}
        self.current_lines = []  # 当前显示的线条列表

        self.setWindowTitle(f"IV曲线（电流-电压曲线）测试工具V{version}")
        self.resize(800, 600)

        main_widget = QFrame()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        main_layout.addLayout(left_layout)
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        main_layout.addLayout(right_layout, 1)

        # Device Scan
        device_scan_group, scan_layout = build_group_box("Device Scan", QVBoxLayout())
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.setSpacing(0)
        left_layout.addWidget(device_scan_group)
        self.osc_devices = QComboBox()
        self.osc_devices.setMaximumWidth(300)
        self.osc_devices.setEditable(False)
        self.osc_devices.currentTextChanged.connect(self.choose_devices_list)
        scan_layout.addWidget(self.osc_devices)
        scan_btn_layout = QHBoxLayout()
        scan_btn_layout.setContentsMargins(0, 0, 0, 0)
        scan_btn_layout.setSpacing(5)
        scan_layout.addLayout(scan_btn_layout)
        self.btn_dryrun = QCheckBox("dryrun")
        self.btn_dryrun.setChecked(dry_run)
        self.btn_dryrun.stateChanged.connect(self.switch_dryrun)
        scan_btn_layout.addWidget(self.btn_dryrun, alignment=Qt.AlignmentFlag.AlignLeft)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.device_sate_change)
        scan_btn_layout.addWidget(self.btn_connect, alignment=Qt.AlignmentFlag.AlignRight)

        # Setting
        smu_setting_group, setting_layout = build_group_box("SMU Setting", QGridLayout())
        # setting_layout.setContentsMargins(0, 0, 0, 0)
        # setting_layout.setSpacing(0)
        left_layout.addWidget(smu_setting_group, 1)

        setting_layout.addWidget(QLabel("SMU Channel"), 0, 0)
        self.channel_entry = QComboBox()
        self.channel_entry.addItems(["1", "2", "3", "4"])
        self.channel_entry.setEditable(True)
        setting_layout.addWidget(self.channel_entry, 0, 1, 1, 2)

        setting_layout.addWidget(QLabel("SMU Start"), 1, 0)
        self.start_entry = QLineEdit()
        setting_layout.addWidget(self.start_entry, 1, 1)
        setting_layout.addWidget(QLabel("V(mA)"), 1, 2)

        setting_layout.addWidget(QLabel("SMU End"), 2, 0)
        self.end_entry = QLineEdit()
        setting_layout.addWidget(self.end_entry, 2, 1)
        setting_layout.addWidget(QLabel("V(mA)"), 2, 2)

        setting_layout.addWidget(QLabel("SMU step"), 3, 0)
        self.step_entry = QLineEdit()
        setting_layout.addWidget(self.step_entry, 3, 1)
        setting_layout.addWidget(QLabel("V(mA)/point"), 3, 2)

        setting_layout.addWidget(QLabel("SMU limit"), 4, 0)
        self.limit_entry = QLineEdit()
        setting_layout.addWidget(self.limit_entry, 4, 1)
        setting_layout.addWidget(QLabel("mA(V)"), 4, 2)

        setting_layout.addWidget(QLabel("SMU Delay"), 5, 0)
        self.sample_entry = QLineEdit()
        setting_layout.addWidget(self.sample_entry, 5, 1)
        setting_layout.addWidget(QLabel("s/point"), 5, 2)

        setting_layout.addWidget(QLabel("Polt label"), 6, 0)
        self.label_entry = QLineEdit("polt-1")
        setting_layout.addWidget(self.label_entry, 6, 1, 1, 2)

        # 颜色选择
        setting_layout.addWidget(QLabel("Polt Color"), 7, 0)
        self.color_choose = QComboBox()
        self.color_choose.addItems(Color_List)
        self.color_choose.setCurrentIndex(0)
        setting_layout.addWidget(self.color_choose, 7, 1)
        self.clear_button = QPushButton('clear')
        self.clear_button.clicked.connect(self.clear)
        setting_layout.addWidget(self.clear_button, 7, 2)

        # 按钮框架
        button_group, button_layout = build_group_box("btn start", QHBoxLayout())
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(15)
        left_layout.addWidget(button_group)
        self.iv_button = QPushButton('I-V Start')
        self.iv_button.clicked.connect(lambda: self.run('I-V'))
        button_layout.addWidget(self.iv_button)
        self.log_button = QPushButton('open log file')
        self.log_button.clicked.connect(self.open_file)
        button_layout.addWidget(self.log_button)
        self.vi_button = QPushButton('V-I Start')
        self.vi_button.clicked.connect(lambda: self.run('V-I'))
        button_layout.addWidget(self.vi_button)

        left_layout.addStretch(2)

        self.fig = Figure()
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvas(self.fig)
        self.canvas.setMouseTracking(True)
        self.cid = self.canvas.mpl_connect('motion_notify_event', self.on_mouse_move)
        self.annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(20, 20), textcoords="offset points",
            bbox=dict(boxstyle="round", fc="w", alpha=0.8),
            arrowprops=dict(arrowstyle="->")
        )
        self.annot.set_visible(False)
        right_layout.addWidget(self.canvas, 1)

        self.toolbar = NavigationToolbar(self.canvas, self)
        right_layout.addWidget(self.toolbar)

        self.load_setting()
        self.disable_btn_status()

    def deleteLater(self, /):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        if self.device or self.connected:
            self.logger.info(f"设备未断开，将自动断开连接")
            self.device.disconnect()
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        if self.device or self.connected:
            self.logger.info(f"设备未断开，将自动断开连接")
            self.device.disconnect()
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()

    def load_setting(self):
        self.n6700_list = get_device_patterns("N6700")
        self.b2900_list = get_device_patterns("B2900")

        data = {}
        if self.setting_file.exists():
            data = read_data_from_yaml(self.setting_file)
        self.channel_entry.setCurrentText(data.get("SMU_channel", "1"))
        self.start_entry.setText(data.get("SMU_start", "-1.8"))
        self.end_entry.setText(data.get("SMU_end", "1.8"))
        self.step_entry.setText(data.get("SMU_step", "0.02"))
        self.limit_entry.setText(data.get("SMU_limit", "20"))
        self.sample_entry.setText(data.get("SMU_time", "0.02"))

        self.refresh_devices_list()
        # 初始化图形设置
        self.apply_initial_setting()

    def save_setting(self):
        data = {
            'SMU_channel': self.channel_entry.currentText(),
            'SMU_start': self.start_entry.text(),
            'SMU_end': self.end_entry.text(),
            'SMU_step': self.step_entry.text(),
            'SMU_limit': self.limit_entry.text(),
            'SMU_time': self.sample_entry.text(),
        }
        save_data_to_yaml(data, self.setting_file)

    def choose_devices_list(self):
        self.osc_devices.blockSignals(True)
        current_text = self.osc_devices.currentText()
        if current_text and current_text != "刷新列表":
            info = current_text.split(": ")
            self.name = info[0]
            self.sn = info[1]
            self.logger.info(f"用户选择了{info}")
        else:
            self.refresh_devices_list()
        self.osc_devices.blockSignals(False)

    def refresh_devices_list(self):
        if self.device and self.connected:
            self.disconnect_device()
        self.logger.info(f"刷新列表")
        self.devices_list = {}
        self.osc_devices.clear()
        devices = get_device_list()
        sn_list = [""]
        for index, address in enumerate(devices):
            ok, class_name, sn = check_device_module(address, self.n6700_list + self.b2900_list)
            self.logger.debug(f"{index}.{sn}: {class_name}")
            if ok:
                sn_list.append(class_name + ": " + sn)
                self.devices_list[sn] = address
                self.logger.debug(f"{class_name}为所需仪器，加入列表")
        self.logger.info(f"当前识别到了{len(sn_list) - 1}个仪器")
        if self.dryrun:
            sn_list.append("KeysightTechnologiesB2900(demo): MY114514")
            self.devices_list["MY114514"] = "USB0::0x2A8D::0x0F02::MY11451419::INSTR"
            sn_list.append("KeysightTechnologiesN6705C(demo): MY114515")
            self.devices_list["MY114515"] = "USB0::0x2A8D::0x0F02::MY11541420::INSTR"
        sn_list.append("刷新列表")
        self.osc_devices.addItems(sn_list)
        self.osc_devices.setCurrentText("")
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

    def connect_device(self):
        if not self.sn:
            raise Exception("请先选择设备")
        self.device = create_device(osc_info=self.name, address=self.devices_list[self.sn], n6700_list=self.n6700_list, b2900_list=self.b2900_list, logger=self.logger)
        self.device.connect(reset=False)
        self.btn_connect.setText("Disconnect")
        self.osc_devices.setEnabled(False)
        self.connected = True
        self.reset_status()

    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.osc_devices.setEnabled(True)
            self.device = None
            self.connected = False
        self.disable_btn_status()

    def open_file(self):
        """打开日志文件"""
        if self.data_dir.exists():
            if os.name == 'nt':  # Windows
                os.startfile(self.data_dir)
            else:  # macOS/Linux
                subprocess.run(['open' if os.name == 'posix' else 'xdg-open', self.data_dir])
        else:
            self.logger.warning(f'{self.data_dir}路径不存在')
            QMessageBox.warning(self, "警告", f"{self.data_dir}路径不存在")

    def clear(self):
        """清除数据"""
        self.color_choose.setCurrentIndex(0)
        self.test_times = -1
        self.new_turn = True
        self.run_type = 'I-V'

        # 清除曲线数据
        self.curve_data.clear()
        self.current_lines.clear()

        self.fig.clear()
        self.ax = self.fig.add_subplot(111)

        # 重新初始化标注
        self.annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(20, 20), textcoords="offset points",
            bbox=dict(boxstyle="round", fc="w", alpha=0.8),
            arrowprops=dict(arrowstyle="->")
        )
        self.annot.set_visible(False)

        try:
            start_volt = float(self.start_entry.text())
            end_volt = float(self.end_entry.text())
            current_lim = float(self.limit_entry.text())

            self.ax.set_xlim((start_volt * 1.1, end_volt * 1.1))
            self.ax.set_ylim((-current_lim * 1.1, current_lim * 1.1))
        except ValueError:
            pass

        for tick_label in self.ax.xaxis.get_ticklabels():
            tick_label.set_fontsize(8)
            tick_label.set_rotation(90)
        for tick_label in self.ax.yaxis.get_ticklabels():
            tick_label.set_fontsize(8)

        self.ax.axvline(x=0, color='black')
        self.ax.axhline(y=0, color='black')
        self.ax.grid()
        self.fig.tight_layout()
        self.canvas.draw()

        self.last_label = ""
        self.iv_button.setText('I-V Start')
        self.iv_button.setEnabled(True)
        self.vi_button.setText('V-I Start')
        self.vi_button.setEnabled(True)

    def apply_initial_setting(self):
        """应用初始图形设置"""
        try:
            start_limit, end_limit = float(self.start_entry.text()) * 1.2, float(self.end_entry.text()) * 1.2
            x_min_limit = min(start_limit, end_limit)
            x_max_limit = max(start_limit, end_limit)
            y_limit = float(self.limit_entry.text()) * 1.2
            y_min_limit, y_max_limit = -y_limit, y_limit
            self.ax.set_xlim(x_min_limit, x_max_limit)
            self.ax.set_ylim(y_min_limit, y_max_limit)
            self.ax.xaxis.set_major_locator(ticker.MultipleLocator(float(self.step_entry.text()) * 5))
            self.ax.yaxis.set_major_locator(ticker.MultipleLocator(y_limit * 2 * 5 / 100))

            for tick_label in self.ax.xaxis.get_ticklabels():
                tick_label.set_fontsize(8)
                tick_label.set_rotation(90)
            for tick_label in self.ax.yaxis.get_ticklabels():
                tick_label.set_fontsize(8)

            self.ax.axvline(x=0, color='black')
            self.ax.axhline(y=0, color='black')
            self.ax.grid()
            self.fig.tight_layout()
            self.canvas.draw()

        except ValueError as e:
            self.logger.warning(f"初始图形设置错误: {e}")

    def on_mouse_move(self, event):
        """鼠标移动事件处理"""
        if event.inaxes != self.ax:
            if self.annot.get_visible():
                self.annot.set_visible(False)
                self.canvas.draw_idle()
            return

        # 获取鼠标位置
        x, y = event.xdata, event.ydata

        # 寻找最近的曲线点
        min_distance = float('inf')
        closest_label = None
        closest_x = None
        closest_y = None

        for label, (x_data, y_data, line) in self.curve_data.items():
            if len(x_data) == 0 or len(y_data) == 0:
                continue

            # 计算距离
            distances = np.sqrt((np.array(x_data) - x) ** 2 + (np.array(y_data) - y) ** 2)
            min_idx = np.argmin(distances)
            distance = distances[min_idx]

            if distance < min_distance and distance < 0.1:  # 设置一个阈值
                min_distance = distance
                closest_label = label
                closest_x = x_data[min_idx]
                closest_y = y_data[min_idx]

        if closest_label is not None:
            # 更新标注文本
            if self.run_type == 'I-V':
                text = f"{closest_label}\nI: {closest_x:.3f} mA\nV: {closest_y:.3f} V"
            else:
                text = f"{closest_label}\nV: {closest_x:.3f} V\nI: {closest_y:.3f} mA"

            self.annot.xy = (closest_x, closest_y)
            self.annot.set_text(text)
            self.annot.get_bbox_patch().set_alpha(0.8)

            # 调整标注位置，避免超出画布
            xlim = self.ax.get_xlim()
            ylim = self.ax.get_ylim()
            x_range = xlim[1] - xlim[0]
            y_range = ylim[1] - ylim[0]

            # 使用范围信息来智能调整标注位置
            x_threshold = x_range * 0.1  # 使用x范围的10%作为阈值
            y_threshold = y_range * 0.1  # 使用y范围的10%作为阈值

            # 如果鼠标靠近右侧边界，标注显示在左侧
            if x > xlim[1] - x_threshold:
                x_offset = -40
            # 如果鼠标靠近左侧边界，标注显示在右侧
            elif x < xlim[0] + x_threshold:
                x_offset = 20
            else:
                # 默认根据鼠标位置决定
                x_offset = 20 if x < (xlim[0] + xlim[1]) / 2 else -40

            # 如果鼠标靠近上侧边界，标注显示在下侧
            if y > ylim[1] - y_threshold:
                y_offset = -40
            # 如果鼠标靠近下侧边界，标注显示在上侧
            elif y < ylim[0] + y_threshold:
                y_offset = 20
            else:
                # 默认根据鼠标位置决定
                y_offset = 20 if y < (ylim[0] + ylim[1]) / 2 else -40

            self.annot.xyann = (x_offset, y_offset)
            self.annot.set_visible(True)
            self.canvas.draw_idle()
        else:
            if self.annot.get_visible():
                self.annot.set_visible(False)
                self.canvas.draw_idle()

    def reset_status(self):
        """重置状态"""
        self.run_status = False

        # 启用所有控件
        widgets = [
            self.channel_entry, self.start_entry, self.end_entry,
            self.step_entry, self.limit_entry, self.sample_entry, self.label_entry,
            self.color_choose, self.clear_button, self.log_button, self.vi_button, self.iv_button
        ]

        for widget in widgets:
            if hasattr(widget, 'setEnabled'):
                widget.setEnabled(True)
            if hasattr(widget, 'setReadOnly') and hasattr(widget, 'isReadOnly'):
                widget.setReadOnly(False)

        self.vi_button.setText('V-I Start')
        self.iv_button.setText('I-V Start')

    def disable_btn_status(self):
        widgets = [
            self.channel_entry, self.start_entry, self.end_entry,
            self.step_entry, self.limit_entry, self.sample_entry, self.label_entry,
            self.color_choose, self.clear_button, self.log_button, self.vi_button, self.iv_button
        ]

        for widget in widgets:
            if hasattr(widget, 'setEnabled'):
                widget.setEnabled(False)
            if hasattr(widget, 'setReadOnly') and hasattr(widget, 'isReadOnly'):
                widget.setReadOnly(True)

    def run(self, run_type='I-V'):
        """运行测试"""
        if self.run_status:
            # 如果正在运行，则停止
            self.cancel_test()
            return

        if not self.connected or not self.device:
            QMessageBox.warning(self, "警告", "请先连接设备")
            return

        self.run_status = True
        self.run_type = run_type

        # 禁用控件
        self.disable_btn_status()

        if run_type == 'I-V':
            x_label = 'Current(mA)'
            y_label = 'Voltage(V)'
            self.iv_button.setEnabled(True)
            self.iv_button.setText('取消')
        else:
            x_label = 'Voltage(V)'
            y_label = 'Current(mA)'
            self.vi_button.setEnabled(True)
            self.vi_button.setText('取消')

        self.ax.set_title(self.run_type + ' Curves')
        self.ax.set_xlabel(x_label)
        self.ax.set_ylabel(y_label)
        self.apply_initial_setting()
        self.logger.info(
            f"start={self.start_entry.text()}, "
            f"end={self.end_entry.text()}, "
            f"step={self.step_entry.text()}, "
            f"limit={self.limit_entry.text()}"
        )

        self.logger.info("开始测试")
        self.test_times += 1
        label_name = self.label_entry.text()
        color_id = self.color_choose.currentIndex()
        while label_name == self.last_label or label_name in self.curve_data:
            label_name = f"polt-{self.test_times + 1}"
            color_id += 1
            if color_id >= len(Color_List):
                color_id = 0
        # 查找或创建线条
        if label_name not in self.curve_data:
            color = Color_List[color_id]
            line, = self.ax.plot([], [], color=color, label=label_name)
            self.current_lines.append(line)
            self.curve_data[label_name] = ([], [], line)
            self.ax.legend()
        self.last_label = label_name
        self.label_entry.setText(label_name)
        self.color_choose.setCurrentIndex(color_id)

        if self.new_turn:
            self.new_turn = False
            self.data_dir = self.data_path / "result" / datetime.now().strftime("%y_%m_%d_%H_%M_%S")
            self.logger.info(f"创建log目录:{self.data_dir}")
            os.makedirs(self.data_dir, exist_ok=True)
            os.makedirs(self.data_dir / "drive_log", exist_ok=True)

        drive_log_ptah = self.data_dir / "drive_log" / f'{label_name}.log'
        drive_log = create_logger(f"IVCurves.{label_name}", propagate=False, log_path=drive_log_ptah,
                                  time_rotating=False)

        # 准备测试数据
        settings = {
            'device': "N6700" if _check_device_type(self.name, self.n6700_list) else "B2900",
            'channel': self.channel_entry.currentText(),
            'start': self.start_entry.text(),
            'end': self.end_entry.text(),
            'step': self.step_entry.text(),
            'limit': self.limit_entry.text(),
            'sample_time': self.sample_entry.text()
        }

        # 创建并启动工作线程
        self.worker = TestWorker(device=self.device, run_type=run_type, settings=settings, parent=self,
                                 logger=drive_log)
        self.worker.progress.connect(self.on_test_progress)
        self.worker.finished.connect(self.on_test_finished)
        self.worker.start()

    def cancel_test(self):
        """取消测试"""
        self.disable_btn_status()
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(2000)  # 等待2秒让线程安全退出

        # self.run_status = False
        self.reset_status()
        if self.run_type == 'I-V':
            self.vi_button.setEnabled(False)
        else:
            self.iv_button.setEnabled(False)
        self.logger.info("测试已取消")

    def on_test_progress(self, voltage, current):
        """处理测试进度"""

        x_data, y_data, line = self.curve_data[self.last_label]

        if self.run_type == 'I-V':
            x_data.append(current)
            y_data.append(voltage)
        else:
            x_data.append(voltage)
            y_data.append(current)
        line.set_xdata(x_data)
        line.set_ydata(y_data)

        self.curve_data[self.last_label] = (x_data, y_data, line)

        self.fig.tight_layout()
        self.canvas.draw()

        # 处理GUI事件
        QApplication.processEvents()

    def on_test_finished(self, success, message):
        """测试完成处理"""
        self.save_test_data()
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            if message != "测试被取消":
                QMessageBox.warning(self, "警告", message)

        # self.run_status = False
        self.reset_status()
        if self.run_type == 'I-V':
            self.vi_button.setEnabled(False)
        else:
            self.iv_button.setEnabled(False)
        self.logger.info(f"测试完成: {message}")

    def save_test_data(self):
        """保存测试数据"""
        label_name = self.label_entry.text()

        # 保存CSV文件
        csv_name = self.data_dir / f'{label_name}_plot_points.csv'
        with open(csv_name, 'w', newline='') as station:
            writer = csv.writer(station, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)  # NOQA
            writer.writerow(['Points', 'Voltage(V)', 'Current(mA)'])

            # 从曲线数据中获取数据点
            if label_name in self.curve_data:
                x_data, y_data, _ = self.curve_data[label_name]
                for i, (x, y) in enumerate(zip(x_data, y_data)):
                    if self.run_type == 'I-V':
                        writer.writerow([i + 1, y, x])
                    else:
                        writer.writerow([i + 1, x, y])

        # 保存图片
        picture_name = self.data_dir / (self.run_type + " Curves.svg")
        self.fig.savefig(picture_name, dpi=300, format='svg')


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="IVCurves")
    window.show()
    sys.exit(app.exec())
