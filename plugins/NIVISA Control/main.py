import logging
import sys
from datetime import datetime
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Optional, Union

from PySide6.QtGui import Qt, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFrame, QSizePolicy, QVBoxLayout, QHBoxLayout, QComboBox, QPushButton, QCheckBox,
    QPlainTextEdit, QTextEdit, QLineEdit, QSpinBox
)

from lib.customlog import create_logger
from lib.deviceCheck import check_error, auto_connected
from lib.instruments.instrument import Instrument, Instrument_Dryrun, get_device_list, check_device_module
from lib.qtui.custom_widget import show_toast

Base_Command = [
    "*IDN?",
    "*RST",
    "*CLS",
    "*OPC?",
    "TST?",
    "*WAI"
]


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
        self.dry_run = dryrun
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
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[Instrument] = None
        self.connected = False

        self.setWindowTitle(f"{name} V{version}")
        self.resize(800, 600)

        self.setAutoFillBackground(True)
        self.palette = self.palette()
        self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
        self.setPalette(self.palette)

        main_widget = QFrame()
        main_widget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
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
        self.dryrun_box.setChecked(self.dry_run)
        self.dryrun_box.stateChanged.connect(self.switch_dryrun)
        scan_layout.addWidget(self.dryrun_box)

        history_layout = QHBoxLayout()
        history_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(history_layout)
        history_layout.addWidget(QLabel("TimeOut"))
        self.timeout_input = QSpinBox(minimum=1, maximum=1_000_000_000)
        self.timeout_input.setMinimumWidth(20)
        self.timeout_input.setValue(3000)
        history_layout.addWidget(self.timeout_input)
        history_layout.addWidget(QLabel("ms"))
        apply_btn = QPushButton("Set")
        apply_btn.clicked.connect(self.set_timeout)
        history_layout.addWidget(apply_btn)
        history_layout.addStretch()
        history_layout.addWidget(QLabel("history"))
        self.history_box = QComboBox()
        self.history_box.addItems(Base_Command)
        history_layout.addWidget(self.history_box)

        cmd_layout = QHBoxLayout()
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setAlignment(Qt.AlignmentFlag.AlignRight)
        main_layout.addLayout(cmd_layout)
        self.cmd_input = QPlainTextEdit()
        self.cmd_input.setMaximumBlockCount(1)
        self.cmd_input.setPlaceholderText("请输入指令")
        self.cmd_input.setFixedHeight(60)
        cmd_layout.addWidget(self.cmd_input, 1)
        cmd_send_btn = QPushButton("Send")
        cmd_send_btn.clicked.connect(self.send_command)
        cmd_layout.addWidget(cmd_send_btn)

        return_layout = QHBoxLayout()
        return_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addLayout(return_layout)
        self.return_value = QLineEdit()
        self.return_value.setReadOnly(True)
        return_layout.addWidget(self.return_value, 1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clr_data)
        return_layout.addWidget(self.clear_btn)

        self.data_txt = QTextEdit()
        self.data_txt.setReadOnly(True)
        main_layout.addWidget(self.data_txt, 1)

        self.history_box.currentTextChanged.connect(self.update_cmd_box)
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
            _, class_name, sn = check_device_module(address)
            self.logger.debug(f"{index}.{sn}: {class_name}")
            sn_list.append(class_name + ": " + sn)
            self.devices_list[sn] = address
        self.logger.info(f"当前识别到了{len(sn_list)-1}个仪器")
        if self.dry_run:
            sn_list.append("KeysightTechnologiesN6705C(demo): MY114514")
            self.devices_list["MY114514"] = "USB0::0x2A8D::0x0F02::MY11551419::INSTR"
        sn_list.append("刷新列表")
        self.devices_box.addItems(sn_list)
        self.devices_box.setCurrentText("")
        self.sn = ""

    def switch_dryrun(self):
        self.dry_run = not self.dry_run
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
        if self.dry_run and "demo" in self.name:
            self.device = Instrument_Dryrun(instrument_address=self.devices_list[self.sn], logger=self.logger)
        else:
            self.device = Instrument(instrument_address=self.devices_list[self.sn], logger=self.logger)
        self.device.connect(reset=False)
        self.btn_connect.setText("Disconnect")
        self.devices_box.setEnabled(False)
        self.palette.setColor(self.backgroundRole(), QColor("#B1D85C"))
        self.setPalette(self.palette)
        self.connected = True

    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.devices_box.setEnabled(True)
            self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
            self.setPalette(self.palette)
            self.device = None
            self.connected = False

    @auto_connected
    def set_timeout(self):
        timeout = self.timeout_input.value()
        self.device.set_timeout(timeout)
        show_toast(self, "应用成功")

    @auto_connected
    def send_command(self):
        ts = datetime.now().strftime("[%H:%M:%S.%f]")
        command = self.cmd_input.toPlainText().strip()
        self.data_txt.append(f"{ts} -> {command}")
        return_value = self.device.send_command(command, check_errors=True)
        if return_value:
            self.return_value.setText(return_value)
            self.data_txt.append(f"{ts} <- {return_value}")

    def clr_data(self):
        self.return_value.setText("")
        self.data_txt.clear()

    def update_cmd_box(self, txt: str):
        self.cmd_input.setPlainText(txt)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="example")
    window.show()
    sys.exit(app.exec())
