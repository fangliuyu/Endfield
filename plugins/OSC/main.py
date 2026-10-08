import logging
import re
import sys
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Union

from PySide6.QtGui import QColor, QPixmap, QIntValidator, QDoubleValidator
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel,
                               QFrame, QGridLayout, QComboBox, QSizePolicy, QLineEdit, QMessageBox, QFileDialog,
                               QCheckBox, QButtonGroup, QToolButton, QMenu, QWidgetAction)

from lib.deviceCheck import auto_connected
from lib.qtui.custom_widget import build_group_box, SwitchButton, ImageLabel, show_toast
from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_osc import (
    Measure_Dict, SourceWaveformType,
    SourceTriggerType, TriggerSlopeType, create_osc_agent
)


int_validator = QIntValidator(0, 255)
double_validator = QDoubleValidator(0.01, 100.0, 2)
double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: Logger = None, dry_run=False,
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
        self.pic_dir = self.data_path / "pictures"
        if not self.pic_dir.exists():
            self.pic_dir.mkdir()
        osc_list: dict = get_device_patterns("OSC")
        self.osc_normal_list = osc_list.get("osc_all", [])
        self.osc_cata_list = osc_list.get("osc_cata", [])
        self.osc_tek_list = osc_list.get("osc_tek", [])
        self.logger.debug(f"load devices file list: {self.osc_normal_list}")
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device = None
        self.connected = False
        self.lastName = ""
        self.img_data = None
        self.img_saved = False
        self.current_horizon_mode = ""
        self.current_trigger_mode = ""

        self.setWindowTitle(f"示波器控制器V{version}")
        self.resize(800, 600)

        self.setAutoFillBackground(True)
        self.palette = self.palette()
        self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
        self.setPalette(self.palette)

        main_widget = QFrame()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        left_layout = QVBoxLayout()
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(5)
        main_layout.addLayout(left_layout, 1)
        right_layout = QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(5)
        main_layout.addLayout(right_layout)

        base_setting_layout = QHBoxLayout()
        base_setting_layout.setContentsMargins(0, 0, 0, 0)
        base_setting_layout.setSpacing(5)
        left_layout.addLayout(base_setting_layout)
        # RunControl
        run_control_group, control_btn_layout = build_group_box("RunControl", QVBoxLayout())
        base_setting_layout.addWidget(run_control_group)
        btn_setting_layout = QHBoxLayout()
        btn_setting_layout.setContentsMargins(0, 0, 0, 0)
        btn_setting_layout.setSpacing(5)
        control_btn_layout.addLayout(btn_setting_layout)
        self.control_btn_group = QButtonGroup(self)
        self.control_btn_group.buttonClicked.connect(self.btn_state_changed)
        run_btn = QPushButton("RUN")
        run_btn.setStyleSheet("background-color: green;")
        self.control_btn_group.addButton(run_btn)
        btn_setting_layout.addWidget(run_btn)
        stop_btn = QPushButton("STOP")
        stop_btn.setStyleSheet("background-color: red;")
        self.control_btn_group.addButton(stop_btn)
        btn_setting_layout.addWidget(stop_btn)
        single_btn = QPushButton("SINGLE")
        single_btn.setStyleSheet("background-color: yellow;")
        self.control_btn_group.addButton(single_btn)
        btn_setting_layout.addWidget(single_btn)

        # trigger
        trigger_settings_group, trigger_settings_layout = build_group_box("Trigger", QVBoxLayout())
        trigger_settings_layout.setContentsMargins(0, 0, 0, 0)
        trigger_settings_layout.setSpacing(0)
        control_btn_layout.addWidget(trigger_settings_group)
        trigger_mode_layout = QHBoxLayout()
        trigger_mode_layout.setContentsMargins(0, 0, 0, 0)
        trigger_mode_layout.setSpacing(5)
        trigger_settings_layout.addLayout(trigger_mode_layout)
        trigger_mode_layout.addWidget(QLabel('Mode'))
        self.trigger_mode_box = QComboBox()
        self.trigger_mode_box.addItems(['AUTO', 'NORMal'])
        self.trigger_mode_box.setCurrentIndex(0)
        trigger_mode_layout.addWidget(self.trigger_mode_box, 1)
        trigger_apply_btn = QPushButton("应用")
        trigger_apply_btn.clicked.connect(self.apply_trigger_setting)
        trigger_mode_layout.addWidget(trigger_apply_btn)
        trigger_side_layout = QHBoxLayout()
        trigger_side_layout.setContentsMargins(0, 0, 0, 0)
        trigger_side_layout.setSpacing(5)
        trigger_settings_layout.addLayout(trigger_side_layout)
        trigger_side_layout.addWidget(QLabel('CH'))
        self.trigger_channel_box = QLineEdit("1")
        self.trigger_channel_box.setValidator(int_validator)
        trigger_side_layout.addWidget(self.trigger_channel_box)
        self.trigger_edge_box = QComboBox()
        self.trigger_edge_box.addItem('⎇', TriggerSlopeType.Rising)
        self.trigger_edge_box.addItem('⌥', TriggerSlopeType.Falling)
        self.trigger_edge_box.addItem('⎇⌥', TriggerSlopeType.Either)
        self.trigger_edge_box.setCurrentIndex(0)
        trigger_side_layout.addWidget(self.trigger_edge_box)
        self.trigger_level_box = QLineEdit("0V")
        trigger_side_layout.addWidget(self.trigger_level_box)

        # horizontal
        horizon_settings_group, horizon_settings_layout = build_group_box("Horizontal", QGridLayout())
        base_setting_layout.addWidget(horizon_settings_group)
        horizon_settings_layout.addWidget(QLabel('Mode'), 0, 0)
        self.horizon_mode_box = QComboBox()
        self.horizon_mode_box.addItems(['MAIN', 'WINDow', 'XY', 'ROLL'])
        self.horizon_mode_box.setCurrentIndex(0)
        horizon_settings_layout.addWidget(self.horizon_mode_box, 0, 1)
        horizon_apply_btn = QPushButton("应用")
        horizon_apply_btn.clicked.connect(self.apply_horizon_setting)
        horizon_settings_layout.addWidget(horizon_apply_btn, 0, 2)
        horizon_reset_btn = QPushButton("重置")
        horizon_reset_btn.clicked.connect(self.reset_device)
        horizon_settings_layout.addWidget(horizon_reset_btn, 0, 3)
        base_settings_group, base_settings_layout = build_group_box("BaseTime", QGridLayout(), font_size=12)
        horizon_settings_layout.addWidget(base_settings_group, 1, 0, 2, 2)
        base_settings_layout.addWidget(QLabel('Scale'), 0, 0)
        self.horizon_scale_box = QLineEdit("100us")
        base_settings_layout.addWidget(self.horizon_scale_box, 0, 1)
        base_settings_layout.addWidget(QLabel('Delay'), 1, 0)
        self.horizon_delay_box = QLineEdit("0s")
        base_settings_layout.addWidget(self.horizon_delay_box, 1, 1)
        zoom_settings_group, zoom_settings_layout = build_group_box("Zoom", QGridLayout(), font_size=12)
        horizon_settings_layout.addWidget(zoom_settings_group, 1, 2, 2, 2)
        zoom_settings_layout.addWidget(QLabel('Scale'), 2, 2)
        self.horizon_zoom_scale_box = QLineEdit("10us")
        zoom_settings_layout.addWidget(self.horizon_zoom_scale_box, 2, 3)
        zoom_settings_layout.addWidget(QLabel('Position'), 3, 2)
        self.horizon_zoom_pos_box = QLineEdit("0s")
        zoom_settings_layout.addWidget(self.horizon_zoom_pos_box, 3, 3)

        image_frame = QFrame()
        image_frame.setFrameStyle(QFrame.Shape.Box)
        image_frame.setLineWidth(1)
        left_layout.addWidget(image_frame, 1)
        image_layout = QVBoxLayout()
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(10)
        image_frame.setLayout(image_layout)
        self.image_label = ImageLabel(self)
        self.image_label.setPixmap(QPixmap((Path(__file__).parent / "icon.png").as_posix()))
        self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        image_layout.addWidget(self.image_label, 1)
        image_setting_layout = QVBoxLayout()
        image_setting_layout.setContentsMargins(0, 0, 0, 0)
        image_setting_layout.setSpacing(5)
        image_layout.addLayout(image_setting_layout)
        path_setting_layout = QHBoxLayout()
        path_setting_layout.setContentsMargins(10, 0, 10, 0)
        path_setting_layout.setSpacing(5)
        image_setting_layout.addLayout(path_setting_layout)
        path_setting_layout.addWidget(QLabel("保存路径:"))
        self.save_path_box = QLineEdit(text=self.pic_dir.as_posix())
        self.save_path_box.setReadOnly(True)
        path_setting_layout.addWidget(self.save_path_box)
        self.btn_browse = QPushButton("浏览...")
        self.btn_browse.clicked.connect(self.set_save_path)
        path_setting_layout.addWidget(self.btn_browse)
        name_setting_layout = QHBoxLayout()
        name_setting_layout.setContentsMargins(10, 0, 10, 0)
        name_setting_layout.setSpacing(5)
        image_setting_layout.addLayout(name_setting_layout)
        name_setting_layout.addWidget(QLabel("文件名:"))
        self.edit_filename = QLineEdit("screenshot")
        name_setting_layout.addWidget(self.edit_filename)
        btn_setting_layout = QHBoxLayout()
        btn_setting_layout.setContentsMargins(5, 0, 5, 0)
        btn_setting_layout.setSpacing(5)
        image_setting_layout.addLayout(btn_setting_layout)
        img_btn_layout = QGridLayout()
        img_btn_layout.setContentsMargins(5, 0, 5, 0)
        img_btn_layout.setSpacing(0)
        btn_setting_layout.addLayout(img_btn_layout)
        img_btn_layout.addWidget(QLabel("截图颜色:"), 0, 0)
        self.cmb_screenshot_color = QComboBox()
        self.cmb_screenshot_color.addItems(["彩色", "灰度"])
        self.cmb_screenshot_color.setCurrentIndex(0)
        img_btn_layout.addWidget(self.cmb_screenshot_color, 0, 1)
        img_btn_layout.addWidget(QLabel("保存格式:"), 1, 0)
        self.cmb_screenshot_suffix = QComboBox()
        self.cmb_screenshot_suffix.addItems(['PNG', "JPG", "JPEG", "GIF", 'BMP', 'TIFF'])
        self.cmb_screenshot_suffix.setCurrentIndex(0)
        img_btn_layout.addWidget(self.cmb_screenshot_suffix, 1, 1)
        retake_btn = QPushButton("获取屏幕")
        retake_btn.setStyleSheet("""
            QPushButton {
                background-color: #f5f5f5;
                padding: 8px 8px;
                border: 1px solid rgba(0, 123, 255, 0.5);
                border-radius: 4px;
                font-size: 32px;
            }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        retake_btn.clicked.connect(self.get_pic)
        btn_setting_layout.addWidget(retake_btn, 1)
        save_btn = QPushButton("保存")
        save_btn.setStyleSheet("""
            QPushButton {
                padding: 8px 8px;
                border: 1px solid;
                border-radius: 4px;
                font-size: 32px;
            }
            QPushButton:hover { background-color: #1e8449; }
            QPushButton:disabled { background-color: #bdc3c7; }
        """)
        save_btn.clicked.connect(self.save_pic)
        btn_setting_layout.addWidget(save_btn)

        # Device Scan
        device_scan_group, scan_layout = build_group_box("Device Scan", QVBoxLayout())
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.setSpacing(0)
        right_layout.addWidget(device_scan_group)
        self.osc_devices = QComboBox()
        self.osc_devices.setMaximumWidth(300)
        self.osc_devices.setEditable(False)
        self.osc_devices.currentTextChanged.connect(self.choose_devices_list)
        scan_layout.addWidget(self.osc_devices, 1)
        scan_btn_layout = QHBoxLayout()
        scan_btn_layout.setContentsMargins(0, 0, 0, 0)
        scan_btn_layout.setSpacing(0)
        scan_layout.addLayout(scan_btn_layout)
        self.btn_dryrun = QCheckBox("dryrun")
        self.btn_dryrun.setChecked(dry_run)
        self.btn_dryrun.stateChanged.connect(self.switch_dryrun)
        scan_btn_layout.addWidget(self.btn_dryrun)
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.device_sate_change)
        scan_btn_layout.addWidget(self.btn_connect)

        # Measure
        meas_settings_group, meas_settings_layout = build_group_box("Measure", QVBoxLayout())
        right_layout.addWidget(meas_settings_group)
        meas_btn_layout = QHBoxLayout()
        meas_btn_layout.setContentsMargins(0, 0, 0, 0)
        meas_btn_layout.setSpacing(5)
        meas_settings_layout.addLayout(meas_btn_layout, 1)

        self.add_meas_btn = QToolButton(self)
        self.add_meas_btn.setText("Add Meas")
        self.add_meas_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        meas_btn_layout.addWidget(self.add_meas_btn, 1)
        meas_menu = QMenu(self)
        meas_menu_widget = QWidget()
        meas_menu_layout = QVBoxLayout(meas_menu_widget)
        meas_menu_layout.setContentsMargins(5, 5, 5, 5)
        meas_menu_layout.setSpacing(0)
        meas_type_layout = QHBoxLayout()
        meas_type_layout.setContentsMargins(0, 0, 0, 0)
        meas_type_layout.setSpacing(5)
        meas_menu_layout.addLayout(meas_type_layout)
        meas_type_layout.addWidget(QLabel("Type"))
        self.meas_type = QComboBox()
        self.meas_type.addItems(Measure_Dict.keys())
        self.meas_type.setCurrentIndex(0)
        meas_type_layout.addWidget(self.meas_type)
        meas_apply_btn = QPushButton("Add Meas")
        meas_apply_btn.clicked.connect(self.add_meas)
        meas_cancel_btn = QPushButton("Cancel")
        meas_cancel_btn.clicked.connect(meas_menu.hide)
        meas_type_layout.addWidget(meas_apply_btn)
        meas_type_layout.addWidget(meas_cancel_btn)

        meas_source_label_layout = QHBoxLayout()
        meas_source_label_layout.setContentsMargins(0, 0, 0, 0)
        meas_source_label_layout.setSpacing(5)
        meas_menu_layout.addLayout(meas_source_label_layout)
        meas_source_label_layout.addWidget(QLabel("Source1"))
        meas_source_label_layout.addWidget(QLabel("Source2"))
        meas_source_layout = QHBoxLayout()
        meas_source_layout.setContentsMargins(0, 0, 0, 0)
        meas_source_layout.setSpacing(5)
        meas_menu_layout.addLayout(meas_source_layout)
        self.meas_source1_type = QComboBox()
        meas_source_layout.addWidget(self.meas_source1_type)
        self.meas_source1_number = QLineEdit("1")
        self.meas_source1_number.setFixedWidth(30)
        self.meas_source1_number.setValidator(int_validator)
        meas_source_layout.addWidget(self.meas_source1_number)
        self.meas_source2_type = QComboBox()
        self.meas_source2_type.addItem("", 0)
        meas_source_layout.addWidget(self.meas_source2_type)
        self.meas_source2_number = QLineEdit("")
        self.meas_source2_number.setFixedWidth(30)
        self.meas_source2_number.setValidator(int_validator)
        meas_source_layout.addWidget(self.meas_source2_number)
        for list_item in SourceWaveformType:
            self.meas_source1_type.addItem(list_item.name, list_item)
            self.meas_source2_type.addItem(list_item.name, list_item)
        self.meas_source1_type.setCurrentIndex(0)
        self.meas_source2_type.setCurrentIndex(0)

        meas_widget_action = QWidgetAction(meas_menu)
        meas_widget_action.setDefaultWidget(meas_menu_widget)
        meas_menu.addAction(meas_widget_action)
        self.add_meas_btn.setMenu(meas_menu)

        self.th_setting_btn = QToolButton(self)
        self.th_setting_btn.setText("Threshold")
        self.th_setting_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        meas_btn_layout.addWidget(self.th_setting_btn, 1)
        ths_menu = QMenu(self)
        th_menu_widget = QWidget()
        th_menu_layout = QVBoxLayout(th_menu_widget)
        th_menu_layout.setContentsMargins(5, 5, 5, 5)
        th_menu_layout.setSpacing(0)

        th_source_layout = QHBoxLayout()
        th_source_layout.setContentsMargins(0, 0, 0, 0)
        th_source_layout.setSpacing(5)
        th_menu_layout.addLayout(th_source_layout)
        th_source_layout.addWidget(QLabel("Source"))
        self.th_source_type = QComboBox()
        for list_item in SourceWaveformType:
            self.th_source_type.addItem(list_item.name, list_item)
        self.th_source_type.setCurrentIndex(0)
        th_source_layout.addWidget(self.th_source_type)
        self.th_source_number = QLineEdit("1")
        self.th_source_number.setFixedWidth(30)
        self.th_source_number.setValidator(int_validator)
        th_source_layout.addWidget(self.th_source_number)
        th_type_layout = QHBoxLayout()
        th_type_layout.setContentsMargins(0, 0, 0, 0)
        th_type_layout.setSpacing(5)
        th_menu_layout.addLayout(th_type_layout)
        th_type_layout.addWidget(QLabel("Type"))
        self.th_type = QComboBox()
        self.th_type.addItems(['STANdard', 'PERCent', 'ABSolute'])
        self.th_type.setCurrentText('STANdard')
        self.th_type.currentTextChanged.connect(self.change_th_unit)
        th_type_layout.addWidget(self.th_type, 1)

        th_setting_label_layout = QHBoxLayout()
        th_setting_label_layout.setContentsMargins(0, 0, 0, 0)
        th_setting_label_layout.setSpacing(5)
        th_menu_layout.addLayout(th_setting_label_layout)
        th_setting_label_layout.addWidget(QLabel("base-top-top["))
        self.th_unit = QLabel("🔒")
        th_setting_label_layout.addWidget(self.th_unit)
        th_setting_label_layout.addWidget(QLabel("]"))
        th_setting_label_layout.addStretch(1)
        th_apply_btn = QPushButton("Apply")
        th_apply_btn.clicked.connect(self.apply_threshold)
        th_setting_label_layout.addWidget(th_apply_btn)

        th_setting_layout = QHBoxLayout()
        th_setting_layout.setContentsMargins(0, 0, 0, 0)
        th_setting_layout.setSpacing(5)
        th_menu_layout.addLayout(th_setting_layout)
        self.th_base = QLineEdit("10")
        self.th_base.setFixedWidth(30)
        self.th_base.setReadOnly(True)
        th_setting_layout.addWidget(self.th_base)
        th_setting_layout.addWidget(QLabel("-"))
        self.th_mid = QLineEdit("50")
        self.th_mid.setFixedWidth(30)
        self.th_mid.setReadOnly(True)
        th_setting_layout.addWidget(self.th_mid)
        th_setting_layout.addWidget(QLabel("-"))
        self.th_top = QLineEdit("90")
        self.th_top.setFixedWidth(30)
        self.th_top.setReadOnly(True)
        th_setting_layout.addWidget(self.th_top)
        th_setting_layout.addStretch(1)
        th_cancel_btn = QPushButton("Cancel")
        th_cancel_btn.clicked.connect(ths_menu.hide)
        th_setting_layout.addWidget(th_cancel_btn)

        th_widget_action = QWidgetAction(ths_menu)
        th_widget_action.setDefaultWidget(th_menu_widget)
        ths_menu.addAction(th_widget_action)
        self.th_setting_btn.setMenu(ths_menu)

        clear_meas_btn = QPushButton("Clear Meas")
        clear_meas_btn.clicked.connect(self.clear_meas)
        meas_btn_layout.addWidget(clear_meas_btn)

        # Vertical
        ch_settings_group, ch_settings_layout = build_group_box("Vertical", QVBoxLayout())
        ch_settings_layout.setContentsMargins(0, 0, 0, 0)
        ch_settings_layout.setSpacing(0)
        right_layout.addWidget(ch_settings_group)
        self.ch_btn_group = QButtonGroup(self)
        self.ch_btn_group.idClicked.connect(self.setting_channel)

        for i in range(1, 5):
            group, layout = build_group_box(f"CH{i}", QGridLayout(), font_size=12)
            ch_settings_layout.addWidget(group)

            widgets_config = [
                ("label", QLineEdit(str(i)), (0, 0), (0, 1, 1, 2)),
                ("vertical", QLineEdit("5.0V"), (1, 0), (1, 1)),
                ("offset", QLineEdit("0.0V"), (1, 2), (1, 3)),
                ("state", SwitchButton(), (2, 0), (2, 1))
            ]

            for (attr, widget, name_pos, widget_pos) in widgets_config:
                layout.addWidget(QLabel(attr.capitalize()), *name_pos)
                layout.addWidget(widget, *widget_pos)
                setattr(self, f"ch{i}_{attr}", widget)

            modify_name_btn = QPushButton("修改")
            modify_name_btn.clicked.connect(lambda _, ch=i: self.apply_channel_label(ch))
            layout.addWidget(modify_name_btn, 0, 3)

            # 设置CH1状态按钮默认开启
            if i == 1:
                getattr(self, "ch1_state").setState(True)
            state_btn = getattr(self, f"ch{i}_state")
            state_btn.clicked.connect(lambda checked, ch=i: self.toggle_channel_state(ch, checked))

            # 添加应用按钮
            apply_btn = QPushButton("应用")
            self.ch_btn_group.addButton(apply_btn, id=i)
            layout.addWidget(apply_btn, 2, 2, 1, 2)

        ch5_settings_group, ch5_settings_layout = build_group_box("Other", QGridLayout(), font_size=12)
        ch_settings_layout.addWidget(ch5_settings_group)
        container_widget = QWidget()
        ch5_layout = QHBoxLayout()
        ch5_layout.setContentsMargins(0, 0, 0, 0)
        container_widget.setLayout(ch5_layout)
        ch5_settings_layout.addWidget(container_widget, 0, 0, 1, 4)
        self.ch5_type = QComboBox()
        self.ch5_type.setFixedWidth(100)
        for list_item in SourceWaveformType:
            self.ch5_type.addItem(list_item.name, list_item)
        self.ch5_type.setCurrentIndex(0)
        ch5_layout.addWidget(self.ch5_type)
        self.ch5_ch = QLineEdit("1")
        self.ch5_ch.setFixedWidth(30)
        self.ch5_ch.setValidator(int_validator)
        ch5_layout.addWidget(self.ch5_ch)
        ch5_layout.addStretch(1)
        ch5_save_btn = QPushButton("保存波形")
        ch5_save_btn.clicked.connect(self.save_source)
        ch5_layout.addWidget(ch5_save_btn)
        ch5_settings_layout.addWidget(QLabel("Name"), 1, 0)
        self.ch5_label = QLineEdit("5")
        ch5_settings_layout.addWidget(self.ch5_label, 1, 1, 1, 2)
        ch5_name_btn = QPushButton("修改")
        ch5_name_btn.clicked.connect(lambda _, ch=5: self.apply_channel_label(ch))
        ch5_settings_layout.addWidget(ch5_name_btn, 1, 3)
        ch5_settings_layout.addWidget(QLabel("Vertical"), 2, 0)
        self.ch5_vertical = QLineEdit("5.0V")
        ch5_settings_layout.addWidget(self.ch5_vertical, 2, 1)
        ch5_settings_layout.addWidget(QLabel("Offset"), 2, 2)
        self.ch5_offset = QLineEdit("0.0V")
        ch5_settings_layout.addWidget(self.ch5_offset, 2, 3)
        ch5_settings_layout.addWidget(QLabel("State"), 3, 0)
        ch5_state = SwitchButton()
        ch5_state.clicked.connect(lambda checked, ch=5: self.toggle_channel_state(ch, checked))
        ch5_settings_layout.addWidget(ch5_state, 3, 1)
        ch5_apply_btn = QPushButton("应用")
        self.ch_btn_group.addButton(ch5_apply_btn, id=5)
        ch5_settings_layout.addWidget(ch5_apply_btn, 3, 2, 1, 2)

        right_layout.addStretch(1)

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
        self.logger.info(f"当前识别到了{len(sn_list) - 1}个仪器")
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
        self.device = create_osc_agent(osc_info=self.name, address=self.devices_list[self.sn], logger=self.logger)
        self.device.connect(reset=False)
        self.btn_connect.setText("Disconnect")
        self.osc_devices.setEnabled(False)
        self.palette.setColor(self.backgroundRole(), QColor("#B1D85C"))
        self.setPalette(self.palette)
        self.connected = True

    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.osc_devices.setEnabled(True)
            self.palette.setColor(self.backgroundRole(), QColor("#f5f5f5"))
            self.setPalette(self.palette)
            self.device = None
            self.connected = False

    def set_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "选择保存路径")
        if path:
            self.pic_dir = Path(path)
            self.save_path_box.setText(path)

    @auto_connected
    def get_pic(self):
        if self.dryrun and "demo" in self.name:
            with open(Path(__file__).parent / "logo.png", 'rb') as img_file:
                self.img_data = img_file.read()
        else:
            # 获取颜色选项
            color = self.cmb_screenshot_color.currentIndex() == 0  # 0=彩色, 1=灰度
            color_text = "彩色" if color else "灰度"
            suffix = self.cmb_screenshot_suffix.currentText()

            self.logger.info(f"正在截取屏幕 ({color_text})")
            self.img_data = self.device.get_screen_image(image_format=suffix, color=color)

        self.image_label.setPixmapFromData(self.img_data)
        self.img_saved = False
        self.logger.info(f"屏幕获取完成")

    def save_pic(self):
        """保存截图到文件"""
        if not self.img_data:
            return
        edit_filename = self.edit_filename.text()
        if not edit_filename:
            QMessageBox.information(self, "警告", "请输入文件名")
            return
        if self.img_saved and edit_filename == self.lastName:
            reply = QMessageBox.question(self, "确认", "该图片已保存,是否确定需要重新保存?")
            if reply == QMessageBox.StandardButton.No:
                return
        suffix = self.cmb_screenshot_suffix.currentText()

        full_path = self.pic_dir / f"{edit_filename}.{suffix}"

        # 处理文件冲突
        if full_path.exists():
            question = QMessageBox(self)
            question.setWindowTitle("确认")
            question.setText(f"文件已存在:\n{full_path.as_posix()}\n\n请选择操作:")
            question.setIcon(QMessageBox.Icon.Question)
            question.addButton("覆盖原文件", QMessageBox.ButtonRole.YesRole)
            btn_new_file = question.addButton("创建新文件 (自动添加序号)", QMessageBox.ButtonRole.ApplyRole)
            btn_cancel = question.addButton("取消", QMessageBox.ButtonRole.NoRole)

            question.exec()

            # 判断点击的是哪个按钮对象
            clicked_button = question.clickedButton()
            if clicked_button == btn_cancel:
                return
            elif clicked_button == btn_new_file:
                """计算新文件路径"""
                counter = 1
                edit_filename = re.sub(r'-\d+', '', edit_filename)
                new_path_name = f"{edit_filename}-{counter}.{suffix}"
                full_path = self.pic_dir / new_path_name
                while full_path.exists():
                    counter += 1
                    new_path_name = f"{edit_filename}-{counter}.{suffix}"
                    full_path = self.pic_dir / new_path_name

                self.edit_filename.setText(full_path.stem)
        self.logger.info(f"保存截图到: {full_path.as_posix()}")
        try:
            with open(full_path, 'wb') as pic_file:
                pic_file.write(self.img_data)
            show_toast(self, f"截图已保存至:\n{full_path.as_posix()}")
            self.lastName = edit_filename
            self.img_saved = True
        except Exception as e:
            self.logger.error(f"截图保存失败: {e}")
            QMessageBox.information(self, "错误", f"截图保存失败{e}")
            self.img_saved = False

    @auto_connected
    def btn_state_changed(self, button):
        func = button.text()
        if func == "RUN":
            self.device.run_ctl_press_run()
        elif func == "STOP":
            self.device.run_ctl_press_stop()
        elif func == "SINGLE":
            self.device.run_ctl_press_single()

    @auto_connected
    def apply_horizon_setting(self):
        new_mode = self.horizon_mode_box.currentText()
        if new_mode != self.current_horizon_mode:
            self.current_horizon_mode = new_mode
            self.device.horizon_set_mode(new_mode)
        main_scale = self.horizon_scale_box.text()
        main_scale_value = float(re.sub(r'[^-+\d.]+', '', main_scale))
        main_scale_suffix = re.sub(r'[-+\d.]+', '', main_scale)
        self.device.horizon_set_time_base_scale(scale_value=main_scale_value, scale_suffix=main_scale_suffix)
        main_delay = self.horizon_delay_box.text()
        main_delay_value = float(re.sub(r'[^-+\d.]+', '', main_delay))
        main_delay_suffix = re.sub(r'[-+\d.]+', '', main_delay)
        self.device.horizon_set_time_base_delay(delay_value=main_delay_value, delay_suffix=main_delay_suffix)
        if new_mode == "WINDow":
            zoom_scale = self.horizon_zoom_scale_box.text()
            zoom_scale_value = float(re.sub(r'[^-+\d.]+', '', zoom_scale))
            zoom_scale_suffix = re.sub(r'[-+\d.]+', '', zoom_scale)
            self.device.horizon_zoom_set_time_scale(scale_value=zoom_scale_value, scale_suffix=zoom_scale_suffix)
            zoom_pos = self.horizon_zoom_pos_box.text()
            zoom_pos_value = float(re.sub(r'[^-+\d.]+', '', zoom_pos))
            zoom_pos_suffix = re.sub(r'[-+\d.]+', '', zoom_pos)
            self.device.horizon_zoom_set_time_position(pose_value=zoom_pos_value, pose_suffix=zoom_pos_suffix)
        show_toast(self, "应用成功")

    @auto_connected
    def reset_device(self):
        self.device.reset()
        show_toast(self, "设备复位成功")

    @auto_connected
    def apply_trigger_setting(self):
        channel = self.trigger_channel_box.text()
        edge = self.trigger_edge_box.currentData().value
        level = self.trigger_level_box.text()
        self.device.trigger_set_edge_option(
            source_type=SourceTriggerType.CH, source_number=int(channel),
            slope=edge, level=level
        )
        new_mode = self.trigger_mode_box.currentText()
        if new_mode != self.current_trigger_mode:
            self.current_trigger_mode = new_mode
            self.device.trigger_set_mode(new_mode)

        show_toast(self, "应用成功")

    @auto_connected
    def add_meas(self):
        meas_type = self.meas_type.currentText()
        source1_type = self.meas_source1_type.currentData().value
        source1_number = self.meas_source1_number.text()
        source1 = f"{source1_type}{source1_number}"
        source2 = ""
        source2_type = self.meas_source2_type.currentData()
        if source2_type:
            source2_type = source2_type.value
            source2_number = self.meas_source2_number.text()
            source2 = f"{source2_type}{source2_number}"
        self.device.meas_show_measure(measure_type=meas_type, source1=source1, source2=source2)
        show_toast(self, "添加成功")
        self.add_meas_btn.menu().hide()

    def change_th_unit(self):
        th_type = self.th_type.currentText()
        if th_type == "STANdard":
            self.th_unit.setText("🔒")
            self.th_base.setReadOnly(True)
            self.th_mid.setReadOnly(True)
            self.th_top.setReadOnly(True)
            return
        self.th_base.setReadOnly(False)
        self.th_mid.setReadOnly(False)
        self.th_top.setReadOnly(False)
        self.th_unit.setText("%" if th_type == "PERCent" else "V")

    @auto_connected
    def apply_threshold(self):
        th_type = self.th_type.currentText()
        source_type = self.th_source_type.currentData()
        source_number = int(self.th_source_number.text())
        upper_middle_lower = ['90%', '50%', '10%']
        if th_type != "STANdard":
            upper_middle_lower = [self.th_top.text(), self.th_mid.text(), self.th_base.text()]
        self.device.meas_set_thresholds(
            source_type=source_type, source_number=source_number,
            thresholds_mode=th_type, upper_middle_lower=upper_middle_lower
        )
        show_toast(self, "应用成功")
        self.add_meas_btn.menu().hide()

    @auto_connected
    def clear_meas(self):
        self.device.meas_clear_all()
        show_toast(self, f"清空成功")

    @auto_connected
    def apply_channel_label(self, ch_number):
        label = getattr(self, f'ch{ch_number}_label').text()
        if not label:
            return

        source_type = SourceWaveformType.CH
        source_number = ch_number
        if ch_number == 5:
            source_type = self.ch5_type.currentData()
            ch = self.ch5_ch.text()
            if ch:
                source_number = int(ch)

        self.device.source_set_label(label=label, source_type=source_type, source_number=source_number)
        show_toast(self, "修改成功")

    @auto_connected
    def toggle_channel_state(self, ch_number, checked):
        source_type = SourceWaveformType.CH
        source_number = ch_number
        if ch_number == 5:
            source_type = self.ch5_type.currentData()
            ch = self.ch5_ch.text()
            if ch:
                source_number = int(ch)

        status = "ON" if checked else "OFF"
        self.device.source_set_status(source_type=source_type, source_number=source_number, status=status)
        show_toast(self, f"CH{ch_number} {status}")

    @auto_connected
    def setting_channel(self, btn_id):
        source_type = SourceWaveformType.CH
        source_number = int(btn_id)
        if btn_id == 5:
            source_type = self.ch5_type.currentData()
            ch = self.ch5_ch.text()
            if ch:
                source_number = int(ch)
        # -----------------------------------------#
        vertical = getattr(self, f'ch{btn_id}_vertical').text()
        offset = getattr(self, f'ch{btn_id}_offset').text()
        # -----------------------------------------#
        if vertical:
            vertical_value = float(re.sub(r'[^-+\d.]+', '', vertical))
            vertical_suffix = re.sub(r'[-+\d.]+', '', vertical)
            self.device.source_set_vertical(
                source_type=source_type, source_number=source_number,
                vertical_value=vertical_value, vertical_suffix=vertical_suffix
            )
        # -----------------------------------------#
        if offset:
            offset_value = float(re.sub(r'[^-+\d.]+', '', offset))
            offset_suffix = re.sub(r'[-+\d.]+', '', offset)
            self.device.source_set_offset(
                source_type=source_type, source_number=source_number,
                offset_value=offset_value, offset_suffix=offset_suffix
            )

        show_toast(self, "应用成功")

    @auto_connected
    def save_source(self):
        if self.dryrun and "demo" in self.name:
            return
        source_type = self.ch5_type.currentData()
        ch = self.ch5_ch.text()
        ch_number = None
        if ch:
            ch_number = int(ch)
        file_name, _ = QFileDialog.getSaveFileName(self, "选择文件", self.pic_dir.as_posix(), "CSV File (*.csv)")
        if not file_name:
            return
        if not file_name.endswith('.csv'):
            file_name += '.csv'
        save_file = Path(file_name)
        folder = save_file.parent
        name = save_file.name
        self.device.file_save_channel_waveform_to_csv(
            save_dir=folder, source_type=source_type, source_number=ch_number, csv_name=name
        )
        show_toast(self, f"保存成功")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="OSC", version="0.0.1", logger=None, dry_run=True)
    window.show()
    sys.exit(app.exec())
