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
from typing import Union, Optional, Dict

from PySide6.QtCore import QTimer, QThread, Slot, Signal, QMutex, QWaitCondition
from PySide6.QtGui import Qt, QFont, QIntValidator, QColor, QTextCursor, QTextCharFormat
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QLabel, QFrame, QSplitter, QVBoxLayout,
    QSizePolicy, QHBoxLayout, QGroupBox, QPushButton, QCheckBox, QComboBox,
    QTextEdit, QLineEdit, QProgressBar, QLCDNumber, QTreeWidget, QFileDialog,
    QTreeWidgetItem, QHeaderView, QMessageBox, QDialog, QGridLayout
)

from lib.customlog import create_logger, Formatter
from lib.deviceCheck import check_error
from lib.uartSerial.scan import get_serial_ports, get_serial_bauds_str
from lib.uartSerial.QtSerial import SerialPortManager
from lib.filetools import scan_file_list

from .property import process_value
from .excel import read_xlsx_file, save_data_to_xlsx
from .setting import read_setting_file, SettingConfig, SerialConfig, save_setting_file


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: logging.Logger = None, data_path: Union[PathLike[str], str, None] = None, *args, **kwargs):
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
        self.result_folder = self.data_path / "result"
        if not self.result_folder.exists():
            self.result_folder.mkdir()
        self.result_default_folder = self.result_folder
        commands_path = self.data_path / 'commands'
        if not commands_path.exists():
            commands_path.mkdir()
        if not (commands_path / "example_commands.xlsx").exists():
            self.logger.info("默认commands不存在,将创建该文件")
            shutil.copy2(Path(__file__).parent / "example_commands.xlsx", commands_path)
        self.command_file_path = self.data_path / "commands/example_commands.xlsx"
        self.setting_file = self.data_path / ".setting.yaml"

        self.command_row_data = OrderedDict()
        self.sn_name = ""
        self.run_status = False
        self.run_thread: Optional[BuildTestThread] = None
        self.thread_event = Event()
        self.station_log = create_logger(f"{self.logger.name}.EEFCTStation", propagate=True)
        self.loop_status_bool = False
        self.loop_now_time = 0
        self.loop_test_time = 0
        self.loop_fail_time = 0
        self.all_test_time = 0
        self.all_fail_time = 0

        # 设置窗口标题和大小
        self.setWindowTitle(f'EE FunctionCheckTest V{version}')
        self.resize(1500, 800)

        # 主布局
        # 使用QSplitter作为主分割窗口
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setContentsMargins(5, 5, 5, 5)
        splitter.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCentralWidget(splitter)

        # 左侧面板
        left_panel = QFrame()
        left_panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 标题栏
        title_frame = QFrame()
        title_layout = QHBoxLayout(title_frame)
        title_layout.setContentsMargins(5, 0, 5, 0)
        name_label = QLabel(self)
        name_label.setText('EEFCT')
        name_label.setFont(QFont('', 30, QFont.Weight.Bold))
        title_layout.addWidget(name_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        version_label = QLabel(self)
        version_label.setText(f'V{version}')
        version_label.setFont(QFont('', 15, QFont.Weight.Bold))
        title_layout.addWidget(version_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        title_layout.addStretch()
        note_label = QLabel(self)
        note_label.setText("Let's 💯!")
        note_label.setFont(QFont("Noteworthy", 20))
        note_label.setStyleSheet("color: red")
        title_layout.addWidget(note_label, alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        author_label = QLabel(self)
        author_label.setText('🖋️Liuyu')
        author_label.setStyleSheet("color: gray")
        title_layout.addWidget(author_label, alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        left_layout.addWidget(title_frame)

        # 设置区域
        settings_group = QGroupBox("Settings")
        settings_group.setStyleSheet("""
            QGroupBox {
                font-Size: 15px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 7 5px;
                background-color: transparent;
            }
        """)
        settings_layout = QVBoxLayout(settings_group)
        settings_layout.setContentsMargins(0, 0, 0, 0)
        settings_layout.setSpacing(0)
        left_layout.addWidget(settings_group)

        # 串口设置
        com_setting_frame = QFrame()
        com_setting_layout = QHBoxLayout(com_setting_frame)
        com_setting_layout.setContentsMargins(0, 0, 0, 0)

        com_setting_layout.addWidget(QLabel('Enable'))
        com_setting_layout.addStretch()
        self.refresh_btn = QPushButton('🔄refresh uartSerial coms')
        self.refresh_btn.clicked.connect(self.serial_com_refresh)
        com_setting_layout.addWidget(self.refresh_btn)
        clear_btn = QPushButton('clear')
        clear_btn.clicked.connect(self.serial_com_clear)
        com_setting_layout.addWidget(clear_btn)
        com_setting_layout.addStretch()
        self.show_command_enable = QCheckBox("显示发送的指令")
        com_setting_layout.addWidget(self.show_command_enable, alignment=Qt.AlignmentFlag.AlignRight)
        settings_layout.addWidget(com_setting_frame)

        # 串口配置
        self.serial_combos = {}

        for i in range(1, 7):
            frame = QFrame()
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(5)

            serial_data = {
                f'serial{i}_enable': QCheckBox(f'Serial{i}'),
                f'serial{i}_name': QComboBox(),
                f'serial{i}_baud': QComboBox()
            }

            serial_data[f'serial{i}_enable'].setChecked(True)
            serial_data[f'serial{i}_name'].setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            serial_data[f'serial{i}_baud'].addItems(get_serial_bauds_str())
            serial_data[f'serial{i}_baud'].setCurrentText("230400")
            layout.addWidget(serial_data[f'serial{i}_enable'])
            layout.addWidget(serial_data[f'serial{i}_name'])
            layout.addWidget(QLabel('baud'), 0, Qt.AlignmentFlag.AlignRight)
            layout.addWidget(serial_data[f'serial{i}_baud'])
            settings_layout.addWidget(frame)

            self.serial_combos[f"serial{i}"] = serial_data

        self.serial_com_refresh()

        # command文件选择
        command_frame = QFrame()
        command_layout = QHBoxLayout(command_frame)
        command_layout.setContentsMargins(0, 0, 0, 0)
        command_layout.setSpacing(5)

        self.command_file_name = QComboBox()
        self.command_file_name.setEditable(False)
        self.command_file_name.currentTextChanged.connect(self.change_command_path_name)
        self.command_file_name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        command_layout.addWidget(self.command_file_name)

        choose_btn = QPushButton('choose other')
        choose_btn.clicked.connect(self.choose_command_file)
        command_layout.addWidget(choose_btn)

        open_btn = QPushButton('open edit')
        open_btn.clicked.connect(self.open_command_file)
        command_layout.addWidget(open_btn)

        settings_layout.addWidget(command_frame)

        # 命令输出框
        self.rx_txt_pos = 0
        self.rx_txt = QTextEdit()
        self.rx_txt.setReadOnly(True)
        self.rx_txt.setFont(QFont("Arial"))
        self.rx_txt.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        left_layout.addWidget(self.rx_txt)
        # 用于跟踪文本位置的变量
        self.command_start_pos = 0

        # 右侧面板
        right_panel = QFrame()
        right_panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 进度和状态区域
        progress_frame = QFrame()
        progress_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        progress_layout = QHBoxLayout(progress_frame)
        progress_layout.setContentsMargins(0, 0, 0, 0)

        # SN输入和日志按钮
        log_frame = QFrame()
        log_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log_layout = QVBoxLayout(log_frame)
        log_layout.setContentsMargins(5, 5, 5, 5)

        self.sn_input_box = QLineEdit()
        self.sn_input_box.returnPressed.connect(self._check_sn_input)
        self.sn_input_box.setMinimumWidth(20 * 8)
        self.sn_input_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        log_layout.addWidget(self.sn_input_box)

        open_log_btn = QPushButton('open log')
        open_log_btn.clicked.connect(self.open_result_folder)
        log_layout.addWidget(open_log_btn)
        progress_layout.addWidget(log_frame, 1)

        # 运行按钮
        self.run_btn = QPushButton('Start')
        self.run_btn.setFont(QFont('', 30, QFont.Weight.Bold))
        self.run_btn.clicked.connect(self.run_preparation_set)
        self.run_btn.setFixedWidth(100)
        self.run_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        progress_layout.addWidget(self.run_btn, 0)

        # 进度标签
        self.progress = QLabel('progress')
        self.progress.setFont(QFont('', 20))
        self.progress.setFixedWidth(100)
        self.progress.setStyleSheet("background-color: grey")
        self.progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        progress_layout.addWidget(self.progress, 0)

        # 进度条和循环设置
        setting_frame = QFrame()
        setting_frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        setting_frame_layout = QVBoxLayout(setting_frame)
        setting_frame_layout.setContentsMargins(0, 0, 15, 0)

        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px; 
                background-color: #FFFFFF; 
                text-align:center; 
                font-size:12px;
                height: 15px
            }
            QProgressBar::chunk {
                background-color: green; 
            }
        """)
        self.progress_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        setting_frame_layout.addWidget(self.progress_bar)

        # 循环设置
        loop_layout = QHBoxLayout()
        loop_layout.setContentsMargins(5, 0, 5, 0)
        loop_layout.setSpacing(5)
        setting_frame_layout.addLayout(loop_layout)

        lcd_layout = QHBoxLayout()
        lcd_layout.setContentsMargins(0, 0, 0, 0)
        lcd_layout.setSpacing(0)
        loop_layout.addLayout(lcd_layout)
        self.run_time_s = 0
        self.run_time_lcd = QLCDNumber(5)
        self.run_time_lcd.setMode(QLCDNumber.Mode.Dec)
        self.run_time_lcd.setSegmentStyle(QLCDNumber.SegmentStyle.Flat)
        self.run_time_lcd.setStyleSheet("border: 1px solid gray; font: bold; color: black; background: silver;")
        lcd_layout.addWidget(self.run_time_lcd, 0, Qt.AlignmentFlag.AlignRight)
        lcd_layout.addWidget(QLabel('s'), alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)

        loop_layout.addStretch()
        loop_layout.addWidget(QLabel('Loop'))
        self.loop_time_input = QLineEdit('1')
        int_validator = QIntValidator()
        self.loop_time_input.setValidator(int_validator)
        self.loop_time_input.setMaximumWidth(30)
        loop_layout.addWidget(self.loop_time_input)
        loop_layout.addWidget(QLabel('Times'))
        loop_layout.addStretch()
        self.loop_result_value = QLabel('0F/0T')
        loop_layout.addWidget(self.loop_result_value)
        clear_btn = QPushButton('clear')
        clear_btn.clicked.connect(self.clear_result_data)
        loop_layout.addWidget(clear_btn)
        loop_layout.addStretch()
        self.fail_to_break = QCheckBox('fail to stop')
        self.fail_to_break.setFixedWidth(90)
        loop_layout.addWidget(self.fail_to_break)

        progress_layout.addWidget(setting_frame, 3)

        right_layout.addWidget(progress_frame)

        # 树形视图
        self.treeview = QTreeWidget()
        self.treeview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.treeview.setHeaderLabels(
            [
                "No", "Item", "Serial", "Command",
                "Lower_limit", "Value", "Upper_limit",
                "Status"
            ]
        )
        right_layout.addWidget(self.treeview)
        self.treeview.itemDoubleClicked.connect(self.on_treeview_click)

        # 添加面板
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        # Load settings
        self.load_setting()
        self.change_command_path_name()

        # Timer for run time updates
        self.run_timer = QTimer(self)
        self.run_timer.timeout.connect(self.on_timer)

    def deleteLater(self, /):
        if self.run_status:
            self.thread_event.set()
            while not self.run_thread.isFinished():
                pass
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        if self.run_status:
            self.thread_event.set()
            while not self.run_thread.isFinished():
                pass
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()

    def load_setting(self):
        if self.setting_file.exists():
            config = read_setting_file(self.setting_file)
            self.command_file_path = Path(config.CommandFile)
            self.command_file_name.addItem(self.command_file_path.name)
            self.command_file_name.setCurrentText(self.command_file_path.name)
            self.show_command_enable.setChecked(config.ShowCmd)
            self.fail_to_break.setChecked(config.FailStop)
            for index, data in config.Serial.items():
                if isinstance(data, dict):
                    data = SerialConfig(**data)
                serial_data = self.serial_combos[f"serial{index}"]
                serial_data[f'serial{index}_enable'].setChecked(data.Enable)
                serial_data[f'serial{index}_name'].setCurrentText(data.Name)
                serial_data[f'serial{index}_baud'].setCurrentText(str(data.Baud))
        else:
            self.logger.debug(f'配置文件不存在,将生成配置文件')
            self.save_setting()
        if not self.command_file_path:
            self.command_file_path = self.data_path / "commands/example_commands.xlsx"
            self.command_file_name.addItem("example_commands.xlsx")
            self.command_file_name.setCurrentText("example_commands.xlsx")

    @check_error
    def save_setting(self):
        serial_setting: Dict[int, SerialConfig] = {}
        for i in range(1, 7):
            serial_data = self.serial_combos[f"serial{i}"]
            serial_info = SerialConfig(
                Enable=serial_data[f'serial{i}_enable'].isChecked(),
                Name=serial_data[f'serial{i}_name'].currentText(),
                Baud=int(serial_data[f'serial{i}_baud'].currentText()),
            )
            serial_setting[i] = serial_info
        config = SettingConfig(
            CommandFile=self.command_file_path.as_posix(),
            ShowCmd=self.show_command_enable.isChecked(),
            FailStop=self.fail_to_break.isChecked(),
            Serial=serial_setting
        )
        save_setting_file(config, self.setting_file)
        self.logger.info("保存用户数据成功")

    def serial_com_refresh(self):
        serial_com_scan = [""]
        if sys.platform == 'win32':
            serial_com_scan += [com.name for com in get_serial_ports()]
        else:
            serial_com_scan += [f'/dev/{com.name}' for com in get_serial_ports()]
        for i in range(1, 7):
            serial_data = self.serial_combos[f"serial{i}"]
            current_text = serial_data[f"serial{i}_name"].currentText()
            serial_data[f"serial{i}_name"].clear()
            serial_data[f"serial{i}_name"].addItems(serial_com_scan)
            if current_text and current_text in serial_com_scan:
                serial_data[f"serial{i}_name"].setCurrentText(current_text)

    def serial_com_clear(self):
        for i in range(1, 7):
            serial_data = self.serial_combos[f"serial{i}"]
            serial_data[f"serial{i}_name"].setCurrentIndex(0)

    def open_command_file(self):
        if self.command_file_path:
            if sys.platform == 'win32':
                os.startfile(self.command_file_path)
            else:
                subprocess.run(['open', self.command_file_path])

    def change_command_path_name(self):
        self.command_file_name.blockSignals(True)
        current_text = self.command_file_name.currentText()
        self.logger.debug("refresh command files")
        files = scan_file_list(self.data_path / "commands", "xlsx", True)
        self.command_file_name.clear()
        self.command_file_name.addItems(files)
        if current_text and current_text in files:
            self.command_file_path = self.data_path / "commands" / current_text
            self.command_file_name.setCurrentText(current_text)
        self._build_command_treeview()
        self.command_file_name.blockSignals(False)

    def choose_command_file(self):
        if self.run_status:
            return

        self.command_file_name.blockSignals(True)
        new_path_name, _ = QFileDialog.getOpenFileName(
            None, "Open command excel file",
            "", "Excel File(*.xlsx);;Numbers File(*.numbers)"
        )
        if not new_path_name:
            return
        if not new_path_name == self.command_file_path.as_posix():
            new_ptah = Path(new_path_name)
            self.command_file_name.addItem(new_ptah.name)
            self.command_file_name.setCurrentText(new_ptah.name)
            self.command_file_path = new_ptah
            self.logger.debug(f"change the command file to {self.command_file_path} successfully")
            self._build_command_treeview()
        self.command_file_name.blockSignals(False)

    def _build_command_treeview(self):
        self.treeview.clear()
        try:
            self._build_sequence_treeview()
            self.progress_bar.setMaximum(len(self.command_row_data))
            self.progress_bar.setValue(0)
        except Exception as e:
            self.logger.exception(traceback.format_exc())
            QMessageBox.warning(self, "失败", str(e))

    def _build_sequence_treeview(self):
        sequence_table_list: dict = {"-1": self.treeview}
        items_counter = {}
        last_label = ""

        command_row_data = read_xlsx_file(self.command_file_path)
        self.command_row_data.clear()
        new_index = 0

        for index, row_data in command_row_data.items():
            original_row_data = row_data.copy()
            item = original_row_data['Item']

            if item:  # 只有当Items非空时才创建父级标签
                if last_label != item:  # 更新计数器：记录该Items出现的次数
                    items_counter[item] = items_counter.get(item, 0) + 1
                    if items_counter[item] == 1:  # 如果是第一次出现，直接用Items作为标签
                        label_text = item
                    else:
                        label_text = f"{item}-{items_counter[item] - 1}"

                    if label_text not in sequence_table_list:
                        parent = QTreeWidgetItem(self.treeview)
                        parent.setText(0, label_text)
                        sequence_table_list[label_text] = parent
                    item = label_text
            else:
                item = "-1"

            serial = original_row_data["Serial"].strip()
            serials = []
            if serial == "ALL":
                for name, info in self.serial_combos.items():
                    en = info.get(f'{name}_enable').isChecked()
                    port = info.get(f'{name}_name').currentText()
                    if en and port:
                        serials.append(name)
            else:
                serials.append(serial)
            for serial_index, choose_serial in enumerate(serials):
                sub_item = QTreeWidgetItem(sequence_table_list[item])
                sub_item.setText(0, str(original_row_data['Sequence']))
                sub_item.setText(1, original_row_data['SubTest'])
                sub_item.setText(2, choose_serial)
                sub_item.setText(3, original_row_data['Command'])
                sub_item.setText(4, original_row_data['LowerLimit'])
                sub_item.setText(5, '')
                sub_item.setText(6, original_row_data['UpperLimit'])
                sub_item.setText(7, '')

                new_row_data = original_row_data.copy()
                new_row_data["Serial"] = choose_serial
                new_row_data["itemid"] = sub_item
                new_index += 1
                self.command_row_data[new_index] = new_row_data

            last_label = item
        header = self.treeview.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self.treeview.setColumnWidth(2, 60)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.Fixed)
        self.treeview.setColumnWidth(7, 50)

        self.treeview.expandAll()

    def _check_sn_input(self):
        if self.run_status:
            return
        if self.sn_input_box.text().strip() != "":
            time.sleep(1)
            self.logger.info(f"监测到SN：{self.sn_input_box.text().strip()}")
            self.run_preparation_set()

    def open_result_folder(self):
        if self.result_folder:
            if sys.platform == 'win32':
                os.startfile(self.result_folder)
            else:
                subprocess.run(['open', self.result_folder])

    def clear_result_data(self):
        self.loop_status_bool = False
        self.loop_now_time = 0
        self.loop_test_time = 0
        self.loop_fail_time = 0
        self.all_test_time = 0
        self.all_fail_time = 0
        self.run_time_lcd.display(0)
        self.loop_time_input.setText("0")
        self.loop_result_value.setText("0F/0T")
        self._build_command_treeview()

    def on_treeview_click(self, item, column):
        """双击项目时调用的槽函数"""
        self.logger.debug(f"user choose treeview {item} {column}")
        # 获取整行的所有列内容
        row_contents = []
        for i in range(self.treeview.columnCount()):
            row_contents.append(item.text(i))

        # 格式化显示内容
        header_labels = [self.treeview.headerItem().text(i)
                         for i in range(self.treeview.columnCount())]

        row_dict = {}
        for header, content in zip(header_labels, row_contents):
            row_dict[header] = content

        # 显示弹窗
        popup = TreeviewInfoBox(self, row_dict)
        popup.exec_()

    def on_timer(self):
        if self.run_status:
            self.run_time_s += 1
            self.run_time_lcd.display(self.run_time_s)

    def run_preparation_set(self):
        self.run_btn.setStyleSheet("font-size: 30px; font-weight: bold; color: gray;")
        self.run_btn.setEnabled(False)
        if self.run_status:
            self.thread_event.set()
            return

        if self.command_file_path == "":
            self.sn_input_box.setText("")
            QMessageBox.warning(self, "警告", "未选择任何command文件!\nplease choose the command file!")
            self.run_btn.setEnabled(True)
            self.run_btn.setStyleSheet("font-size: 30px; font-weight: bold; color: black;")
            return

        self.logger.info("Refresh commands file")
        self._build_command_treeview()

        self.sn_name = self.sn_input_box.text().strip()
        if self.sn_name == "":
            file_name = self.command_file_name.currentText()
            self.sn_name = file_name.rsplit(".", 1)[0]

        self.run_time_lcd.display(0)
        self.loop_test_time = int(self.loop_time_input.text())
        if self.loop_test_time > 1:
            self.loop_now_time = 0
            self.loop_fail_time = 0
            self.loop_status_bool = True
            self.loop_result_value.setText("0F/0T")
        else:
            self.loop_status_bool = False
            self.loop_result_value.setText(f"{self.all_fail_time}F/{self.all_test_time}T")
        self.rx_txt.clear()

        self.result_folder = self.result_default_folder
        now = datetime.now().strftime("%y_%m_%d_%H_%M_%S")
        self.result_folder = self.result_folder / f"{self.sn_name}_{now}"
        self.result_folder.mkdir()

        self.run_status = True
        self.thread_event.clear()
        self.run_time_s = 0
        self.run_timer.start(1000)
        self.logger.debug(f"{self.sn_name} 测试{self.loop_test_time}次开始")

        self.run_thread = BuildTestThread(
            sn=self.sn_name, event=self.thread_event,
            test_time=self.loop_test_time, fail_to_break=self.fail_to_break.isChecked(),
            command_file_path=self.command_file_path, test_sequence=self.command_row_data,
            serial_combos=self.serial_combos, test_path=self.result_folder,
            logger=self.station_log, show_command_en=self.show_command_enable.isChecked(),
        )
        self.run_thread.test_started.connect(self.update_start)
        self.run_thread.qt_msg_signal.connect(self.show_popup_msg)
        self.run_thread.treeview_signal.connect(self.update_treeview_result)
        self.run_thread.progress_signal.connect(self.update_progress_bar)
        self.run_thread.test_finished.connect(self.update_test_result)
        self.run_thread.finished.connect(self.update_ui_result)
        self.run_thread.error.connect(self.update_error_msg)
        self.run_thread.textEdict_signal.connect(self.update_text_info)

        self.run_thread.start()

    def update_start(self):
        self._build_command_treeview()
        self.loop_now_time += 1
        self.all_test_time += 1
        if self.loop_status_bool:
            self.progress.setText(f"Loop-{self.loop_now_time}")
        else:
            self.progress.setText(f"Test")
        self.progress.setStyleSheet("background-color: yellow")
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Stop")
        self.run_btn.setStyleSheet("font-size: 30px; font-weight: bold; color: red;")
        if self.loop_status_bool:
            self.loop_result_value.setText(f"{self.loop_fail_time}F/{self.loop_now_time}T")
        else:
            self.loop_result_value.setText(f"{self.all_fail_time}F/{self.all_test_time}T")

    @Slot(dict)
    def show_popup_msg(self, msg_info):
        popup = MessageBox(self, msg_info["tittle"], msg_info["info"], msg_info["timeout"])
        popup.button_clicked.connect(self.run_thread.set_dialog_result)
        popup.exec()

    @Slot(dict)
    def update_treeview_result(self, result):
        """更新树状图结果显示"""
        row_data = self.command_row_data.get(result["index"])
        if not row_data or "itemid" not in row_data:
            return

        item: QTreeWidgetItem = row_data["itemid"]
        item.setText(5, str(result["value"]))
        item.setText(7, "PASS" if result["status"] == "PASS" else "FAIL")
        if result["status"] == "PASS":
            item.setForeground(7, QColor("green"))
        else:
            for i in range(8):
                item.setBackground(i, QColor("red"))

    @Slot(int)
    def update_progress_bar(self, value: int):
        self.progress_bar.setValue(value)

    @Slot(str)
    def update_test_result(self, final_state: str):
        self.progress.setText(final_state)
        if final_state == "PASS":
            self.progress.setStyleSheet("background-color: green")
        else:
            self.loop_fail_time += 1
            self.all_fail_time += 1
            self.progress.setStyleSheet("background-color: red")
            if self.loop_status_bool:
                self.loop_result_value.setText(f"{self.loop_fail_time}F/{self.loop_now_time}T")
            else:
                self.loop_result_value.setText(f"{self.all_fail_time}F/{self.all_test_time}T")

    @Slot(Path)
    def update_ui_result(self, result_path):
        self.run_status = False
        self.run_timer.stop()
        self.sn_input_box.setText("")
        self.sn_input_box.setFocus()
        self.result_folder = result_path
        self.run_btn.setEnabled(True)
        self.run_btn.setText("Start")
        self.run_btn.setStyleSheet("font-size: 30px; font-weight: bold; color: black;")

    @Slot(str)
    def update_error_msg(self, msg: str):
        QMessageBox.critical(self, "ERROR", msg)

    @Slot(dict)
    def update_text_info(self, msg_info):
        """更新文本显示区域"""
        try:
            # 获取数据
            port = msg_info.get("port", "Unknown")
            msg_type = msg_info.get("type", "data")
            data_msg = msg_info.get("msg", "")
            color_set = msg_info.get("color", "")

            # 处理特殊标记
            if msg_type == "command_start":
                # 记录命令开始位置
                self.command_start_pos = self.rx_txt.textCursor().position()
                return

            elif msg_type == "command_end":
                # 检查状态
                state = msg_info.get("state", "PASS")
                if state == "FAIL":
                    # 对从 command_start 到现在的所有文本标红
                    self._color_last_command_red()
                return

            elif msg_type == "command_failed":
                # 直接标红最后一个命令
                self._color_last_command_red()

                cursor = self.rx_txt.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)

                text_format = QTextCharFormat()
                text_format.setForeground(QColor(255, 0, 0))
                text_format.setFontWeight(QFont.Weight.Bold)
                return

            # 普通数据消息处理
            if not data_msg and msg_type == "data":
                return

            # 格式化显示
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

            # 如果是串口数据，特殊处理
            if msg_type == "serial_data":
                display_text = f"{timestamp:14} | {port} | {data_msg}\n"
            else:
                display_text = f"{timestamp:14} | {data_msg}\n"

            # 添加到文本区域
            cursor = self.rx_txt.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)

            # 设置文本颜色
            text_format = QTextCharFormat()
            if color_set == "fail":
                text_format.setForeground(QColor(255, 0, 0))
                text_format.setFontWeight(QFont.Weight.Bold)
            elif color_set == "info":
                text_format.setForeground(QColor("darkgreen"))
            elif color_set == "warning":
                text_format.setForeground(QColor("orange"))
            elif color_set == "debug":
                text_format.setForeground(QColor("chocolate"))
            else:
                text_format.setForeground(QColor("black"))

            # 插入文本
            cursor.insertText(display_text, text_format)

            # 滚动到底部
            self.rx_txt.ensureCursorVisible()

        except Exception as e:
            self.logger.error(f"Error updating text info: {e}")

    def _color_last_command_red(self):
        """将上一个命令的所有日志标红"""
        try:
            if self.command_start_pos == 0:
                return

            cursor = self.rx_txt.textCursor()
            current_pos = cursor.position()

            # 设置从 command_start_pos 到当前位置的文本为红色
            cursor.setPosition(self.command_start_pos)
            cursor.setPosition(current_pos, QTextCursor.MoveMode.KeepAnchor)

            # 应用红色格式
            text_format = QTextCharFormat()
            text_format.setForeground(QColor(255, 0, 0))
            text_format.setFontWeight(QFont.Weight.Bold)
            cursor.mergeCharFormat(text_format)

            # 重置起始位置
            self.command_start_pos = 0

        except Exception as e:
            self.logger.error(f"Error coloring last command red: {e}")


class BuildTestThread(QThread):
    finished = Signal(Path)
    error = Signal(str)
    test_started = Signal()
    qt_msg_signal = Signal(dict)
    treeview_signal = Signal(dict)
    progress_signal = Signal(int)
    test_finished = Signal(str)
    textEdict_signal = Signal(dict)

    def __init__(
            self,
            sn: str, command_file_path: Path, test_sequence: OrderedDict,
            serial_combos: dict, event: Event, fail_to_break: bool,
            test_path: Path, logger: logging.Logger, test_time: int = 1, show_command_en: bool = False
    ):
        super().__init__()
        self.sn = sn
        self.thread_event = event
        self.command_file_path = command_file_path
        self.command_row_data = test_sequence
        self.serial_combos = serial_combos
        self.serial_channels: dict[str, SerialPortManager] = {}
        self.station_log = logger
        self.test_path = test_path
        self.station_handler: Optional[logging.FileHandler] = None
        self.test_time = test_time
        self.loop_now_time = 0
        self.show_command_en = show_command_en
        self.fail_to_break = fail_to_break

        self.dialog_response = None
        self.condition = QWaitCondition()
        self.mutex = QMutex()

    def run(self):
        try:
            self.build_test_thread()
        except Exception as e:
            self.error.emit(str(e))

    def build_test_thread(self):
        test_fail_time = 0
        while self.loop_now_time < self.test_time:
            if self.thread_event.wait(0.01):
                break

            self.loop_now_time += 1
            if self.loop_now_time > 1:
                time.sleep(1)
            self.test_started.emit()
            self.station_log.debug(f"第{self.loop_now_time}次参数开始")

            if self.test_time > 1:
                now = datetime.now().strftime("%y_%m_%d_%H_%M_%S")
                self.test_path = self.test_path / f"{self.sn}_{now}"
                self.test_path.mkdir()
            station_folder_path = self.test_path / "station_info"
            log_folder_path = self.test_path / "serials_log"
            station_folder_path.mkdir()
            log_folder_path.mkdir()
            self.station_log.handlers.clear()
            self.station_handler = logging.FileHandler(station_folder_path / "station.log")
            self.station_handler.setFormatter(Formatter)
            self.station_log.addHandler(self.station_handler)

            state = "PASS"
            try:
                for serial, info in self.serial_combos.items():
                    en = info.get(f'{serial}_enable').isChecked()
                    port = info.get(f'{serial}_name').currentText()
                    baud = info.get(f'{serial}_baud').currentText()
                    if en and port:
                        log_port = str(port).rsplit(".", 1)[-1]
                        serial_logger = create_logger(
                            f"{serial}_{log_port}", propagate=False,
                            log_path=log_folder_path/f"{serial}_{log_port}.log", time_rotating=False
                        )
                        new_serial = SerialPortManager(
                            parent=None,
                            port=port,
                            baud_rate=baud,
                            timeout=5,
                            logger=serial_logger
                        )
                        new_serial.data_received.connect(self.on_serial_data_received)
                        connect_state = new_serial.connect_serial()
                        if not connect_state:
                            raise Exception(f"{serial} {port} connect fail")
                        self.serial_channels[serial] = new_serial
            except Exception as e:
                self.tset_finish_emit("Broke")
                self.station_log.error(traceback.format_exc())
                self.error.emit("链接串口失败\n" + str(e))
                test_fail_time += 1
                break

            try:
                state = self.run_commands()  # 开始跑sequence
            except Exception as e:
                self.station_log.error(traceback.format_exc())
                self.error.emit(str(e))
            for serial in self.serial_channels.values():
                serial.disconnect_serial()

            self.tset_finish_emit(state)
            if self.test_time > 1:  # 返回到主文件夹
                self.test_path = self.test_path.parent

            if not (state == "PASS"):
                test_fail_time += 1
                if self.fail_to_break:
                    break

        if self.test_time > 1:
            msg = f"{test_fail_time}F/{self.test_time}T"
            self.station_log.info(f"{self.sn} loop测试结束，结果为：" + msg)
            self.rename_result_folder("Loop_" + msg.replace("/", "_"))

        self.finished.emit(self.test_path)

    def run_commands(self) -> str:
        final_state = "PASS"
        result_header = ['NO', 'Item', 'SubTest', 'Serial', 'Command', 'Lower_limit', 'Value', 'Upper_limit', 'Status']
        result_data = [result_header]
        try:
            current_index = 0
            index_list = list(self.command_row_data.keys())
            table_length = len(index_list)
            value_list = {"sn": self.sn, }
            while current_index < table_length:
                if self.thread_event.wait(0.01):
                    break

                index = index_list[current_index]
                row_data = self.command_row_data[index]
                self.station_log.info(f"row{index} data is {str(row_data)}")

                # 实际执行命令的逻辑
                result = self.execute_command(row_data, value_list)
                value_name = row_data.get("ValueName")
                if value_name:
                    value_list[value_name] = result["value"]

                # 更新UI显示结果
                result["index"] = index
                self.treeview_signal.emit(result)
                self.progress_signal.emit(index + 1)

                result_data.append([
                    row_data["Sequence"],
                    row_data["Item"],
                    row_data["SubTest"],
                    row_data["Serial"],
                    row_data["Command"],
                    row_data["LowerLimit"],
                    str(result["value"]),
                    row_data["UpperLimit"],
                    result["status"],
                ])

                final_state = result["status"]
                current_index += 1
                if self.fail_to_break and not (final_state == "PASS"):
                    break
                if not (final_state == "PASS"):
                    new_index = row_data["Fail2Line"]
                    if new_index:
                        if new_index == "END":
                            break
                        if str(new_index).isdigit():
                            current_index = index_list.index(new_index)

            if len(result_data) < table_length:
                final_state = "FAIL"
        except Exception as e:
            final_state = "Broke"
            self.station_log.error(traceback.format_exc())
            self.error.emit(str(e))
        finally:
            del value_list

        try:
            save_data_to_xlsx(
                self.test_path / f'{self.sn}_Result_{final_state}.xlsx',
                result_data, result_header.index("Status"), "FAIL",
                result_header.index("Command")
            )
            shutil.copy2(self.command_file_path, self.test_path / "station_info")
        except Exception as e:
            final_state = "Broke"
            self.station_log.error(traceback.format_exc())
            self.error.emit(str(e))

        self.station_log.info(f"{self.sn}测试结束，结果为：{final_state}")

        return final_state

    def execute_command(self, row_data, temp_list):
        serial = row_data['Serial'].strip() or "serial1"
        command = row_data['Command'].strip().format(**temp_list)
        timeout_ms = 0 if row_data['TimeOut'] == '' else int(row_data['TimeOut'])

        # 发送命令开始标记
        self.textEdict_signal.emit({
            "port": serial,
            "type": "command_start",
            "command": command,
            "color": "start"
        })

        value = ""
        if serial == 'MessageInfoBox' or serial == 'MessageResultBox':
            self.station_log.info(f"{serial} : {command}")
            if self.show_command_en:
                self.textEdict_signal.emit({"port": serial, "msg": f"{serial}:\n{command}", "color": "warning"})
            timeout = timeout_ms / 1000 or 30
            msf_setting = {
                "tittle": serial,
                "info": command,
                "timeout": timeout
            }
            self.qt_msg_signal.emit(msf_setting)
            self.mutex.lock()
            self.condition.wait(self.mutex)
            self.mutex.unlock()
            value = self.dialog_response
            if self.show_command_en:
                self.textEdict_signal.emit({"port": serial, "msg": f"User choose : {value}", "color": "info"})
            self.station_log.info(f"User Select : {value}")
        else:
            delay = timeout_ms or 100
            serial_channel = self.serial_channels[serial]
            for cmd in command.split('\n'):
                cmd = cmd.rstrip()
                if self.show_command_en:
                    self.textEdict_signal.emit(
                        {
                            "port": serial,
                            "type": "serial_data",
                            "msg": f"send: {cmd}",
                            "color": "warning"
                        }
                    )
                self.station_log.info("——"*20)
                self.station_log.info(f"{serial} | send : {cmd}")
                self.station_log.info("——"*20)
                return_data = serial_channel.send_with_response(cmd, delay / 1000).strip()
                self.station_log.info(return_data)
                value += return_data

        parameter = row_data['Parameter'].strip()
        rule = row_data['Rule'].strip()

        low_limit = row_data['LowerLimit'].strip()
        up_limit = row_data['UpperLimit'].strip()
        typ = row_data.get("ValueType", "文字").strip()
        if typ == "公式":
            typ = row_data['Expressions'].strip()

        value, state = process_value(
            value=value, value_type=typ,
            parameter=parameter, rule=rule,
            low_limit=low_limit, up_limit=up_limit,
            value_list=temp_list, logger=self.station_log
        )

        # 发送命令结束标记和状态
        self.textEdict_signal.emit({
            "port": serial,
            "type": "command_end",
            "state": state,
            "value": str(value),
            "color": "end"
        })

        # 如果失败，发送失败标记（这会触发前一段日志标红）
        if state == "FAIL":
            self.textEdict_signal.emit({
                "port": serial,
                "type": "command_failed",
                "command": command,
                "value": str(value),
                "color": "red_marker"
            })

        result = {
            "value": value,
            "status": state
        }
        return result

    def tset_finish_emit(self, result: str):
        self.station_log.removeHandler(self.station_handler)
        # self.station_handler.release()
        self.station_handler.close()
        self.test_finished.emit(result)
        self.rename_result_folder(result)

    def rename_result_folder(self, result: str):
        try:
            new_name = self.test_path.name + "_" + result
            new_folder = self.test_path.with_name(new_name)
            self.test_path = self.test_path.rename(new_folder)
        except Exception as e:
            self.station_log.error(str(e))
            self.station_log.error(traceback.format_exc())

    @Slot(str)
    def set_dialog_result(self, result):
        """设置弹窗结果并唤醒线程"""
        self.dialog_response = result
        self.condition.wakeAll()

    def on_serial_data_received(self, data_dict: dict):
        """处理从串口接收到的数据并转发到主线程"""
        # 这里可以添加数据处理逻辑
        self.textEdict_signal.emit(data_dict)


class MessageBox(QDialog):
    button_clicked = Signal(str)

    def __init__(self, parent, tittle, msg, timeout):
        super().__init__(parent)
        self._result = None
        self.setWindowTitle(tittle)
        self.resize(600, 250)

        # 设置为模态对话框
        self.setModal(True)

        layout = QVBoxLayout()

        label = QLabel(msg)
        label.setFont(QFont("Arial", 25))
        label.setWordWrap(True)
        layout.addWidget(label)

        button_layout = QHBoxLayout()

        if tittle == 'MessageInfoBox':
            btn = QPushButton("OK")
            btn.setFont(QFont("Arial", 25))
            btn.setStyleSheet("background-color: rgb(22, 135, 255);")
            btn.clicked.connect(lambda: self.on_button_clicked("ok"))
            button_layout.addWidget(btn)
        else:
            yes_btn = QPushButton("YES")
            yes_btn.setFont(QFont("Arial", 25))
            yes_btn.setStyleSheet("background-color: rgb(22, 135, 255);")
            yes_btn.clicked.connect(lambda: self.on_button_clicked("yes"))
            button_layout.addWidget(yes_btn)

            no_btn = QPushButton("NO")
            no_btn.setFont(QFont("Arial", 25))
            no_btn.clicked.connect(lambda: self.on_button_clicked("no"))
            button_layout.addWidget(no_btn)

        # 超时显示标签
        self.time_label = QLabel(f"Time left: {timeout}s")
        self.time_label.setFont(QFont("Arial", 20))
        layout.addWidget(self.time_label)

        layout.addLayout(button_layout)
        self.setLayout(layout)

        # 设置定时器
        self.timer = QTimer()
        self.timer.timeout.connect(self.time_refresh)
        self.timer.start(1000)
        self.time_left = timeout

    def time_refresh(self):
        self.time_left -= 1
        self.time_label.setText(f"Time left: {self.time_left}s")
        if self.time_left <= 0:
            self.on_button_clicked("TimeOut")

    def on_button_clicked(self, result):
        self._result = result
        self.button_clicked.emit(result)  # 停止定时器
        self.accept()


class TreeviewInfoBox(QDialog):
    def __init__(self, parent, values: dict):
        super().__init__(parent)
        self.setWindowTitle("Item Info")

        layout = QGridLayout()
        # layout.setContentsMargins(0, 0, 0, 0)
        # layout.setSpacing(5)
        layout.addWidget(QLabel("No:"), 0, 0)
        layout.addWidget(QLabel(values["No"]), 0, 1, 1, 5)
        layout.addWidget(QLabel("Item:"), 1, 0)
        layout.addWidget(QLineEdit(values["Item"]), 1, 1, 1, 5)
        layout.addWidget(QLabel("Serial:"), 2, 0)
        layout.addWidget(QLineEdit(values["Serial"]), 2, 1, 1, 5)
        layout.addWidget(QLabel("Command:"), 3, 0)
        layout.addWidget(QLineEdit(values["Command"]), 3, 1, 1, 5)
        layout.addWidget(QLabel("Lower Limit:"), 4, 0)
        layout.addWidget(QLineEdit(values["Lower_limit"]), 4, 1)
        layout.addWidget(QLabel("State:"), 4, 2)
        layout.addWidget(QLineEdit(values["Status"]), 4, 3)
        layout.addWidget(QLabel("Upper Limit:"), 4, 4)
        layout.addWidget(QLineEdit(values["Upper_limit"]), 4, 5)
        layout.addWidget(QLabel("Value:"), 5, 0)
        layout.addWidget(QTextEdit(values["Value"]), 5, 1, 3, 5)

        ok_button = QPushButton("OK")
        ok_button.setFont(QFont("Arial", 16))
        ok_button.setStyleSheet("background-color: rgb(22, 135, 255);")
        ok_button.clicked.connect(self.accept)
        layout.addWidget(ok_button, 8, 0, 1, 6)

        self.setLayout(layout)


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = MainWindow(name="EEFCT", version="0.0.1", logger=None, dryrun=True)
        window.show()
        sys.exit(app.exec())
    except Exception as ex:
        print(f"程序崩溃: {ex}")
        traceback.print_exc()
        input("按回车键退出...")
