import logging
import sys
import traceback
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Union, Optional

import serial
from PySide6.QtCore import QTimer
from PySide6.QtGui import Qt, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFrame, QSplitter, QVBoxLayout,
    QSizePolicy, QHBoxLayout, QPushButton, QCheckBox, QComboBox,
    QTextEdit, QSpinBox, QTableWidget, QHeaderView, QLCDNumber, QFileDialog, QMessageBox, QTableWidgetItem
)

from lib.customlog import create_logger
from lib.deviceCheck import check_error
from lib.uartSerial.scan import get_serial_ports, get_serial_bauds_str
from lib.uartSerial.QtSerial import UARTSerial
from lib.filetools import save_data_to_yaml, read_data_from_yaml


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: logging.Logger = None,
                 data_path: Union[PathLike[str], str, None] = None, *args, **kwargs):
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
            self.logger = create_logger(name=name, level=logging.DEBUG, log_path=log_path)
        self.logger.info(f"{name} logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        # Initialize variables
        self.setting_file = self.data_path / ".setting.yaml"
        self.serial: Optional[UARTSerial] = None
        self.cmd_treeview_showed = False
        self.sent_count_value = 0
        self.recv_count_value = 0
        self.loop_running = False
        self.loop_send_remaining = 0
        self.auto_save_file: Optional[Path] = None
        self.cmd_loop_running = False
        self.cmd_loop_remaining = 0
        self.cmd_loop_index = 0
        self.cmd_loop_round = 0

        # 设置窗口标题和大小
        self.setWindowTitle(f'{name} V{version}')
        self.resize(500, 400)
        main_widget = QFrame()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        txt_layout = QVBoxLayout()
        txt_layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(txt_layout, 5)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(0, 0, 0, 0)
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        txt_layout.addWidget(splitter, 1)

        self.rx_txt = QTextEdit()
        self.rx_txt.setReadOnly(True)
        self.rx_txt.setFont(QFont("Arial"))
        self.rx_txt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        splitter.addWidget(self.rx_txt)

        self.cmd_treeview = QFrame()
        splitter.addWidget(self.cmd_treeview)
        splitter.setStretchFactor(0, 1)

        treeview_layout = QVBoxLayout(self.cmd_treeview)
        treeview_layout.setContentsMargins(0, 0, 0, 0)

        treeview_setting_layout = QHBoxLayout()
        treeview_setting_layout.setContentsMargins(0, 0, 0, 0)
        treeview_layout.addLayout(treeview_setting_layout)
        import_btn = QPushButton("导入ini")
        import_btn.clicked.connect(self.import_ini)
        treeview_setting_layout.addWidget(import_btn)
        add_row_btn = QPushButton("+")
        add_row_btn.setFixedWidth(30)
        add_row_btn.clicked.connect(self.add_cmd_row)
        treeview_setting_layout.addWidget(add_row_btn)
        treeview_setting_layout.addStretch()
        self.cmd_loop_en = QCheckBox("顺序执行")
        self.cmd_loop_en.stateChanged.connect(self.on_cmd_loop_changed)
        treeview_setting_layout.addWidget(self.cmd_loop_en)
        self.cmd_loop_count = QSpinBox(minimum=1, maximum=1_000)
        self.cmd_loop_count.setMinimumWidth(10)
        self.cmd_loop_count.setValue(1)
        treeview_setting_layout.addWidget(self.cmd_loop_count)
        treeview_setting_layout.addWidget(QLabel("次"))

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["hex", "cmd", "txt", "index", "delay(ms)", "btn"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        treeview_layout.addWidget(self.table)

        self.cmd_treeview.hide()

        txt_setting_layout = QHBoxLayout()
        txt_setting_layout.setContentsMargins(5, 0, 5, 0)
        txt_layout.addLayout(txt_setting_layout)
        txt_setting_layout.addWidget(QLabel("Sent:"))
        self.sent_count = QLCDNumber(5)
        self.sent_count.setMode(QLCDNumber.Mode.Dec)
        txt_setting_layout.addWidget(self.sent_count)
        txt_setting_layout.addWidget(QLabel("Receive:"))
        self.recv_count = QLCDNumber(5)
        self.recv_count.setMode(QLCDNumber.Mode.Dec)
        txt_setting_layout.addWidget(self.recv_count)
        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self.clear_txt)
        txt_setting_layout.addWidget(clear_btn)
        txt_setting_layout.addStretch()
        ex_cmd_btn = QPushButton("扩展")
        ex_cmd_btn.clicked.connect(self.show_cmds)
        txt_setting_layout.addWidget(ex_cmd_btn)

        setting_frame = QFrame()
        setting_frame.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        layout.addWidget(setting_frame, 1)
        setting_layout = QHBoxLayout(setting_frame)
        setting_layout.setContentsMargins(5, 5, 5, 5)

        com_setting_frame = QFrame()
        setting_layout.addWidget(com_setting_frame)
        com_setting_layout = QVBoxLayout(com_setting_frame)
        com_setting_layout.setContentsMargins(0, 0, 0, 0)

        com_list_layout = QHBoxLayout()
        com_list_layout.setContentsMargins(0, 0, 0, 0)
        com_setting_layout.addLayout(com_list_layout)
        com_list_layout.addWidget(QLabel("串口"))
        self.serial_name = QComboBox()
        self.serial_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        com_list_layout.addWidget(self.serial_name)
        self.refresh_btn = QPushButton('🔄')
        self.refresh_btn.clicked.connect(self.serial_com_refresh)
        com_list_layout.addWidget(self.refresh_btn)

        baud_list_layout = QHBoxLayout()
        baud_list_layout.setContentsMargins(0, 0, 0, 0)
        com_setting_layout.addLayout(baud_list_layout)
        baud_list_layout.addWidget(QLabel("波特率"))
        self.serial_baud = QComboBox()
        self.serial_baud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.serial_baud.addItems(get_serial_bauds_str())
        self.serial_baud.setCurrentText("115200")
        baud_list_layout.addWidget(self.serial_baud)
        self.connect_btn = QPushButton('连接')
        self.connect_btn.clicked.connect(self.connect_serial)
        baud_list_layout.addWidget(self.connect_btn)

        bit_setting_layout = QHBoxLayout()
        bit_setting_layout.setContentsMargins(0, 0, 0, 0)
        com_setting_layout.addLayout(bit_setting_layout)
        bit_setting_layout.addWidget(QLabel("数据位"))
        self.serial_bytesize = QComboBox()
        self.serial_bytesize.addItems(
            [str(serial.FIVEBITS), str(serial.SIXBITS), str(serial.SEVENBITS), str(serial.EIGHTBITS)]
        )
        self.serial_bytesize.setCurrentText(str(serial.EIGHTBITS))
        bit_setting_layout.addWidget(self.serial_bytesize)
        bit_setting_layout.addStretch()
        bit_setting_layout.addWidget(QLabel("校验位"))
        self.serial_parity = QComboBox()
        self.serial_parity.addItems(
            [str(serial.PARITY_NONE), str(serial.PARITY_EVEN),
             str(serial.PARITY_ODD), str(serial.PARITY_MARK), str(serial.PARITY_SPACE)]
        )
        self.serial_parity.setCurrentText(str(serial.PARITY_NONE))
        bit_setting_layout.addWidget(self.serial_parity)
        bit_setting_layout.addStretch()
        bit_setting_layout.addWidget(QLabel("停止位"))
        self.serial_stop_bits = QComboBox()
        self.serial_stop_bits.addItems(
            [str(serial.STOPBITS_ONE), str(serial.STOPBITS_ONE_POINT_FIVE), str(serial.STOPBITS_TWO)]
        )
        self.serial_stop_bits.setCurrentText(str(serial.STOPBITS_ONE))
        bit_setting_layout.addWidget(self.serial_stop_bits)

        fc_setting_layout = QHBoxLayout()
        fc_setting_layout.setContentsMargins(0, 0, 0, 0)
        com_setting_layout.addLayout(fc_setting_layout)
        self.serial_x_onoff = QCheckBox("软件流控")
        fc_setting_layout.addWidget(self.serial_x_onoff)
        fc_setting_layout.addStretch()
        self.serial_rts_cts = QCheckBox("RTS/CTS")
        fc_setting_layout.addWidget(self.serial_rts_cts)
        fc_setting_layout.addStretch()
        self.serial_dsr_dtr = QCheckBox("DSR/DTR")
        fc_setting_layout.addWidget(self.serial_dsr_dtr)

        cmd_setting_frame = QFrame()
        setting_layout.addWidget(cmd_setting_frame, 1)
        cmd_setting_layout = QVBoxLayout(cmd_setting_frame)
        cmd_setting_layout.setContentsMargins(0, 0, 0, 0)

        cmd_rx_setting_layout = QHBoxLayout()
        cmd_rx_setting_layout.setContentsMargins(0, 0, 0, 0)
        cmd_rx_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cmd_setting_layout.addLayout(cmd_rx_setting_layout)
        self.serial_timemap = QCheckBox("add timemap")
        cmd_rx_setting_layout.addWidget(self.serial_timemap)
        self.serial_rx_hex = QCheckBox("hex show")
        cmd_rx_setting_layout.addWidget(self.serial_rx_hex)
        self.serial_autosave = QCheckBox("auto save")
        cmd_rx_setting_layout.addWidget(self.serial_autosave)
        self.serial_save_btn = QPushButton("save log")
        self.serial_save_btn.clicked.connect(self.save_log_to_file)
        cmd_rx_setting_layout.addWidget(self.serial_save_btn)

        cmd_tx_setting_layout = QHBoxLayout()
        cmd_tx_setting_layout.setContentsMargins(0, 0, 0, 0)
        cmd_tx_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cmd_setting_layout.addLayout(cmd_tx_setting_layout)
        self.serial_tx_hex = QCheckBox("hex send")
        cmd_tx_setting_layout.addWidget(self.serial_tx_hex)
        self.serial_loop_en = QCheckBox("loop")
        cmd_tx_setting_layout.addWidget(self.serial_loop_en)
        self.serial_loop_count = QSpinBox(minimum=1, maximum=1_000)
        self.serial_loop_count.setMinimumWidth(10)
        self.serial_loop_count.setValue(1)
        cmd_tx_setting_layout.addWidget(self.serial_loop_count)
        cmd_tx_setting_layout.addWidget(QLabel("次"))
        self.serial_loop_delay = QSpinBox(minimum=100, maximum=3_600_000)
        self.serial_loop_delay.setMinimumWidth(30)
        self.serial_loop_delay.setValue(1000)
        cmd_tx_setting_layout.addWidget(self.serial_loop_delay)
        cmd_tx_setting_layout.addWidget(QLabel("ms/次"))
        self.cmd_send_btn = QPushButton("Send")
        self.cmd_send_btn.clicked.connect(self.send_data)
        cmd_tx_setting_layout.addWidget(self.cmd_send_btn)

        self.tx_txt = QTextEdit()
        self.tx_txt.setMaximumHeight(68)
        self.tx_txt.setFont(QFont("Arial"))
        cmd_setting_layout.addWidget(self.tx_txt)

        self.send_loop_timer = QTimer(self)
        self.send_loop_timer.timeout.connect(self.loop_send_step)
        self.cmd_loop_timer = QTimer(self)
        self.cmd_loop_timer.timeout.connect(self.cmd_loop_step)

        # Load settings
        self.serial_com_refresh()
        self.load_setting()

    def deleteLater(self, /):
        self.stop_all()
        if self.serial and self.serial.is_open():
            self.serial.disconnect()
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        self.stop_all()
        if self.serial and self.serial.is_open():
            self.serial.disconnect()
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()

    def load_setting(self):
        if self.setting_file.exists():
            config = read_data_from_yaml(self.setting_file)
            if config.get("serial_name"):
                self.serial_name.setCurrentText(config["serial_name"])
            if config.get("serial_baud"):
                self.serial_baud.setCurrentText(str(config["serial_baud"]))
            if config.get("serial_bytesize"):
                self.serial_bytesize.setCurrentText(str(config["serial_bytesize"]))
            if config.get("serial_parity"):
                self.serial_parity.setCurrentText(str(config["serial_parity"]))
            if config.get("serial_stop_bits"):
                self.serial_stop_bits.setCurrentText(str(config["serial_stop_bits"]))
            self.serial_x_onoff.setChecked(config.get("serial_x_onoff", False))
            self.serial_rts_cts.setChecked(config.get("serial_rts_cts", False))
            self.serial_dsr_dtr.setChecked(config.get("serial_dsr_dtr", False))
            self.serial_timemap.setChecked(config.get("serial_timemap", False))
            self.serial_rx_hex.setChecked(config.get("serial_rx_hex", False))
            self.serial_tx_hex.setChecked(config.get("serial_tx_hex", False))
            self.serial_autosave.setChecked(config.get("serial_autosave", False))
            self.serial_loop_en.setChecked(config.get("serial_loop_en", False))
            if config.get("serial_loop_count"):
                self.serial_loop_count.setValue(config["serial_loop_count"])
            if config.get("serial_loop_delay"):
                self.serial_loop_delay.setValue(config["serial_loop_delay"])
            self.cmd_loop_en.setChecked(config.get("cmd_loop_en", False))
            if config.get("cmd_loop_count"):
                self.cmd_loop_count.setValue(config["cmd_loop_count"])
            if config.get("cmd_treeview_showed"):
                self.show_cmds()
            self.logger.info("加载用户设置成功")

    @check_error
    def save_setting(self):
        serial_setting = {
             "serial_name": self.serial_name.currentText(),
             "serial_baud": self.serial_baud.currentText(),
             "serial_bytesize": self.serial_bytesize.currentText(),
             "serial_parity": self.serial_parity.currentText(),
             "serial_stop_bits": self.serial_stop_bits.currentText(),
             "serial_x_onoff": self.serial_x_onoff.isChecked(),
             "serial_rts_cts": self.serial_rts_cts.isChecked(),
             "serial_dsr_dtr": self.serial_dsr_dtr.isChecked(),
             "serial_timemap": self.serial_timemap.isChecked(),
             "serial_rx_hex": self.serial_rx_hex.isChecked(),
             "serial_tx_hex": self.serial_tx_hex.isChecked(),
             "serial_autosave": self.serial_autosave.isChecked(),
             "serial_loop_en": self.serial_loop_en.isChecked(),
             "serial_loop_count": self.serial_loop_count.value(),
             "serial_loop_delay": self.serial_loop_delay.value(),
             "cmd_treeview_showed": self.cmd_treeview_showed,
             "cmd_loop_en": self.cmd_loop_en.isChecked(),
             "cmd_loop_count": self.cmd_loop_count.value(),
        }
        save_data_to_yaml(serial_setting, self.setting_file)
        self.logger.info("保存用户数据成功")

    def stop_all(self):
        self.send_loop_timer.stop()
        self.cmd_loop_timer.stop()
        self.loop_running = False
        self.cmd_loop_running = False

    def serial_com_refresh(self):
        serial_com_scan = [""]
        if sys.platform == 'win32':
            serial_com_scan += [com.name for com in get_serial_ports()]
        else:
            serial_com_scan += [f'/dev/{com.name}' for com in get_serial_ports()]
        current_text = self.serial_name.currentText()
        self.serial_name.clear()
        self.serial_name.addItems(serial_com_scan)
        self.serial_name.setCurrentText(current_text)

    def connect_serial(self):
        if self.serial and self.serial.is_open():
            # 断开
            self.stop_all()
            self.serial.disconnect()
            self.serial = None
            self.connect_btn.setText('连接')
            self.serial_name.setEnabled(True)
            self.logger.info("串口已断开")
            return
        try:
            port = self.serial_name.currentText()
            baud = int(self.serial_baud.currentText())
            if not port:
                QMessageBox.warning(self, "提示", "请选择串口")
                return
            ser = UARTSerial(
                port=port,
                baud_rate=baud,
                timeout=5,
                bytesize=int(self.serial_bytesize.currentText()),
                parity=self.serial_parity.currentText(),
                stop_bits=int(self.serial_stop_bits.currentText()),
                xon_off=self.serial_x_onoff.isChecked(),
                rts_cts=self.serial_rts_cts.isChecked(),
                dsr_dtr=self.serial_dsr_dtr.isChecked(),
            )
            ser.set_callbacks(
                data_received=self._on_data_received,
                connection_status=self._on_connection_status
            )
            connect_state = ser.connect()

            if not connect_state:
                raise Exception(f"{port} 连接失败")
            self.serial = ser
            self.connect_btn.setText('断开')
            self.serial_name.setEnabled(False)
            self.logger.info(f"串口 {port} 已连接")
        except Exception as e:
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
            self.serial = None
            QMessageBox.critical(self, "连接失败", str(e))

    def _on_data_received(self, data: dict):
        msg = data.get("msg", "")

        if not msg:
            return
        raw_bytes = msg.encode('utf-8') if isinstance(msg, str) else msg
        self.recv_count_value += len(raw_bytes)
        self.recv_count.display(self.recv_count_value)

        if self.serial_rx_hex.isChecked():
            hex_str = raw_bytes.hex(' ').upper()
            line = hex_str
        else:
            line = msg

        if self.serial_timemap.isChecked():
            ts = datetime.now().strftime("[%H:%M:%S.%f] ")
            self.rx_txt.append(ts + line)
        else:
            self.rx_txt.insertPlainText(line)

        scrollbar = self.rx_txt.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        if self.serial_autosave.isChecked():
            self._auto_save(raw_bytes)

    def _on_connection_status(self, status: bool, message: str):
        self.logger.info(f"连接状态: {'连接' if status else '断开'}; {message}")

    def _auto_save(self, data: bytes):
        if not self.auto_save_file:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            self.auto_save_file = self.data_path / f"sscom_log_{ts}.bin"
            try:
                with open(self.auto_save_file, "ab") as f:
                    f.write(data)
            except Exception as e:
                self.logger.error(f"自动保存失败: {e}")

    def save_log_to_file(self):
        text = self.rx_txt.toPlainText()

        if not text:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "保存日志", str(self.data_path), "文本文件 (*.txt);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            self.logger.info(f"日志已保存: {path}")
            QMessageBox.information(self, "完成", f"日志已保存至:\n{path}")
        except Exception as e:
            self.logger.error(f"保存日志失败: {e}")

    def send_data(self):
        if not self.serial or not self.serial.is_open():
            QMessageBox.warning(self, "提示", "请先连接串口")
            return
        text = self.tx_txt.toPlainText()
        if not text:
            return
        if self.serial_loop_en.isChecked():
            # 启动循环发送
            if self.loop_running:
                self.loop_running = False
                self.send_loop_timer.stop()
                self.cmd_send_btn.setText("Send")
                return
            self.loop_running = True
            self.loop_send_remaining = self.serial_loop_count.value()
            self.cmd_send_btn.setText("停止")
            self._do_send_now(text)
            return
        self._do_send_now(text)

    def _do_send_now(self, text: str):
        if self.serial_tx_hex.isChecked():
            try:
                hex_str = text.replace(' ', '').replace('\n', '').replace('\r', '')

                data = bytes.fromhex(hex_str)
            except ValueError as e:
                QMessageBox.warning(self, "错误", f"十六进制格式错误: {e}")
                return
        else:
            data = text.encode('utf-8')
        try:
            if self.serial and self.serial.serial_port and self.serial.serial_port.is_open:
                self.serial.serial_port.write(data)
            self.serial.serial_port.flush()
            self.sent_count_value += len(data)
            self.sent_count.display(self.sent_count_value)
            self.logger.info(f"Send: {data[:100]}")
        except Exception as e:
            self.logger.error(f"发送失败: {e}")

    def loop_send_step(self):
        self.send_loop_timer.stop()

        if not self.loop_running or self.loop_send_remaining <= 0:
            self.loop_running = False
            self.cmd_send_btn.setText("Send")
            return

        text = self.tx_txt.toPlainText()
        if text:
            self._do_send_now(text)

        self.loop_send_remaining -= 1
        if self.loop_send_remaining > 0:
            self.send_loop_timer.start(self.serial_loop_delay.value())
        else:
            self.loop_running = False
            self.cmd_send_btn.setText("Send")

    def add_cmd_row(self, hex_cmd: str = "", cmd: str = "", txt: str = "", delay: int = 0):
        row = self.table.rowCount()

        self.table.insertRow(row)
        hex_w = QCheckBox()
        hex_w.setChecked(bool(hex_cmd))
        self.table.setCellWidget(row, 0, hex_w)
        cmd_item = QTableWidgetItem(cmd)
        self.table.setItem(row, 1, cmd_item)
        txt_item = QTableWidgetItem(txt)
        self.table.setItem(row, 2, txt_item)
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 3, idx_item)
        delay_spin = QSpinBox(minimum=0, maximum=3_600_000)
        delay_spin.setValue(delay)
        self.table.setCellWidget(row, 4, delay_spin)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(lambda checked, r=row: self.remove_cmd_row(r))
        self.table.setCellWidget(row, 5, del_btn)

    def remove_cmd_row(self, row: int):
        self.table.removeRow(row)
        self.reindex_cmd_rows()

    def reindex_cmd_rows(self):
        for i in range(self.table.rowCount()):
            item = self.table.item(i, 3)
            if item:
                item.setText(str(i + 1))

    def import_ini(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入INI文件", "", "INI文件 (*.ini);;所有文件 (*.*)"
        )
        if not path:
            return
        try:
            import configparser
            config = configparser.ConfigParser()
            config.read(path, encoding='utf-8')
            self.table.setRowCount(0)
            count = 0
            for section in config.sections():
                for key in config.options(section):
                    value = config.get(section, key).strip()
                    if value:
                        count += 1
                        is_hex = key.lower() == "hex" or key.lower().startswith("hex")
                        self.add_cmd_row(
                            hex_cmd = "1" if is_hex else "",
                            cmd = value,
                            txt = section,
                            delay = 0,
                        )
            self.logger.info(f"从 {path} 导入了 {count} 条命令")
            QMessageBox.information(self, "导入完成", f"已导入 {count} 条命令")
        except Exception as e:
            self.logger.error(f"导入失败: {e}")
            QMessageBox.critical(self, "导入失败", str(e))

    def on_cmd_loop_changed(self, state):
        if state:
            self.cmd_send_btn.setText("顺序执行")

        else:
            self.cmd_send_btn.setText("Send")

    def cmd_loop_step(self):
        self.cmd_loop_timer.stop()
        if not self.cmd_loop_running:
            return
        # 发送当前命令
        row = self.cmd_loop_index
        hex_cb: Optional[QCheckBox, any] = self.table.cellWidget(row, 0)
        cmd_item = self.table.item(row, 1)

        if cmd_item and cmd_item.text():
            txt = cmd_item.text()
            is_hex = hex_cb and hex_cb.isChecked()

            if is_hex:
                try:
                    data = bytes.fromhex(txt.replace(' ', ''))
                except ValueError:
                    data = txt.encode('utf-8')
            else:
                data = txt.encode('utf-8')
            try:
                if self.serial and self.serial.serial_port and self.serial.serial_port.is_open:
                    self.serial.serial_port.write(data)
                self.serial.serial_port.flush()
                self.sent_count_value += len(data)
                self.sent_count.display(self.sent_count_value)
            except Exception as e:
                self.logger.error(f"命令发送失败: {e}")
        # 下一条
        self.cmd_loop_index += 1
        if self.cmd_loop_index >= self.table.rowCount():
            self.cmd_loop_index = 0
            self.cmd_loop_round += 1
            if self.cmd_loop_round >= self.cmd_loop_count.value():
                self.cmd_loop_running = False
                self.cmd_send_btn.setText("Send")
                return
        # 获取下一条的延迟
        delay_w: Optional[QSpinBox, any] = self.table.cellWidget(self.cmd_loop_index, 4)
        delay = delay_w.value() if delay_w else 0
        if delay > 0:
            self.cmd_loop_timer.start(delay)
        else:
            self.cmd_loop_timer.start(1)

    def clear_txt(self):
        self.rx_txt.clear()
        self.sent_count_value = 0
        self.recv_count_value = 0
        self.sent_count.display(0)
        self.recv_count.display(0)

    def show_cmds(self):
        self.cmd_treeview_showed = not self.cmd_treeview_showed
        if self.cmd_treeview_showed:
            self.cmd_treeview.show()
        else:
            self.cmd_treeview.hide()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow(name="SSCOM", version="0.0.1", logger=None, dryrun=True)
        window.show()
        sys.exit(app.exec())
    except Exception as ex:
        print(f"程序崩溃: {ex}")
        traceback.print_exc()
        input("按回车键退出...")
