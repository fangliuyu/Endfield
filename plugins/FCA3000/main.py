
import csv
import logging
import statistics
import sys
import traceback
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Union, Optional

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import Qt, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel,
    QFrame, QVBoxLayout, QHBoxLayout, QComboBox,
    QPushButton, QCheckBox, QMessageBox, QFileDialog,
    QSizePolicy, QLineEdit, QDoubleSpinBox
)

from lib.customlog import create_logger
from lib.custommath import change_str_value_to_scale
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_fca3000 import FCA3000Agent, Instrument_Dryrun
from lib.deviceCheck import auto_connected, check_error
from lib.qtui.custom_widget import build_group_box, show_toast


class FreqWorker(QThread):
    """后台测量线程，防止界面卡死"""

    data_ready = Signal(float)  # value, timestamp
    error_occurred = Signal(str)

    def __init__(self, driver: FCA3000Agent, channel: int, unit: str):
        super().__init__()
        self.driver = driver
        self.channel = channel
        self.unit = unit
        self._is_running = True

    def run(self) -> None:
        while self._is_running and self.driver:
            val = self.driver.read_measurement(self.channel, self.unit)
            self.data_ready.emit(val)

    def stop(self) -> None:
        self._is_running = False


class MainWindow(QMainWindow):
    def __init__(
            self, name: str, version: str = '1.0.0', logger: logging.Logger = None, dry_run=False,
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
        self.devices_scan_list = get_device_patterns("FCA3000")
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[FCA3000Agent] = None
        self.connected = False
        self.channel = 1
        self.unit = "Hz"
        self.data_records = []
        self.measurement_active = False
        self.worker: Optional[FreqWorker] = None

        self.setWindowTitle(f"FCA3000系列直流电源分析仪控制器V{version}")
        self.resize(800, 600)

        main_widget = QFrame()
        main_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        main_layout.addStretch(1)

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
        save_pic_btn = QPushButton("界面截图")
        save_pic_btn.clicked.connect(self.device_save_pic)
        scan_layout.addWidget(save_pic_btn)

        settings_group, settings_layout = build_group_box("Setting", QVBoxLayout())
        main_layout.addWidget(settings_group)
        setting_box_layout = QHBoxLayout()
        setting_box_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        settings_layout.addLayout(setting_box_layout)
        setting_box_layout.setContentsMargins(0, 0, 0, 0)
        setting_box_layout.setSpacing(5)
        setting_box_layout.addWidget(QLabel("通道1:"))
        setting_box_layout.addWidget(QLabel("耦合:"))
        self.cmb1_coupling = QComboBox()
        self.cmb1_coupling.addItems(["AC", "DC"])
        setting_box_layout.addWidget(self.cmb1_coupling)
        setting_box_layout.addWidget(QLabel("阻抗:"))
        self.cmb1_impedance = QComboBox()
        self.cmb1_impedance.addItems(["50Ω", "1MΩ"])
        setting_box_layout.addWidget(self.cmb1_impedance)
        setting_box_layout.addStretch()
        setting_box_layout.addWidget(QLabel("通道2:"))
        setting_box_layout.addWidget(QLabel("耦合:"))
        self.cmb2_coupling = QComboBox()
        self.cmb2_coupling.addItems(["AC", "DC"])
        setting_box_layout.addWidget(self.cmb2_coupling)
        setting_box_layout.addWidget(QLabel("阻抗:"))
        self.cmb2_impedance = QComboBox()
        self.cmb2_impedance.addItems(["50Ω", "1MΩ"])
        setting_box_layout.addWidget(self.cmb2_impedance)

        setting_meas_layout = QHBoxLayout()
        settings_layout.addLayout(setting_meas_layout)
        setting_meas_layout.setContentsMargins(2, 2, 2, 2)
        setting_meas_layout.addStretch(1)
        setting_meas_layout.addWidget(QLabel("输入通道:"))
        self.cmb_channel = QComboBox()
        self.cmb_channel.addItems(["1", "2"])
        setting_meas_layout.addWidget(self.cmb_channel)
        setting_meas_layout.addStretch()
        setting_meas_layout.addWidget(QLabel("测量时间 (秒):"))
        self.time_value = QDoubleSpinBox(value=0.05, minimum=0.001, maximum=999)
        setting_meas_layout.addWidget(self.time_value)
        setting_meas_layout.addStretch()
        setting_meas_layout.addWidget(QLabel("预期频率:"))
        self.freq_input = QLineEdit("12.288")
        setting_meas_layout.addWidget(self.freq_input)
        self.freq_unit = QComboBox()
        self.freq_unit.addItems(["Hz", "KHz", "MHz", "GHz"])
        setting_meas_layout.addWidget(self.freq_unit)
        setting_meas_layout.addStretch(1)

        setting_btn_layout = QHBoxLayout()
        settings_layout.addLayout(setting_btn_layout)
        setting_btn_layout.setContentsMargins(2, 2, 2, 2)
        btn_apply_config = QPushButton("应用配置")
        btn_apply_config.setFont(QFont("", 18))
        btn_apply_config.clicked.connect(self.apply_config)
        setting_btn_layout.addWidget(btn_apply_config, 1)
        btn_reset_config = QPushButton("重置")
        btn_reset_config.setFont(QFont("", 18))
        btn_reset_config.clicked.connect(self.reset_config)
        setting_btn_layout.addWidget(btn_reset_config)

        measure_frame = QFrame()
        measure_frame.setMinimumWidth(400)
        measure_frame.setFrameStyle(QFrame.Shape.Box)
        measure_frame.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        measure_frame.setLineWidth(1)
        main_layout.addWidget(measure_frame, 1, alignment=Qt.AlignmentFlag.AlignCenter)
        measure_layout = QVBoxLayout()
        measure_layout.setContentsMargins(5, 5, 5, 5)
        measure_layout.setSpacing(0)
        measure_frame.setLayout(measure_layout)

        value_frame = QFrame()
        measure_layout.addWidget(value_frame, 1)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(5)
        value_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        value_frame.setLayout(value_row)
        self.lbl_value = QLineEdit("---.------")
        self.lbl_value.setStyleSheet("""
                    font-size: 32px; 
                    font-family: "", 'Courier New', monospace;
                    color: #2C3E50;
                    font-weight: bold;
                    padding: 10px;
                    border-radius: 5px;
                """)
        self.lbl_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.lbl_value.setReadOnly(True)
        self.lbl_value.setMinimumWidth(250)
        value_row.addStretch(2)
        value_row.addWidget(self.lbl_value, 1)
        self.lbl_unit = QLabel("Hz")
        self.lbl_unit.setMinimumWidth(40)
        self.lbl_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        self.lbl_unit.setStyleSheet("font-size: 24px; color: #7F8C8D;")
        value_row.addWidget(self.lbl_unit)
        value_row.addStretch(2)

        data_tittle_frame = QFrame()
        measure_layout.addWidget(data_tittle_frame, 1)
        data_tittle_layout = QHBoxLayout()
        data_tittle_layout.setContentsMargins(0, 0, 0, 0)
        data_tittle_layout.setSpacing(5)
        data_tittle_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_frame.setLayout(data_tittle_layout)
        label = QLabel("平均值")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_layout.addWidget(label, 1)
        label = QLabel("标准差")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_layout.addWidget(label, 1)
        label = QLabel("最小值")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_layout.addWidget(label, 1)
        label = QLabel("最大值")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_layout.addWidget(label, 1)
        label = QLabel("数据量")
        label.setMinimumWidth(50)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_tittle_layout.addWidget(label, 1)
        self.btn_clear = QPushButton("清除数据")
        self.btn_clear.clicked.connect(self.clear_data)
        data_tittle_layout.addWidget(self.btn_clear)

        data_value_frame = QFrame()
        measure_layout.addWidget(data_value_frame, 1)
        data_value_layout = QHBoxLayout()
        data_value_layout.setContentsMargins(0, 0, 0, 0)
        data_value_layout.setSpacing(5)
        data_value_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        data_value_frame.setLayout(data_value_layout)
        self.avg_value = QLineEdit("---.---")
        self.avg_value.setMinimumWidth(50)
        self.avg_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.avg_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.avg_value.setReadOnly(True)
        data_value_layout.addWidget(self.avg_value, 1)
        self.std_value = QLineEdit("---.---")
        self.std_value.setMinimumWidth(50)
        self.std_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.std_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.std_value.setReadOnly(True)
        data_value_layout.addWidget(self.std_value, 1)
        self.min_value = QLineEdit("---.---")
        self.min_value.setMinimumWidth(50)
        self.min_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.min_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.min_value.setReadOnly(True)
        data_value_layout.addWidget(self.min_value, 1)
        self.max_value = QLineEdit("---.---")
        self.max_value.setMinimumWidth(50)
        self.max_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.max_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.max_value.setReadOnly(True)
        data_value_layout.addWidget(self.max_value, 1)
        self.count_value = QLineEdit("------")
        self.count_value.setMinimumWidth(50)
        self.count_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.count_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.count_value.setReadOnly(True)
        data_value_layout.addWidget(self.count_value, 1)
        self.btn_save = QPushButton("保存数据")
        self.btn_save.clicked.connect(self.save_data)
        data_value_layout.addWidget(self.btn_save)

        btn_frame = QFrame()
        measure_layout.addWidget(btn_frame, 1)
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(5)
        btn_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn_frame.setLayout(btn_layout)
        btn_single = QPushButton("单次测量")
        btn_single.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                padding: 8px 16px;
                border: 1px solid rgba(0, 123, 255, 0.5);
                border-radius: 4px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        btn_single.clicked.connect(self.measure_single)
        btn_layout.addWidget(btn_single, 2)
        btn_layout.addStretch(1)
        self.btn_continue = QPushButton("持续采样")
        self.btn_continue.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                padding: 8px 16px;
                border: 1px solid rgba(0, 123, 255, 0.5);
                border-radius: 4px;
                font-size: 18px;
            }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        self.btn_continue.clicked.connect(self.measure_continue)
        btn_layout.addWidget(self.btn_continue, 2)

        main_layout.addStretch(1)

        self.refresh_devices_list()

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
            self.device = FCA3000Agent(instrument_address=self.devices_list[self.sn], logger=self.logger)
        self.device.connect(reset=True)
        self.btn_connect.setText("Disconnect")
        self.devices_box.setEnabled(False)
        self.connected = True

    @check_error
    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.devices_box.setEnabled(True)
            self.device = None
            self.connected = False

    @auto_connected
    def device_save_pic(self):
        if self.dryrun and "demo" in self.name:
            with open(Path(__file__).parent / "logo.png", 'rb') as img_file:
                img_data = img_file.read()
            file_name, _ = QFileDialog.getSaveFileName(self, "选择文件", self.pic_dir.as_posix(), "图片格式 (*.png)")
            if not file_name:
                return
            if not file_name.endswith('.png'):
                file_name += '.png'
        else:
            self.logger.info(f"正在截取屏幕")
            img_data = self.device.get_screen_image()
            file_name, _ = QFileDialog.getSaveFileName(self, "选择文件", self.pic_dir.as_posix(), "图片格式 (*.bmp)")
            if not file_name:
                return
            if not file_name.endswith('.bmp'):
                file_name += '.bmp'
        try:
            with open(file_name, 'wb') as pic_file:
                pic_file.write(img_data)
            self.logger.info(f"保存截图到: {file_name}")
            show_toast(self, f"截图已保存至:\n{file_name}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(self, "错误", f"截图保存失败{e}")

    @auto_connected
    def apply_config(self):
        self.logger.info("pending apply the user config")
        meas_time = float(self.time_value.text())
        self.device.set_meas_time(meas_time)
        self.channel = int(self.cmb_channel.currentText())
        self.unit = self.freq_unit.currentText()
        self.lbl_unit.setText(self.unit)
        compiling1 = self.cmb1_coupling.currentText()
        self.device.set_coupling(1, compiling1)
        impedance1 = self.cmb1_impedance.currentText()
        self.device.set_impedance(1, change_str_value_to_scale(impedance1))
        compiling2 = self.cmb2_coupling.currentText()
        self.device.set_coupling(2, compiling2)
        impedance2 = self.cmb2_impedance.currentText()
        self.device.set_impedance(2, change_str_value_to_scale(impedance2))

    @auto_connected
    def reset_config(self):
        self.logger.info("pending reset to default config")
        self.device.reset()
        self.time_value.setValue(0.05)
        self.cmb1_coupling.setCurrentText("DC")
        self.cmb1_impedance.setCurrentIndex(0)
        self.cmb2_coupling.setCurrentText("DC")
        self.cmb2_impedance.setCurrentIndex(0)
        self.freq_input.setText("12.288")
        self.freq_unit.setCurrentIndex(0)

    def clear_data(self):
        """清除数据"""
        self.data_records = []
        self._update_stats()
        self.btn_save.setEnabled(False)

    def save_data(self):
        """保存数据"""
        if not self.data_records:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "保存数据", "", "CSV文件 (*.csv)"
        )

        if path:
            try:
                with open(path, 'w', newline='', encoding='utf-8-sig') as save_file:
                    writer = csv.writer(save_file)
                    writer.writerow(["Info", "SN"])
                    writer.writerow([self.name, self.sn])
                    writer.writerow(["Timestamp", "value", "Unit"])
                    for record in self.data_records:
                        writer.writerow([
                            record["timestamp"].strftime("%Y-%m-%d %H:%M:%S.%f"),
                            record["value"],
                            record["Unit"]
                        ])
                QMessageBox.information(self, "保存成功", f"数据已保存至 {path}")
            except Exception as e:
                QMessageBox.critical(self, "保存失败", f"保存错误: {e}")

    @auto_connected
    def measure_single(self):
        """单次测量"""
        if not self.connected:
            return
        value = self.device.read_measurement(self.channel, self.unit)
        self._handle_measurement_data(value)

    @auto_connected
    def measure_continue(self):
        """切换连续测量"""
        if not self.connected:
            return
        if not self.measurement_active:
            self.measurement_active = True
            self.btn_continue.setText("停止测量")
            self.worker = FreqWorker(self.device, self.channel, self.unit)
            self.worker.data_ready.connect(self._handle_measurement_data)
            self.worker.error_occurred.connect(self._handle_measurement_error)
            self.worker.start()
            self.logger.info("开始频率测量（线程模式）")
        else:
            self.measurement_active = False
            self.btn_continue.setText("持续采样")
            if self.worker:
                self.worker.stop()
                self.worker.wait(1000)
                self.worker = None
            self.logger.info("停止频率测量")

    def _handle_measurement_data(self, value: float):
        self._display_value(value)
        self._record_data(value)

    def _handle_measurement_error(self, error_msg: str) -> None:
        """处理测量错误"""
        self.logger.error(f"测量失败: {error_msg}")
        QMessageBox.information(self, "错误", f"测量值获取失败: {error_msg}")
        if self.measurement_active:
            self.measurement_active = False
            self.btn_continue.setText("开始测量")
            if self.worker:
                self.worker.stop()
                self.worker.wait(1000)
                self.worker = None
            self.logger.info("停止频率测量")

    def _display_value(self, value: float):
        """显示测量值"""
        self.lbl_value.setText(f"{value:.6f}")

    def _record_data(self, value: float) -> None:
        """记录数据"""
        record = {
            "timestamp": datetime.now(),
            "value": value,
            "Unit": self.unit
        }
        self.data_records.append(record)
        self.btn_save.setEnabled(True)
        self._update_stats()

    def _update_stats(self) -> None:
        """更新统计信息"""
        if not self.data_records:
            self.avg_value.setText("---.---")
            self.std_value.setText("---.---")
            self.min_value.setText("---.---")
            self.max_value.setText("---.---")
            self.count_value.setText("---.---")
            return

        values = [r["value"] for r in self.data_records]
        avg = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0

        self.avg_value.setText("%6f" % avg)
        self.std_value.setText("%6f" % std)
        self.min_value.setText("%6f" % min(values))
        self.max_value.setText("%6f" % max(values))
        self.count_value.setText("%d" % len(values))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow("FCA3000")
    window.show()
    sys.exit(app.exec())
