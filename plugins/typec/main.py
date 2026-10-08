import logging
import os
import shutil
import subprocess
import sys
import time
import traceback
from collections import OrderedDict
from datetime import datetime
from os import PathLike
from pathlib import Path
from threading import Event
from typing import Optional, Union

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QComboBox, QFileDialog,
    QPlainTextEdit, QMessageBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSpinBox, QLineEdit, QDoubleSpinBox, QCheckBox,
)
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor

from lib.customlog import create_logger
from lib.filetools import read_data_from_yaml, save_data_to_yaml
from lib.custommath import set_value_to_scale_str, change_str_value_to_scale
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_dmm import DmmAgent, Instrument_Dryrun, MeasurementFunction
from lib.uartSerial.SerialAgent import UARTSerial
from lib.uartSerial.scan import get_serial_bauds_str, get_serial_ports

from plugins.typec.excel import read_xlsx_file, save_data_to_xlsx

ITEM_TO_FUNC = {
    "Resistance": MeasurementFunction.RESISTANCE_2W,
    "4WImpedance": MeasurementFunction.RESISTANCE_4W,
    "Diode": MeasurementFunction.DIODE,
    "Capacitance": MeasurementFunction.CAPACITANCE,
    "Continuity": MeasurementFunction.CONTINUITY,
    "Frequency": MeasurementFunction.FREQUENCY,
    "Period": MeasurementFunction.PERIOD,
    "Voltage": MeasurementFunction.DC_VOLTAGE,
    "Current": MeasurementFunction.DC_CURRENT,
    "Temperature": MeasurementFunction.TEMPERATURE,
}

DEFAULT_CONFIG = {
    "device": {"com": "", "baud": 115200, "dmm": ""},
    "value": {"max_Mohm": 500, "offset_ohm": 0, "decimals": 1, "sample_s": 3},
    "config": {"csv_path": "", "log_path": ""},
}


def _check_limits(value: float, low: str, up: str, ol_mohm: float) -> str:
    if not low and not up:
        return "OK"
    if low == "OL" or up == "OL":
        return "OK" if value >= ol_mohm else "NG"
    try:
        lo = change_str_value_to_scale(low) if low else -float('inf')
        hi = change_str_value_to_scale(up) if up else float('inf')
        return "OK" if lo <= value <= hi else "NG"
    except Exception as e:
        print(str(e))
        try:
            return "OK" if eval(low) <= value <= eval(up) else "NG"
        except Exception as e:
            print(str(e))
            return "NG"


class BuildTestThread(QThread):
    finished = Signal(tuple)  # type, message
    command_signal = Signal(str)
    treeview_signal = Signal(dict)

    def __init__(
            self, event: Event, result_path: Path, logger: logging.Logger,
            test_sequence: OrderedDict, serial: UARTSerial, dmm: DmmAgent,
            setting: dict,
    ):
        super().__init__()
        self.thread_event = event
        self.logger = logger
        self.result_path = result_path
        self.test_sequence = test_sequence
        self.serial = serial
        self.dmm = dmm
        self.setting = setting

    def run(self):
        try:
            self.run_commands()
            self.finished.emit(("finish", "测试完成"))
        except Exception as e:
            self.finished.emit(("error", str(e)))

    def run_commands(self) -> str:
        final_state = "PASS"
        result_header = ['NO', 'Item', 'SubTest', 'DMM Item', 'Measure1', 'Measure2', 'Measure3', 'Lower_limit', 'Avg.',
                         'Upper_limit', 'Status']
        result_data = [result_header]
        try:
            current_index = 0
            index_list = list(self.test_sequence.keys())
            table_length = len(index_list)
            last_item = ""
            while current_index < table_length:
                if self.thread_event.wait(0.01):
                    break

                index = index_list[current_index]
                row_data = self.test_sequence[index]

                # 实际执行命令的逻辑
                try:
                    result = self.execute_command(row_data, last_item)
                    last_item = row_data["DMM Item"]
                except Exception as e:
                    self.logger.error(str(e))
                    self.logger.error(traceback.format_exc())
                    break

                # 更新UI显示结果
                self.treeview_signal.emit(result)

                result_data.append([
                    result["No"],
                    result["Item"],
                    result["SubTest"],
                    result["DMMItem"],
                    result["Measure1"],
                    result["Measure2"],
                    result["Measure3"],
                    result["LowerLimit"],
                    result["Avg."],
                    result["UpperLimit"],
                    result["Status"],
                ])

                final_state = result["Status"]
                current_index += 1

            if len(result_data) < table_length:
                final_state = "FAIL"
        except Exception as e:
            final_state = "Broke"
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())

        try:
            save_data_to_xlsx(
                self.result_path / 'Result.xlsx',
                result_data, result_header.index("Status"), "FAIL",
                result_header.index("SubTest")
            )
            self.rename_result_folder(final_state)
        except Exception as e:
            final_state = "Broke"
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())

        return final_state

    def execute_command(self, row_data, last_item: str):
        decimals = self.setting.get("Decimals")
        sample_s = self.setting.get("SampleTime")
        ol_mohm = float(self.setting.get("OL")) * 1e6
        offset_ohm = float(self.setting.get("Offset"))
        net = row_data["Item"].strip()
        name = row_data["SubTest"].strip()
        item = row_data['DMM Item'].strip()
        command = row_data['Command'].strip()
        up = row_data['LowerLimit'].strip()
        lo = row_data['UpperLimit'].strip()

        result = {
            "No": row_data["Sequence"],
            "Item": net,
            "SubTest": name,
            "DMMItem": item,
            "Measure1": "",
            "Measure2": "",
            "Measure3": "",
            "LowerLimit": lo,
            "Avg.": "",
            "UpperLimit": up,
            "Status": "OK",
        }

        delay = 100 / 1000
        try:
            for cmd in command.split('\n'):
                cmd = cmd.rstrip()
                self.command_signal.emit(f"send command: {cmd}")
                return_data = self.serial.send_with_response(cmd, delay).strip()
                self.command_signal.emit(f"receive data: {return_data}")
        except Exception as e:
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
            result["Avg."] = f"send command fial: {item}"
            result["Status"] = "NG"
            return result

        time.sleep(sample_s)

        if not item:
            self.logger.warning(f"不进行测量,跳过读取数值")
            result["Status"] = "OK"
            return result
        func = ITEM_TO_FUNC.get(item)
        if not func:
            self.logger.warning(f"未知测试项: {item}")
            result["Avg."] = f"Unkown {item}"
            result["Status"] = "NG"
            return result

        if not (item == last_item):
            self.logger.info(f"DMM切换至{item}")
            self.dmm.set_measurement_function(func.value)

        avg_val = 0.0
        values = ["", "", "", ""]
        for i in range(3):
            time.sleep(delay)
            try:
                val = self.dmm.read_measurement()
            except Exception as e:
                self.logger.error(f"DMM读取失败: {e}")
                val = 0.0

            self.command_signal.emit(f"DMM[{net}]{name} {item}: {val}")

            avg_val += val
            dmm_result = val - offset_ohm if "Resistance" in item else val
            if dmm_result > ol_mohm:
                dmm_result = "OL"
            else:
                dmm_result = set_value_to_scale_str(dmm_result, decimals)
            values[i] = dmm_result

        avg_val /= 3
        if avg_val > ol_mohm:
            values[3] = "OL"
        else:
            values[3] = set_value_to_scale_str(avg_val, decimals)
        self.command_signal.emit(f"DMM[{net}]{name} {item} avg: {values[3]}")

        # Check limits
        state = _check_limits(avg_val, lo, up, ol_mohm)
        result["Measure1"] = values[0]
        result["Measure2"] = values[1]
        result["Measure3"] = values[2]
        result["Avg."] = values[3]
        result["Status"] = state
        return result

    def rename_result_folder(self, result: str):
        new_name = self.result_path.name + "_" + result
        new_folder = self.result_path.with_name(new_name)
        self.result_path = self.result_path.rename(new_folder)


class TypecTesterWidget(QWidget):
    def __init__(self, data_path: Path, logger: logging.Logger, dryrun: bool = False, parent=None):
        super().__init__(parent)
        self.data_path = data_path
        self.logger = logger
        self.dryrun = dryrun

        self.devices_scan_list = get_device_patterns("dmm")

        self.command_file_path = self.data_path / "default_test.xlsx"
        self.setting_file = self.data_path / ".setting.yaml"
        self.result_folder = self.data_path / "result"
        self.result_path = self.result_folder

        self.cfg:  dict[str, any] = DEFAULT_CONFIG
        self.serial: Optional[UARTSerial] = None
        self.dmm_devices_list = {}
        self.dmm_name = ""
        self.dmm_sn = ""
        self.dmm_connected = False
        self.dmm: Optional[DmmAgent] = None

        self.command_row_data = OrderedDict()

        self.run_status = False
        self.run_thread: Optional[BuildTestThread] = None
        self.thread_event = Event()

        # ── UI ──────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # -- Top config panel --
        cfg_panel = QFrame()
        cfg_panel.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(cfg_panel)
        cfg_grid = QVBoxLayout(cfg_panel)
        cfg_grid.setSpacing(0)

        driver_frame = QHBoxLayout()
        cfg_grid.addLayout(driver_frame)
        driver_frame.addWidget(QLabel("TyRay COM:"))
        self.com_combo = QComboBox()
        self.com_combo.setEditable(False)
        self.com_combo.currentTextChanged.connect(self.choose_serial_list)
        driver_frame.addWidget(self.com_combo, 2)
        driver_frame.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(get_serial_bauds_str())
        self.baud_combo.setEditable(True)
        self.baud_combo.setCurrentText("115200")
        driver_frame.addWidget(self.baud_combo)
        driver_frame.addStretch(1)
        driver_frame.addWidget(QLabel("DMM:"))
        self.dmm_devices = QComboBox()
        self.dmm_devices.setEditable(False)
        self.dmm_devices.currentTextChanged.connect(self.choose_dmm_list)
        driver_frame.addWidget(self.dmm_devices, 2)
        self.dryrun_box = QCheckBox("dryrun")
        self.dryrun_box.setChecked(dryrun)
        self.dryrun_box.stateChanged.connect(self.switch_dryrun)
        driver_frame.addWidget(self.dryrun_box)

        config_frame = QHBoxLayout()
        cfg_grid.addLayout(config_frame)
        config_frame.addWidget(QLabel("Test Config:"))
        self.csv_path_edit = QLineEdit()
        self.csv_path_edit.setReadOnly(True)
        config_frame.addWidget(self.csv_path_edit, 1)
        self.btn_csv = QPushButton("...")
        self.btn_csv.clicked.connect(self.choose_config)
        config_frame.addWidget(self.btn_csv)

        setting_frame = QHBoxLayout()
        cfg_grid.addLayout(setting_frame)
        setting_frame.addWidget(QLabel("OL Limit:"))
        self.ol_limit = QDoubleSpinBox()
        self.ol_limit.setRange(0, 1e6)
        self.ol_limit.setValue(500)
        self.ol_limit.setSuffix(" Mohm")
        setting_frame.addWidget(self.ol_limit)
        setting_frame.addStretch()
        setting_frame.addWidget(QLabel("Offset:"))
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-1e6, 1e6)
        self.offset.setSuffix(" ohm")
        setting_frame.addWidget(self.offset)
        setting_frame.addStretch()
        setting_frame.addWidget(QLabel("小数位:"))
        self.decimals = QSpinBox()
        self.decimals.setRange(0, 6)
        self.decimals.setValue(1)
        setting_frame.addWidget(self.decimals)
        setting_frame.addStretch()
        setting_frame.addWidget(QLabel("采样时间:"))
        self.sample_time = QDoubleSpinBox()
        self.sample_time.setRange(0.1, 60)
        self.sample_time.setValue(3)
        self.sample_time.setSuffix(" s")
        setting_frame.addWidget(self.sample_time)
        setting_frame.addStretch()
        btn_open = QPushButton("打开结果")
        btn_open.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        btn_open.clicked.connect(self.open_result)
        setting_frame.addWidget(btn_open)
        setting_frame.addStretch()
        self.btn_test = QPushButton("开始测试")
        self.btn_test.setStyleSheet("font-size: 18px; font-weight: bold; padding: 10px;")
        self.btn_test.clicked.connect(self.toggle_test)
        setting_frame.addWidget(self.btn_test)

        # Right: terminal
        term_frame = QFrame()
        term_frame.setFixedHeight(150)
        term_frame.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(term_frame)
        term_layout = QVBoxLayout(term_frame)
        term_layout.setContentsMargins(2, 2, 2, 2)
        term_layout.setSpacing(0)
        self.term_rx = QPlainTextEdit()
        self.term_rx.setReadOnly(True)
        self.term_rx.setMaximumBlockCount(500)
        self.term_rx.setStyleSheet("font-family: 'Courier New', monospace; font-size: 11px;")
        term_layout.addWidget(self.term_rx, 1)
        self.term_tx = QLineEdit()
        self.term_tx.setPlaceholderText("输入指令按回车发送...")
        self.term_tx.returnPressed.connect(self.send_terminal_command)
        term_layout.addWidget(self.term_tx)

        # -- Tree table --
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([
            "No", "Net", "Name", "Item",
            "Low", "Value", "High", "Status"
        ])
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.setAlternatingRowColors(True)
        layout.addWidget(self.tree, 1)

        self.refresh_serial_list()
        self.refresh_dmm_list()
        self.load_ui_config()

    def deleteLater(self, /):
        if self.run_status:
            self.stop_test()
        self.save_ui_config()

    def closeEvent(self, event):
        if self.run_status:
            self.stop_test()
        self.save_ui_config()
        event.accept()

    def choose_serial_list(self):
        self.com_combo.blockSignals(True)
        current_text = self.com_combo.currentText()
        if current_text == "刷新列表":
            self.refresh_serial_list()
        self.com_combo.blockSignals(False)

    def refresh_serial_list(self):
        if self.serial and self.serial.is_connected:
            self.serial.disconnect()
            self.serial = None
        self.com_combo.clear()
        serial_com_scan = [""]
        if sys.platform == 'win32':
            serial_com_scan += [com.name for com in get_serial_ports()]
        else:
            serial_com_scan += [f'/dev/{com.name}' for com in get_serial_ports()]
        serial_com_scan.append("刷新列表")
        self.com_combo.addItems(serial_com_scan)
        self.com_combo.setCurrentText("")

    def choose_dmm_list(self):
        self.dmm_devices.blockSignals(True)
        current_text = self.dmm_devices.currentText()
        if current_text != "刷新列表":
            info = current_text.split(": ")
            self.dmm_name = info[0]
            self.dmm_sn = info[1]
            self.logger.info(f"用户选择了DMM: {info}")
        else:
            self.refresh_dmm_list()
        self.dmm_devices.blockSignals(False)

    def refresh_dmm_list(self):
        if self.dmm and self.dmm_connected:
            self.disconnect_dmm()
        self.logger.info(f"开始刷新dmm列表")
        self.dmm_devices_list = {}
        self.dmm_devices.clear()
        devices = get_device_list()
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
            sn_list.append(f"KeysightTechnologies34465A(demo): MY114514")
            self.dmm_devices_list[f"MY114514"] = f"USB0::0x2A8D::0x0101::MY114514:INSTR"
        sn_list.append("刷新列表")
        self.dmm_devices.addItems(sn_list)
        self.dmm_devices.setCurrentText("")
        self.dmm_sn = ""
        self.dmm_name = ""

    def switch_dryrun(self):
        self.dryrun = not self.dryrun
        self.refresh_dmm_list()

    def connect_dmm(self):
        if self.dmm_sn == "":
            return
        if "demo" in self.dmm_name:
            self.logger.info("enter DEMO device.")
            self.dmm = Instrument_Dryrun(self.dmm_devices_list[self.dmm_sn], logger=self.logger)
        else:
            self.dmm = DmmAgent(self.dmm_devices_list[self.dmm_sn], logger=self.logger)
        self.dmm.connect()
        self.dmm_connected = True

    def disconnect_dmm(self):
        if self.dmm and self.dmm_connected:
            self.dmm.disconnect()
            self.dmm = None
            self.dmm_connected = False

    def load_ui_config(self):
        if self.setting_file.exists():
            self.cfg = read_data_from_yaml(self.setting_file)
        d = self.cfg["device"]
        self.com_combo.setCurrentText(d.get("com", ""))
        self.baud_combo.setCurrentText(str(d.get("baud", 115200)))
        self.dmm_devices.setCurrentText(d.get("dmm", ""))
        v = self.cfg["value"]
        self.ol_limit.setValue(float(v.get("max_Mohm", 500)))
        self.offset.setValue(float(v.get("offset_ohm", 0)))
        self.decimals.setValue(int(v.get("decimals", 1)))
        self.sample_time.setValue(float(v.get("sample_s", 3)))
        c = self.cfg["config"].get("csv_path", "")
        if c == "":
            c = self.command_file_path.as_posix()
        self.csv_path_edit.setText(c)

    def save_ui_config(self):
        self.cfg["device"] = {
            "com": self.com_combo.currentText(),
            "baud": int(self.baud_combo.currentText() or 115200),
            "dmm": self.dmm_devices.currentText(),
        }
        self.cfg["value"] = {
            "max_Mohm": self.ol_limit.value(),
            "offset_ohm": self.offset.value(),
            "decimals": self.decimals.value(),
            "sample_s": self.sample_time.value(),
        }
        self.cfg["config file"] = self.csv_path_edit.text()
        save_data_to_yaml(self.cfg, self.setting_file)

    def open_result(self):
        if self.result_path:
            if sys.platform == 'win32':
                os.startfile(self.result_path)
            else:
                subprocess.run(['open', self.result_path])

    def choose_config(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择测试文件", self.data_path.as_posix(),
                                              "Ecexl File (*.xlsx);;所有文件 (*)")
        if path:
            self.csv_path_edit.setText(path)

    def send_terminal_command(self):
        cmd = self.term_tx.text().strip()
        if not cmd:
            return
        self.term_tx.clear()
        if not self.serial or not self.serial.is_connected:
            self.serial = UARTSerial(self.com_combo.currentText(), int(self.baud_combo.currentText()))
            self.serial.connect()
        resp = self.serial.send_with_response(cmd, timeout=0.5)
        self.log_rx(f">{cmd}\n{resp}")
        self.serial.disconnect()
        self.serial = None

    def log_rx(self, msg: str):
        self.term_rx.appendPlainText(msg)
        self.term_rx.verticalScrollBar().setValue(self.term_rx.verticalScrollBar().maximum())

    def toggle_test(self):
        if self.run_status:
            self.stop_test()
            return

        # Validate
        if not self.csv_path_edit.text() or not os.path.exists(self.csv_path_edit.text()):
            QMessageBox.warning(self, "提示", "请选择有效的CSV测试文件")
            return
        if not self.com_combo.currentText():
            QMessageBox.warning(self, "提示", "请选择TyRay串口")
            return
        if not self.dmm_devices.currentText():
            QMessageBox.warning(self, "提示", "请选择DMM")
            return

        # Read test list
        self.command_row_data = read_xlsx_file(self.csv_path_edit.text())
        if not self.command_row_data:
            QMessageBox.warning(self, "提示", "CSV文件为空或格式错误")
            return

        try:
            # Connect serial
            self.logger.info("连接TyRay板子...")
            self.serial = UARTSerial(
                port=self.com_combo.currentText(),
                baud_rate=int(self.baud_combo.currentText() or 115200),
                timeout=1.0,
            )
            if not self.serial.connect():
                QMessageBox.warning(self, "错误", "串口连接失败")
                return

            # Connect DMM
            self.logger.info("连接DMM...")
            self.connect_dmm()

        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.warning(self, "连接设备失败", str(e))
            return

        setting = {
            "OL": self.ol_limit.value(),
            "Offset": self.offset.value(),
            "SampleTime": self.sample_time.value(),
            "Decimals": self.decimals.value(),
        }

        self.run_status = True
        self.btn_test.setText("停止测试")
        self.tree.clear()

        # Create log dir
        self.result_path = self.result_path / datetime.now().strftime("%y_%m_%d_%H_%M_%S")
        self.result_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"日志目录: {self.result_path}")

        self.run_thread = BuildTestThread(
            event=self.thread_event, logger=self.logger,
            result_path=self.result_path, test_sequence=self.command_row_data,
            serial=self.serial, dmm=self.dmm, setting=setting,
        )
        self.run_thread.finished.connect(self.update_ui_result)
        self.run_thread.command_signal.connect(self.log_rx)
        self.run_thread.treeview_signal.connect(self.append_tree_row)

        self.run_thread.start()

    def stop_test(self):
        self.run_status = False
        self.thread_event.set()
        while self.run_thread.wait(1):
            pass
        self.btn_test.setText("开始测试")
        self._cleanup_connections()

    def update_ui_result(self, info: tuple):
        self.run_status = False
        self.btn_test.setText("开始测试")
        self._cleanup_connections()
        QMessageBox.information(self, info[0], info[1])

    def append_tree_row(self, data: dict):
        item_widget = QTreeWidgetItem(
            [
                data["No"],
                data["Item"],
                data["SubTest"],
                data["DMMItem"],
                data["LowerLimit"],
                data["Avg."],
                data["UpperLimit"],
                data["Status"],
            ]
        )
        if data["Status"] == "NG":
            for c in range(item_widget.columnCount()):
                item_widget.setForeground(c, QColor("red"))
        self.tree.addTopLevelItem(item_widget)
        self.tree.scrollToBottom()

    def _cleanup_connections(self):
        try:
            if self.dmm:
                self.dmm.disconnect()
        except Exception as e:
            self.logger.warning(f"DMM断开异常: {e}")
        try:
            if self.serial:
                self.serial.disconnect()
        except Exception as e:
            self.logger.warning(f"串口断开异常: {e}")
        self.dmm = None
        self.serial = None


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: logging.Logger = None,
                 data_path: Union[PathLike[str], str, None] = None, dryrun: bool = False, *args, **kwargs):
        super().__init__()
        self.widget_name = name
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
            self.logger = create_logger(name="TypeC tester", level=logging.DEBUG, log_path=log_path)
        self.logger.info("TypeC tester logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        # Initialize variables
        result_folder = self.data_path / "result"
        if not result_folder.exists():
            result_folder.mkdir()
        if not (self.data_path / "default_test.xlsx").exists():
            self.logger.info("default_test不存在,将创建该文件")
            shutil.copy2(Path(__file__).parent / "default_test.xlsx", self.data_path)

        self.setWindowTitle(f"Type-C Tester V{version}")
        self.resize(1200, 700)

        self.tester = TypecTesterWidget(data_path=self.data_path, logger=self.logger, dryrun=dryrun)
        self.setCentralWidget(self.tester)

    def deleteLater(self, /):
        self.tester.deleteLater()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        self.tester.deleteLater()
        self.logger.info(f"{self.widget_name}窗口关闭")
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="TypeC tester", version="2.1.5", dryrun=True)
    window.show()
    sys.exit(app.exec())
