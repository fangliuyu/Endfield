import importlib
import os
import subprocess
import time
from datetime import datetime
from importlib import util
import logging
import sys
import traceback
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Union, Dict, Optional

from PySide6.QtCore import Slot, QThread, Signal, QObject
from PySide6.QtGui import QPixmap, QIntValidator, QDoubleValidator, Qt, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QPushButton, QLabel,
    QComboBox, QSizePolicy, QLineEdit, QFileDialog,
    QCheckBox, QSplitter, QTreeWidget, QTabWidget,
    QTextEdit, QTreeWidgetItem, QHeaderView, QMessageBox
)

from lib.uartSerial.QtSerial import SerialPortManager
from lib.uartSerial.scan import get_serial_bauds_str, get_serial_ports
from lib.uartSerial.SerialAgent import UARTSerial
from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_osc import InfiniiumCatAOsc, TektronixOsc, OscAgnet, Instrument_Dryrun, check_osc_type, create_osc_agent
from lib.qtui.custom_widget import build_group_box, ImageLabel, LogTextEdit
from lib.filetools import copy_without_overwrite, read_data_from_yaml, save_data_to_yaml

from .read_spec import read_spec_excel
from .worker_analyzer import build_analyzer_work
from .protocol_frame import ProtocolFrame, ProtocolBaseConfig
from .setting import SetupData
from .worker_summary import build_summary_work
from .worker_waveform import build_waveform_catch


def create_osc(osc_info: str, address: str, cata_list: list[str], tek_list: list[str], logger=None):
    if "demo" in osc_info:
        return Instrument_Dryrun(instrument_address=address, logger=logger)
    elif check_osc_type(osc_info, cata_list):
        return InfiniiumCatAOsc(instrument_address=address, logger=logger)
    elif check_osc_type(osc_info, tek_list):
        return TektronixOsc(instrument_address=address, logger=logger)
    else:
        return OscAgnet(instrument_address=address, logger=logger)


int_validator = QIntValidator(0, 255)
double_validator = QDoubleValidator(0.01, 100.0, 2)
double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)


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
        self.spc_file = self.data_path / "specification"
        copy_without_overwrite(Path(__file__).parent.parent / 'specification', self.spc_file)
        self.result_dir = self.data_path / "result"
        if not self.result_dir.exists():
            self.result_dir.mkdir()
        self.osc_normal_list = get_device_patterns("osc_normal")
        self.osc_cata_list = get_device_patterns("osc_cata")
        self.osc_tek_list = get_device_patterns("osc_tek")
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[Union[InfiniiumCatAOsc, OscAgnet]] = None
        self.connected = False
        self.serial: Optional[SerialPortManager] = None
        self.frames: Dict[str, ProtocolFrame] = {}
        self.test_item = ""
        self.spec_df = None
        self.picture_list = []
        self.image_index = 0
        self.run_status = False
        self.run_thread: Optional[Worker] = None
        self.osc_logger = self.logger.getChild("osc_log")
        self.unit_logger = self.logger.getChild("unit_log")
        self.analyzer_logger = self.logger.getChild("analyzer_log")
        self.datafile = self.result_dir

        self.setWindowTitle(f"SITools{version}")
        self.resize(800, 600)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)

        # 结果区域
        result_widget = QWidget()
        result_layout = QVBoxLayout(result_widget)
        result_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(5)
        splitter.addWidget(result_widget)

        # 表格
        self.treeview = QTreeWidget()
        self.treeview.setMinimumHeight(200)
        self.treeview.setHeaderLabels(["No", "Net.", "Item", "lower_limit", "value", "upper_limit", "Unit", "status"])
        result_layout.addWidget(self.treeview)

        self.image_label = ImageLabel()
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.image_label.setMinimumSize(850, 400)
        result_layout.addWidget(self.image_label, 1)
        self.show_img_from_path(Path(__file__).parent.parent / "logo.png")
        img_btn_widget = QWidget()
        img_btn_widget.setFixedHeight(60)
        result_layout.addWidget(img_btn_widget)
        img_btn_layout = QHBoxLayout(img_btn_widget)
        prev_btn = QPushButton("<")
        prev_btn.setFont(QFont("", 32, QFont.Weight.Bold))
        prev_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        prev_btn.clicked.connect(self.last_img)
        next_btn = QPushButton(">")
        next_btn.setFont(QFont("", 32, QFont.Weight.Bold))
        next_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        next_btn.clicked.connect(self.next_img)
        self.image_name_label = QLabel("暂无图片展示", alignment=Qt.AlignmentFlag.AlignCenter)
        self.image_name_label.setFont(QFont("", 32, QFont.Weight.Bold))
        img_btn_layout.addStretch(1)
        img_btn_layout.addWidget(prev_btn)
        img_btn_layout.addWidget(self.image_name_label, 2)
        img_btn_layout.addWidget(next_btn)
        img_btn_layout.addStretch(1)

        # 设置区域
        setup_widget = QWidget()
        setup_widget.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Minimum)
        setup_widget.setMinimumWidth(500)
        setup_layout = QVBoxLayout(setup_widget)
        setup_layout.setContentsMargins(0, 0, 0, 0)
        setup_layout.setSpacing(5)
        splitter.addWidget(setup_widget)

        load_btn_layout = QHBoxLayout()
        setup_layout.addLayout(load_btn_layout)
        load_btn_layout.addWidget(QLabel("Protocol Setup"))
        load_btn_layout.addStretch(1)
        save_setup_btn = QPushButton("save")
        save_setup_btn.clicked.connect(self.save_setup)
        load_btn_layout.addWidget(save_setup_btn)
        load_setup_btn = QPushButton("load")
        load_setup_btn.clicked.connect(self.load_setup)
        load_btn_layout.addWidget(load_setup_btn)

        # 功能选项卡
        self.notebook = QTabWidget()
        self.notebook.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #C2C7CB;
                top: -1px;
            }
            QTabWidget::tab-bar {
                alignment: left;  /* 标签栏整体左对齐 */
            }
            QTabBar::tab {
                background-color: #F0F0F0;
                border: 1px solid #C2C7CB;
                padding-left: 8px;
                padding-right: 8px;
                padding-top: 4px;
                padding-bottom: 4px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #FFFFFF;
                border-bottom-color: #FFFFFF;
            }
            QTabBar::tab:hover:!selected {
                background-color: #E0E0E0;
            }
        """)
        self.notebook.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.notebook.currentChanged.connect(self.change_tab)
        setup_layout.addWidget(self.notebook)
        self.load_frames()

        # 示波器设置
        osc_group, osc_layout = build_group_box("Oscilloscope Setup", QVBoxLayout(), title_y=0)
        osc_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        setup_layout.addWidget(osc_group)
        osc_layout.setContentsMargins(0, 0, 0, 0)
        osc_layout.setSpacing(0)
        osc_device_layout = QHBoxLayout()
        osc_device_layout.setContentsMargins(0, 0, 0, 0)
        osc_device_layout.setSpacing(5)
        osc_layout.addLayout(osc_device_layout)
        self.osc_devices = QComboBox()
        self.osc_devices.setEditable(False)
        self.osc_devices.currentTextChanged.connect(self.choose_devices_list)
        osc_device_layout.addWidget(self.osc_devices, 1)
        self.dryrun_box = QCheckBox("dryrun")
        self.dryrun_box.setChecked(dry_run)
        self.dryrun_box.stateChanged.connect(self.switch_dryrun)
        osc_device_layout.addWidget(self.dryrun_box)
        osc_horizon_layout = QHBoxLayout()
        osc_horizon_layout.setContentsMargins(0, 0, 0, 0)
        osc_horizon_layout.setSpacing(5)
        osc_layout.addLayout(osc_horizon_layout)
        osc_horizon_layout.addWidget(QLabel("horizon"))
        self.osc_horizon_range = QLineEdit("10")
        self.osc_horizon_range.setMaximumWidth(50)
        osc_horizon_layout.addWidget(self.osc_horizon_range)
        osc_horizon_layout.addWidget(QLabel("ms/"))
        osc_horizon_layout.addStretch(1)
        osc_horizon_layout.addWidget(QLabel("trigger position"))
        self.osc_horizon_position = QLineEdit("0")
        self.osc_horizon_position.setMaximumWidth(50)
        osc_horizon_layout.addWidget(self.osc_horizon_position)
        osc_horizon_layout.addWidget(QLabel("ms"))
        osc_horizon_layout.addStretch(1)
        osc_horizon_layout.addWidget(QLabel("points"))
        self.osc_horizon_points = QLineEdit("100000000")
        self.osc_horizon_points.setMaximumWidth(80)
        osc_horizon_layout.addWidget(self.osc_horizon_points)
        self.choose_devices_list()

        # 命令设置
        cmd_group, cmd_layout = build_group_box("Command Setup", QVBoxLayout(), title_y=0)
        cmd_group.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        setup_layout.addWidget(cmd_group)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(0)
        self.unit_enable = QCheckBox("Use tools to send command")
        self.unit_enable.setFont(QFont("", 18, QFont.Weight.Bold))
        self.unit_enable.setChecked(True)
        cmd_layout.addWidget(self.unit_enable)

        unit_device_layout = QHBoxLayout()
        unit_device_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        unit_device_layout.setContentsMargins(0, 0, 0, 0)
        unit_device_layout.setSpacing(5)
        cmd_layout.addLayout(unit_device_layout)
        self.unit_devices = QComboBox()
        self.unit_devices.setEditable(False)
        self.unit_devices.currentTextChanged.connect(self.choose_unit_list)
        unit_device_layout.addWidget(self.unit_devices, 3)
        self.refresh_unit_list()
        self.unit_baud = QComboBox()
        self.unit_baud.setEditable(True)
        self.unit_baud.addItems(get_serial_bauds_str())
        self.unit_baud.setCurrentText('230400')
        unit_device_layout.addWidget(self.unit_baud, 1)

        # 初始化命令
        cmd_layout.addWidget(QLabel("Initialization commands"))
        self.init_commands = QTextEdit()
        self.init_commands.setMaximumHeight(30)
        self.init_commands.setMinimumWidth(250)
        cmd_layout.addWidget(self.init_commands)

        # 触发命令
        cmd_layout.addWidget(QLabel("<font color='red'>*</font>Trigger commands"))
        self.trig_commands = QTextEdit()
        self.trig_commands.setMaximumHeight(30)
        self.trig_commands.setMinimumWidth(250)
        cmd_layout.addWidget(self.trig_commands)

        # 日志区域
        log_label = QLabel("Run log", alignment=Qt.AlignmentFlag.AlignLeft)
        log_label.setFont(QFont("", 18, QFont.Weight.Bold))
        setup_layout.addWidget(log_label)
        self.log_text = LogTextEdit(logger=self.logger, level=logging.INFO, show_level=False, show_color=True)
        self.log_text.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.log_text.setFixedHeight(100)
        self.log_text.setMinimumWidth(250)
        setup_layout.addWidget(self.log_text, 1)

        # 文件命名
        file_name_layout = QHBoxLayout()
        file_name_layout.setContentsMargins(0, 0, 0, 0)
        file_name_layout.setSpacing(5)
        file_name_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        setup_layout.addLayout(file_name_layout)
        file_name_layout.addWidget(QLabel("Output File name"))
        self.debug_enable = QCheckBox("debug")
        self.debug_enable.stateChanged.connect(self.debug_state)
        file_name_layout.addWidget(self.debug_enable)
        self.osc_run_en = QCheckBox("OSC_RUN")
        self.osc_run_en.setChecked(True)
        self.osc_run_en.setEnabled(False)
        file_name_layout.addWidget(self.osc_run_en)
        self.analyze_run_en = QCheckBox("Analyzer_RUN")
        self.analyze_run_en.setChecked(True)
        self.analyze_run_en.setEnabled(False)
        file_name_layout.addWidget(self.analyze_run_en)
        self.summary_run_en = QCheckBox("Summary_RUN")
        self.summary_run_en.setChecked(True)
        self.summary_run_en.setEnabled(False)
        file_name_layout.addWidget(self.summary_run_en)

        # 文件名输入
        file_input_layout = QHBoxLayout()
        setup_layout.addLayout(file_input_layout)
        file_input_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.result_name = QLineEdit()
        self.result_name.setMinimumWidth(100)
        file_input_layout.addWidget(self.result_name, 2)
        file_input_layout.addWidget(QLabel("-"))
        self.result_sub_name = QLineEdit()
        self.result_sub_name.setMinimumWidth(50)
        file_input_layout.addWidget(self.result_sub_name, 1)
        file_input_layout.addWidget(QLabel("-"))
        self.result_sub_sub_name = QLineEdit()
        self.result_sub_sub_name.setMinimumWidth(50)
        file_input_layout.addWidget(self.result_sub_sub_name, 1)

        # 开始按钮区域
        start_layout = QHBoxLayout()
        setup_layout.addLayout(start_layout)
        self.run_btn = QPushButton("Start")
        self.run_btn.setFont(QFont("", 72, QFont.Weight.Bold))
        self.run_btn.setStyleSheet("color: blue;")
        self.run_btn.clicked.connect(self.run_btn_status_change)
        start_layout.addWidget(self.run_btn, 1)
        open_result_btn = QPushButton("Open result")
        open_result_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        open_result_btn.clicked.connect(self.open_result)
        start_layout.addWidget(open_result_btn)

        # 设置分割比例
        splitter.setSizes([1500, 500])

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

    def load_setup(self):
        file_name, _ = QFileDialog.getOpenFileName(self, "选择文件", self.result_dir.as_posix(), "setup文件 (*.siset)")
        if not file_name:
            return

        yaml_data = read_data_from_yaml(Path(file_name))
        if yaml_data == {}:
            self.logger.error("Unable to resolve the setup file")
            return
        try:
            setup_info = SetupData(**yaml_data)
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(self, "Parameters are missing", str(e))
            return
        # 测试名称
        self.result_name.setText(setup_info.TestItem.Name)
        self.result_sub_name.setText(setup_info.TestItem.SubName)
        self.result_sub_sub_name.setText(setup_info.TestItem.SubSubName)
        # 协议选择
        note_data = setup_info.Analysis
        self.notebook.setCurrentIndex(note_data.ID)
        si_frame: Optional[ProtocolFrame, QWidget] = self.notebook.currentWidget()
        # 设置协议内容
        channels_info = {}
        channel_list = setup_info.Oscilloscope.Channel
        for channel, info in channel_list.items():
            channels_info[info.Net] = (info.EN, int(str(channel).replace("channel", "")), info.Label)
        protocol_config = ProtocolBaseConfig(
            protocol=note_data.Name,
            spec_file=note_data.Configuration.get("specification", ""),
            base_voltage=note_data.Configuration.get("voltage", 1.2),
            thresholds=note_data.Configuration.get("thresholds", (0.3, 0.7)),
            trigger_func=note_data.Configuration.get("trigger", ("", "rising")),
            channel_list=channels_info,
            protocol_configuration=note_data.Configuration,
        )
        si_frame.load_config(protocol_config)
        # 设置示波器配置
        horizon_data = setup_info.Oscilloscope.Horizon
        if horizon_data:
            self.osc_horizon_range.setText(str(horizon_data.Range))
            self.osc_horizon_position.setText(str(horizon_data.Position))
            self.osc_horizon_points.setText(str(horizon_data.Points))
        # 设置产品串口配置
        cmd_data = setup_info.Uart
        if cmd_data:
            self.unit_enable.setChecked(cmd_data.EN)
            self.unit_baud.setCurrentText(str(cmd_data.Baud))
            self.init_commands.setPlainText(cmd_data.InitCommand)
            self.trig_commands.setPlainText(cmd_data.TriggerCommand)

    def save_setup(self):
        file_name, _ = QFileDialog.getSaveFileName(self, "选择文件", self.result_dir.as_posix(), "setup文件 (*.siset)")
        if not file_name:
            return
        self.save_setup_to_file(Path(file_name))

    def save_setup_to_file(self, file_path: Path):
        yaml_data: dict[str, dict] = {
            "TestItem": {
                "TestName": self.result_name.text(),
                "SubName": self.result_sub_name.text(),
                "SubSubName": self.result_sub_sub_name.text(),
            },
        }
        note_id = self.notebook.currentIndex()
        note_tab = self.notebook.tabText(note_id)
        yaml_data["analysis"] = {
            "ID": note_id,
            "Name": note_tab,
        }
        yaml_data["oscilloscope"] = {
            "horizon": {
                "range": self.osc_horizon_range.text(),
                "position": self.osc_horizon_position.text(),
                "points": self.osc_horizon_points.text(),
            }
        }

        si_frame: Optional[ProtocolFrame, QWidget] = self.notebook.currentWidget()

        protocol_config: ProtocolBaseConfig = si_frame.dump_config()

        yaml_data["analysis"]["configuration"] = {
            "specification": protocol_config.spec_file,
            "voltage": protocol_config.base_voltage,
            "thresholds": protocol_config.thresholds,
        }
        for key, value in protocol_config.protocol_configuration.items():
            yaml_data["analysis"]["configuration"][key] = value.get()

        yaml_data["oscilloscope"]["channel"] = {}
        for net, info in protocol_config.channel_list.items():
            yaml_data["oscilloscope"]["channel"][info[1]] = {
                "en": info[0],
                "net": net,
                "name": info[2],
            }
            if net == protocol_config.trigger_func[0]:
                yaml_data["oscilloscope"]["trigger"] = {
                    "channel": info[1],
                    "edge": protocol_config.trigger_func[1],
                }

        yaml_data["uart"] = {
            "en": self.unit_enable.isChecked(),
            "baud": self.unit_baud.currentText(),
            "init": self.init_commands.toPlainText().strip(),
            "trigger": self.trig_commands.toPlainText().strip(),
        }
        save_data_to_yaml(yaml_data, file_path)
        setup_config = SetupData(**yaml_data)
        return setup_config

    def load_frames(self):
        # 动态加载框架模块
        frames_dir = Path(__file__).parent / "frames"
        self.logger.info(f"[add tab frame] from {frames_dir.as_posix()} load modules")
        files = frames_dir.glob('*.py')

        # 获取当前插件的包名
        package_name = __package__

        for file_path in sorted(files, key=lambda x: x.name):
            if file_path.name != "__init__.py":
                module_name = file_path.stem
                # 构造完整的模块路径，以便支持相对导入
                full_module_name = f"{package_name}.frames.{module_name}" if package_name else module_name

                self.logger.info(f"[add tab frame] load module {full_module_name} form {file_path}")
                try:
                    spec = importlib.util.spec_from_file_location(
                        full_module_name,
                        file_path.as_posix()
                    )
                    module = importlib.util.module_from_spec(spec)
                    # 关键：设置 __package__ 属性，使得相对导入 ..protocol_frame 能够生效
                    if package_name:
                        module.__package__ = f"{package_name}.frames"

                    spec.loader.exec_module(module)
                    frame_class = getattr(module, module_name)
                    tab_name = module_name.replace("_Frame", "")
                    frame_instance: ProtocolFrame = frame_class(
                        parent=None, name=tab_name, spec_path=self.spc_file, logger=self.logger
                    )
                    frame_instance.specChanged.connect(self.update_table)
                    self.notebook.addTab(frame_instance, tab_name)
                    self.logger.info(f"[add tab frame] load module {module_name} successfully")
                except Exception as e:
                    self.logger.error(traceback.format_exc())
                    self.logger.error(f"[add tab frame] Failed to load frame {module_name}: {e}")

    @Slot(int)
    def change_tab(self, index: int):
        self.logger.debug(f"user change tab frame to {index} {self.notebook.tabText(index)}")
        si_frame: Optional[ProtocolFrame, QWidget] = self.notebook.currentWidget()
        si_frame.change_spec_signal()

    @Slot(Path, float)
    def update_table(self, spc_file: Path, voltage: float):
        if not spc_file.exists():
            self.logger.error("load spc excel fail: the excel file doesn't exist")
            return

        self.logger.info(f"load spc excel: {spc_file.parent.name}/{spc_file.name}, voltage is {voltage}")
        self.spec_df = read_spec_excel(spc_file, str(voltage))
        if self.spec_df is None:
            self.logger.error("load spc excel fail: the excel file doesn't have any data")
            return
        self.treeview.clear()
        info = {}
        names = self.spec_df.columns.tolist()
        for i in range(len(names)):
            info[names[i]] = i

        for index, row in self.spec_df.iterrows():
            item = QTreeWidgetItem([
                str(index + 1),  # NOQA
                str(row.iloc[info.get("Net.", 0)]),
                str(row.iloc[info.get("Measurement", 1)]),
                str(row.iloc[info.get("Lower Limit", 2)]),
                "",
                str(row.iloc[info.get("Upper Limit", 5)]),
                str(row.iloc[info.get("Unit", 6)]),
                ""
            ])
            self.treeview.addTopLevelItem(item)
        header = self.treeview.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.logger.info("load excel successfully")

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
            ok, class_name, sn = check_device_module(address, self.osc_normal_list)
            self.logger.debug(f"{index}.{sn}: {class_name}")
            if ok:
                sn_list.append(class_name + ": " + sn)
                self.devices_list[sn] = address
                self.logger.debug(f"{class_name}为所需仪器，加入列表")
        self.logger.info(f"当前识别到了{len(sn_list)-1}个仪器")
        if self.dryrun:
            sn_list.append("KeysightTechnologiesMSOX4054A(demo): MY114514")
            self.devices_list["MY114514"] = "USB0::0x2A8D::0x0101::________:INSTR"
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
        self.device = create_osc(osc_info=self.name, address=self.devices_list[self.sn], cata_list=self.osc_cata_list, tek_list=self.osc_tek_list, logger=self.logger)
        self.device.connect(reset=False)
        self.connected = True

    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.device = None
            self.connected = False

    def choose_unit_list(self):
        self.unit_devices.blockSignals(True)
        current_text = self.unit_devices.currentText()
        if current_text and current_text != "刷新列表":
            self.logger.info(f"用户选择了{current_text}")
        else:
            self.refresh_unit_list()
        self.unit_devices.blockSignals(False)

    def refresh_unit_list(self):
        com_scan = [""]
        if sys.platform == 'win32':
            com_scan += [com.name for com in get_serial_ports()]
        else:
            com_scan += [f'/dev/{com.name}' for com in get_serial_ports()]
        if com_scan:
            self.logger.info(f'当前可用端口\n{com_scan}')
        else:
            self.logger.warning("未找到设备端口")
        com_scan.append("刷新列表")

        self.unit_devices.clear()
        self.unit_devices.addItems(com_scan)
        self.unit_devices.setCurrentIndex(0)

    def show_img_from_path(self, img_path: Path):
        if img_path.exists():
            pixmap = QPixmap(str(img_path))
            self.image_label.setPixmap(pixmap.scaled(850, 500, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.logger.error(f"picture [{img_path.as_posix()}] is not existed")

    def update_img_show(self, img_name):
        if not img_name:
            self.logger.error("picture name is None")
            return
        self.logger.info(f"choose picture [{img_name}.png]")

        img_path = self.result_dir / "picture" / (img_name + ".png")
        if img_path.exists():
            self.image_name_label.setText(img_name)
            self.show_img_from_path(img_path)

    def last_img(self):
        if not self.picture_list:
            return

        self.image_index -= 1
        if self.image_index < 0:
            self.image_index = len(self.picture_list) - 1

        self.update_img_show(self.picture_list[self.image_index])

    def next_img(self):
        if not self.picture_list:
            return

        self.image_index += 1
        if self.image_index >= len(self.picture_list):
            self.image_index = 0

        self.update_img_show(self.picture_list[self.image_index])

    def tree_view_click(self, item, column):
        if not item:
            return
        self.logger.info(f"user choose item {item} {column}")
        index = self.treeview.indexOfTopLevelItem(item)
        values = [item.text(i) for i in range(self.treeview.columnCount())]
        self.image_index = index
        img_name = f"{values[1]} {values[2].replace(':', '_')}"
        if img_name:
            self.update_img_show(img_name)

    def debug_state(self):
        if self.debug_enable.isChecked():
            self.osc_run_en.setEnabled(True)
            self.analyze_run_en.setEnabled(True)
            self.summary_run_en.setEnabled(True)
        else:
            self.osc_run_en.setChecked(True)
            self.analyze_run_en.setChecked(True)
            self.summary_run_en.setChecked(True)
            self.osc_run_en.setEnabled(False)
            self.analyze_run_en.setEnabled(False)
            self.summary_run_en.setEnabled(False)

    def run_btn_status_change(self):
        self.run_btn.setStyleSheet("color: gray;")
        self.run_btn.setEnabled(False)
        self.run_status = not self.run_status
        if self.run_status:
            self.run_thread.stop()
            return

        output_name = self.result_name.text().strip()
        if not output_name and not self.debug_enable.isChecked():
            QMessageBox.information(self, "Parameters are missing", "please entry the output File name")
            self.run_btn.setEnabled(True)
            self.run_btn.setStyleSheet("color: blue;")
            return
        if not self.sn:
            QMessageBox.information(self, "Parameters are missing", "please select OSC device address")
            self.run_btn.setEnabled(True)
            self.run_btn.setStyleSheet("color: blue;")
            return
        if self.unit_enable.isChecked():
            if self.unit_devices.currentText() == "":
                QMessageBox.information(
                    self, "Parameters are missing", "please select unit uart com or disable to send command"
                )
                self.run_btn.setEnabled(True)
                self.run_btn.setStyleSheet("color: blue;")
                return

        self.picture_list = []
        self.image_name_label.setText("暂无图片展示")
        self.show_img_from_path(Path(__file__).parent.parent / "logo.png")

        self.run_si_generate()

    def open_result(self):
        if self.result_name.text() or self.debug_enable.isChecked():
            if sys.platform == 'win32':
                os.startfile(self.datafile)
            else:
                subprocess.run(['open', self.datafile])

    def run_si_generate(self):
        output_name = self.result_name.text().strip()
        if not output_name and self.debug_enable.isChecked():
            output_name = "dryrun"

        self.datafile = self.result_dir / output_name
        if not self.datafile.exists():
            self.datafile.mkdir()

        output_sub_name = self.result_sub_name.text()
        if output_sub_name:
            output_name += "-" + output_sub_name

        output_sub_sub_name = self.result_sub_sub_name.text()
        if output_sub_sub_name:
            output_name += "-" + output_sub_sub_name

        if not self.debug_enable.isChecked():
            timestamp = datetime.now().strftime("%H_%M_%S-%Y_%m_%d")
            self.datafile = self.datafile / (output_name + "-" + timestamp)
        else:
            folder_list = [entry for entry in self.datafile.iterdir() if entry.is_dir()]
            folder_list.sort(key=lambda x: x.name)
            if not folder_list:
                if output_name:
                    self.datafile = self.datafile / (output_name + "- dryrun")
                else:
                    self.datafile = self.datafile / "test"
            else:
                self.datafile = self.datafile / folder_list[-1]
        if not self.datafile.exists():
            self.datafile.mkdir()
            (self.datafile / "setup").mkdir()
            (self.datafile / "picture").mkdir()
            (self.datafile / "log").mkdir()
            (self.datafile / "waveform").mkdir()

        self.logger.info("pre-start run...")
        test_config = self.save_setup_to_file(self.datafile / "setup/setup.siset")
        sequence = {}

        if self.osc_run_en.isChecked():
            # 创建示波器连接
            for handler in self.osc_logger.handlers:
                self.osc_logger.removeHandler(handler)
            self.osc_logger.addHandler(logging.FileHandler(self.datafile / "log/osc_log.log"))
            self.device = create_osc(osc_info=self.name, address=self.devices_list[self.sn], cata_list=self.osc_cata_list, tek_list=self.osc_tek_list, logger=self.osc_logger)

            for handler in self.unit_logger.handlers:
                self.unit_logger.removeHandler(handler)
            if self.unit_enable.isChecked():
                self.unit_logger.addHandler(logging.FileHandler(self.datafile / "log/unit_log.log"))
                self.serial = UARTSerial(
                    port=self.unit_devices.currentText(),
                    baud_rate=int(self.unit_baud.currentText()),
                    timeout=5,
                )
                self.serial.set_serial_log(self.unit_logger)
            else:
                self.serial = None

            waveform_sequence = build_waveform_catch(
                parent=None, config=test_config, osc_device=self.device,
                unit_serial=self.serial, data_folder=self.datafile / "waveform"
            )
            sequence["waveform"] = waveform_sequence
        else:
            self.device = None
            self.serial = None

        if self.analyze_run_en.isChecked():
            # 创建analyzer logger
            for handler in self.analyzer_logger.handlers:
                self.analyzer_logger.removeHandler(handler)
            self.analyzer_logger.addHandler(logging.FileHandler(self.datafile / "log/analyzer_log.log"))
            analyzer_sequence = build_analyzer_work(
                parent=None, config=test_config, spec_df=self.spec_df,
                analyzer_logger=self.analyzer_logger, data_folder=self.datafile
            )
            sequence["analyzer"] = analyzer_sequence

        if self.summary_run_en.isChecked():
            summary_sequence = build_summary_work(parent=None, logger=self.logger, data_folder=self.datafile)
            sequence["summary"] = summary_sequence

        self.run_thread = Worker(parent=self, sequence=sequence, logger=self.logger)
        self.run_thread.finish_signal.connect(self.run_finish)
        self.run_thread.run()

    def run_finish(self, state: bool):
        if state:
            self.run_btn.setEnabled(True)
            self.run_btn.setStyleSheet("color: blue;")
            return


class Worker(QThread):
    finish_signal = Signal(bool)

    def __init__(self, parent: Optional[QObject], sequence: dict, logger: logging.Logger):
        super().__init__(parent)
        self.sequence = sequence
        self.sequence_keys = self.sequence.keys()
        self.logger = logger
        self._is_running = True
        self.spec_df = None

    def run(self):
        start_time = time.time()
        try:
            if "waveform" in self.sequence_keys:
                worker = self.sequence["waveform"]
                worker.run()
            if "analyzer" in self.sequence_keys:
                worker = self.sequence["analyzer"]
                self.spec_df = worker.run()
            if "summary" in self.sequence_keys:
                worker = self.sequence["summary"]
                worker.run()
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)
        finally:
            elapsed = time.time() - start_time
            self.logger.info(f"Total runtime: {elapsed:.3f} seconds")
            self.finish_signal.emit(self.spec_df)

    def stop(self):
        self._is_running = False
