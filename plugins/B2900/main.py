
import logging
import sys
import traceback
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Union, Optional

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel,
                               QFrame, QGridLayout, QComboBox, QSizePolicy, QLineEdit, QMessageBox,
                               QCheckBox, QFileDialog, QSplitter)
from PySide6.QtCore import Qt

from lib.custommath import change_str_value_to_scale
from lib.deviceCheck import auto_connected, check_error
from lib.qtui.custom_widget import CHANNEL_COLORS, LineWidget, SwitchButton, show_toast
from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import get_device_patterns
from lib.instruments.instrument_b2900 import B2900Agent, Instrument_Dryrun


class ChannelWidget(QFrame):
    def __init__(self, index: int, device: B2900Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.device = device
        self.logger = logger
        self.black_color = CHANNEL_COLORS[index]
        self.frequency = None

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

        # self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.setLayout(layout)

        tittle_widget = QWidget()
        tittle_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(tittle_widget)
        tittle_layout = QHBoxLayout(tittle_widget)
        tittle_layout.setContentsMargins(0, 0, 0, 0)
        tittle_layout.setSpacing(5)
        index_label = QLabel(str(self.index))
        index_label.setFixedHeight(35)
        index_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        index_label.setStyleSheet(
            "background-color: %s;border: 1px solid;border-radius: 5px;font-size: 32px;color: black;" % self.black_color
        )
        tittle_layout.addWidget(index_label)
        run_btn = QPushButton("Main View")
        run_btn.clicked.connect(self.set_to_view)
        tittle_layout.addWidget(run_btn)
        tittle_layout.addStretch(1)
        apply_btn = QPushButton("Apply")
        tittle_layout.addWidget(apply_btn)
        switch_btn = SwitchButton()
        switch_btn.clicked.connect(self.output_channel)
        tittle_layout.addWidget(switch_btn)

        base_view_widget = QWidget()
        base_view_widget.setObjectName("background")
        base_view_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        base_view_widget.setStyleSheet("QWidget#background {background-color: %s;}" % CHANNEL_COLORS[0])
        layout.addWidget(base_view_widget, 1)
        base_view_layout = QVBoxLayout(base_view_widget)
        base_view_layout.setContentsMargins(5, 5, 5, 5)
        base_view_layout.setSpacing(0)

        channel_view_layout = QHBoxLayout()
        channel_view_layout.setContentsMargins(5, 5, 5, 5)
        channel_view_layout.setSpacing(5)
        base_view_layout.addLayout(channel_view_layout)

        meas_value_layout = QVBoxLayout()
        meas_value_layout.setContentsMargins(0, 0, 0, 0)
        meas_value_layout.setSpacing(5)
        channel_view_layout.addLayout(meas_value_layout)
        meas_pre_layout = QHBoxLayout()
        meas_pre_layout.setContentsMargins(5, 5, 5, 5)
        meas_pre_layout.setSpacing(5)
        meas_value_layout.addLayout(meas_pre_layout)
        self.meas_pre_value = QLineEdit("---.----")
        self.meas_pre_value.setStyleSheet(
            "background-color: %s;border: None;font-size: 32px;color: white;" % CHANNEL_COLORS[0]
        )
        self.meas_pre_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.meas_pre_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.meas_pre_value.setReadOnly(True)
        meas_pre_layout.addWidget(self.meas_pre_value)
        self.meas_pre_unit = QLabel("V")
        self.meas_pre_unit.setStyleSheet("font-size: 32px;")
        self.meas_pre_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        meas_pre_layout.addWidget(self.meas_pre_unit)
        line = LineWidget(color=QColor(self.black_color), margin=5)
        line.setFixedHeight(5)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        meas_value_layout.addWidget(line)
        meas_next_layout = QHBoxLayout()
        meas_next_layout.setContentsMargins(5, 5, 5, 5)
        meas_next_layout.setSpacing(5)
        meas_value_layout.addLayout(meas_next_layout)
        self.meas_next_value = QLineEdit("---.----")
        self.meas_next_value.setStyleSheet(
            "background-color: %s;border: None;font-size: 32px;color: white;" % CHANNEL_COLORS[0]
        )
        self.meas_next_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.meas_next_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.meas_next_value.setReadOnly(True)
        meas_next_layout.addWidget(self.meas_next_value)
        self.meas_next_unit = QLabel("A")
        self.meas_next_unit.setStyleSheet("font-size: 32px;")
        self.meas_next_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        meas_next_layout.addWidget(self.meas_next_unit)

        source_setting_layout = QVBoxLayout()
        source_setting_layout.setContentsMargins(0, 0, 0, 0)
        source_setting_layout.setSpacing(5)
        channel_view_layout.addLayout(source_setting_layout)

        source_type_layout = QHBoxLayout()
        source_type_layout.setContentsMargins(0, 0, 0, 0)
        source_type_layout.setSpacing(5)
        source_setting_layout.addLayout(source_type_layout)
        source_type_layout.addWidget(QLabel("Source:"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.source_type_box = QComboBox()
        self.source_type_box.setEditable(False)
        self.source_type_box.addItems(['VOLTS', 'AMPS'])
        self.source_type_box.currentTextChanged.connect(self.choose_source_type)
        source_type_layout.addWidget(self.source_type_box, 1)
        source_value_layout = QHBoxLayout()
        source_value_layout.setContentsMargins(0, 0, 0, 0)
        source_value_layout.setSpacing(5)
        source_value_layout.addStretch(1)
        source_setting_layout.addLayout(source_value_layout)
        self.source_value_value = QLineEdit("0.000")
        self.source_value_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.source_value_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        source_value_layout.addWidget(self.source_value_value, 2)
        self.source_unit = QLabel("V")
        self.source_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        source_value_layout.addWidget(self.source_unit)
        source_setting_layout.addWidget(QLabel("Limit(Compliance):"), alignment=Qt.AlignmentFlag.AlignLeft)
        source_limit_layout = QHBoxLayout()
        source_limit_layout.setContentsMargins(0, 0, 0, 0)
        source_limit_layout.setSpacing(5)
        source_setting_layout.addLayout(source_limit_layout)
        source_limit_layout.addStretch(1)
        self.source_limit_value = QLineEdit("0.000")
        self.source_limit_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.source_limit_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        source_limit_layout.addWidget(self.source_limit_value, 2)
        self.source_limit_unit = QLabel("A")
        self.source_limit_unit.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom)
        source_limit_layout.addWidget(self.source_limit_unit)
        apply_btn.clicked.connect(self.apply_setting)

        meas_read_layout = QHBoxLayout()
        meas_read_layout.setContentsMargins(0, 0, 0, 0)
        meas_read_layout.setSpacing(5)
        base_view_layout.addLayout(meas_read_layout)
        meas_read_layout.addWidget(QLabel("Previous"), alignment=Qt.AlignmentFlag.AlignRight)
        self.mes_pre_box = QComboBox()
        self.mes_pre_box.setEditable(False)
        self.mes_pre_box.addItems(['VOLTS', 'AMPS', 'OHMS', 'WATTS'])
        self.mes_pre_box.currentTextChanged.connect(self.choose_meas_pre_type)
        meas_read_layout.addWidget(self.mes_pre_box, 1)
        meas_read_layout.addWidget(QLabel("Next"), alignment=Qt.AlignmentFlag.AlignRight)
        self.mes_next_box = QComboBox()
        self.mes_next_box.setEditable(False)
        self.mes_next_box.addItems(['VOLTS', 'AMPS', 'OHMS', 'WATTS'])
        self.mes_next_box.setCurrentText('AMPS')
        self.mes_next_box.currentTextChanged.connect(self.choose_meas_next_type)
        meas_read_layout.addWidget(self.mes_next_box, 1)
        run_btn = QPushButton("Measure")
        run_btn.clicked.connect(self.get_meas_value)
        meas_read_layout.addWidget(run_btn)

        line = LineWidget(color=QColor(self.black_color), margin=5)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(line)

        meas_setting_widget = QWidget()
        meas_setting_widget.setObjectName("background")
        meas_setting_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        meas_setting_widget.setStyleSheet("QWidget#background {background-color: %s;}" % CHANNEL_COLORS[0])
        layout.addWidget(meas_setting_widget, 1)
        meas_setting_layout = QVBoxLayout(meas_setting_widget)
        meas_setting_layout.setContentsMargins(5, 5, 5, 5)
        meas_setting_layout.setSpacing(0)

        meas_speed_layout = QHBoxLayout()
        meas_speed_layout.setContentsMargins(0, 0, 0, 0)
        meas_speed_layout.setSpacing(5)
        meas_setting_layout.addLayout(meas_speed_layout)
        meas_speed_layout.addWidget(QLabel("Measure Speed:"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.meas_speed_box = QComboBox()
        self.meas_speed_box.setEditable(False)
        self.meas_speed_box.addItems(['AUTO', 'SHORT', 'MEDIUM', 'NORMAL', 'LONG', 'MANUAL'])
        self.meas_speed_box.currentTextChanged.connect(self.choose_speed_mode)
        meas_speed_layout.addWidget(self.meas_speed_box)
        meas_speed_layout.addStretch()
        self.speed_ms_value = QLineEdit("20.00")
        self.speed_ms_value.setDisabled(True)
        self.speed_ms_value.textChanged.connect(self.set_nplc_value)
        self.speed_ms_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.speed_ms_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        meas_speed_layout.addWidget(self.speed_ms_value)
        meas_speed_layout.addWidget(QLabel("ms"))
        meas_speed_layout.addStretch()
        meas_speed_layout.addWidget(QLabel('('))
        self.speed_plc_value = QLineEdit("1.000")
        self.speed_plc_value.setDisabled(True)
        self.speed_plc_value.textChanged.connect(self.set_ms_value)
        self.speed_plc_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.speed_plc_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        meas_speed_layout.addWidget(self.speed_plc_value)
        meas_speed_layout.addWidget(QLabel('PLC)'))
        meas_speed_layout.addStretch()

        range_layout = QGridLayout()
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(5)
        meas_setting_layout.addLayout(range_layout, 1)
        range_layout.addWidget(QLabel("Ranges:"), 0, 0, alignment=Qt.AlignmentFlag.AlignLeft)
        range_layout.addWidget(QLabel("Voltage"), 0, 1, alignment=Qt.AlignmentFlag.AlignRight)
        self.range_vol_box = QComboBox()
        self.range_vol_box.setEditable(False)
        self.range_vol_box.addItems(['AUTO', 'FIXED'])
        range_layout.addWidget(self.range_vol_box, 0, 2)
        self.range_vol_value = QComboBox()
        self.range_vol_value.addItems(["200mV", "2V", "20V", "200V"])
        self.range_vol_value.setCurrentText("20V")
        self.range_vol_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        range_layout.addWidget(self.range_vol_value, 0, 3)

        range_layout.addWidget(QLabel("Amps"), 1, 1, alignment=Qt.AlignmentFlag.AlignRight)
        self.range_cur_box = QComboBox()
        self.range_cur_box.setEditable(False)
        self.range_cur_box.addItems(['AUTO', 'FIXED'])
        range_layout.addWidget(self.range_cur_box, 1, 2)
        self.range_cur_value = QComboBox()
        self.range_cur_value.addItems(
            ["100nA", "1uA", "10uA", "100uA", "1mA", "10mA", "100mA", "1A", "1.5A", "3A", "10A"]
        )
        self.range_cur_value.setCurrentText("10A")
        self.range_cur_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        range_layout.addWidget(self.range_cur_value, 1, 3)

        range_layout.addWidget(QLabel("Ohms"), 2, 1, alignment=Qt.AlignmentFlag.AlignRight)
        self.range_ohm_box = QComboBox()
        self.range_ohm_box.setEditable(False)
        self.range_ohm_box.addItems(['AUTO', 'FIXED', "V/I", "OFF"])
        self.range_ohm_box.setCurrentText("OFF")
        self.range_ohm_box.currentTextChanged.connect(self.choose_ohm_range)
        range_layout.addWidget(self.range_ohm_box, 2, 2)
        range_ohm_layout = QHBoxLayout()
        range_ohm_layout.setContentsMargins(0, 0, 0, 0)
        range_ohm_layout.setSpacing(0)
        range_layout.addLayout(range_ohm_layout, 2, 3)
        self.range_ohm_neg_value = QComboBox()
        self.range_ohm_neg_value.setDisabled(True)
        self.range_ohm_neg_value.addItems(["2Ω", "20Ω", "200Ω", "2KΩ", "20KΩ", "200KΩ", "2MΩ", "20MΩ", "200MΩ"])
        range_ohm_layout.addWidget(self.range_ohm_neg_value, 1)
        range_ohm_layout.addWidget(QLabel("-"))
        self.range_ohm_pos_value = QComboBox()
        self.range_ohm_pos_value.setDisabled(True)
        self.range_ohm_pos_value.addItems(["2Ω", "20Ω", "200Ω", "2KΩ", "20KΩ", "200KΩ", "2MΩ", "20MΩ", "200MΩ"])
        self.range_ohm_pos_value.setCurrentText("200MΩ")
        range_ohm_layout.addWidget(self.range_ohm_pos_value, 1)
        self.range_ohm_neg_value.currentTextChanged.connect(self.check_ohm_limit)
        self.range_ohm_pos_value.currentTextChanged.connect(self.check_ohm_limit)

        meas_apply_btn = QPushButton("Apply Measure Setting")
        meas_apply_btn.clicked.connect(self.apply_meas_setting)
        meas_setting_layout.addWidget(meas_apply_btn)

        line = LineWidget(color=QColor(self.black_color), margin=5)
        line.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout.addWidget(line)

        sweep_setting_widget = QWidget()
        sweep_setting_widget.setObjectName("background")
        sweep_setting_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sweep_setting_widget.setStyleSheet("QWidget#background {background-color: %s;}" % CHANNEL_COLORS[0])
        layout.addWidget(sweep_setting_widget, 1)
        sweep_setting_layout = QVBoxLayout(sweep_setting_widget)
        sweep_setting_layout.setContentsMargins(5, 5, 5, 5)
        sweep_setting_layout.setSpacing(5)

        sweep_state_layout = QHBoxLayout()
        sweep_state_layout.setContentsMargins(0, 0, 0, 0)
        sweep_state_layout.setSpacing(5)
        sweep_setting_layout.addLayout(sweep_state_layout)
        sweep_state_layout.addWidget(QLabel("Sweep:"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.sweep_state_box = QComboBox()
        self.sweep_state_box.setEditable(False)
        self.sweep_state_box.addItems(['OFF', 'LinearSingle', 'LinearDouble', 'LogSingle', 'LogDouble', 'List'])
        self.sweep_state_box.currentTextChanged.connect(self.choose_sweep_mode)
        sweep_state_layout.addWidget(self.sweep_state_box)
        sweep_state_layout.addStretch(1)
        sweep_value_layout = QHBoxLayout()
        sweep_value_layout.setContentsMargins(0, 0, 0, 0)
        sweep_value_layout.setSpacing(5)
        sweep_setting_layout.addLayout(sweep_value_layout)
        sweep_value_layout.addWidget(QLabel('start'))
        self.sweep_start_value = QLineEdit("0.000")
        self.sweep_start_value.setDisabled(True)
        self.sweep_start_value.textChanged.connect(self.set_nplc_value)
        self.sweep_start_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.sweep_start_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sweep_value_layout.addWidget(self.sweep_start_value, 2)
        sweep_value_layout.addWidget(QLabel("V"))
        sweep_value_layout.addStretch(1)
        sweep_value_layout.addWidget(QLabel('stop'))
        self.sweep_stop_value = QLineEdit("0.000")
        self.sweep_stop_value.setDisabled(True)
        self.sweep_stop_value.textChanged.connect(self.set_nplc_value)
        self.sweep_stop_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.sweep_stop_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sweep_value_layout.addWidget(self.sweep_stop_value, 2)
        sweep_value_layout.addWidget(QLabel("V"))
        sweep_value_layout.addStretch(1)
        sweep_value_layout.addWidget(QLabel('points'))
        self.sweep_point_value = QLineEdit("0")
        self.sweep_point_value.setDisabled(True)
        self.sweep_point_value.textChanged.connect(self.set_nplc_value)
        self.sweep_point_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.sweep_point_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sweep_value_layout.addWidget(self.sweep_point_value, 2)
        sweep_value_layout.addStretch(1)
        sweep_value_layout.addWidget(QLabel('step'))
        self.sweep_step_value = QLineEdit("0.000")
        self.sweep_step_value.setDisabled(True)
        self.sweep_step_value.textChanged.connect(self.set_nplc_value)
        self.sweep_step_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.sweep_step_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sweep_value_layout.addWidget(self.sweep_step_value, 2)
        sweep_value_layout.addWidget(QLabel("V"))

        pulse_state_layout = QHBoxLayout()
        pulse_state_layout.setContentsMargins(0, 0, 0, 0)
        pulse_state_layout.setSpacing(5)
        sweep_setting_layout.addLayout(pulse_state_layout)
        pulse_state_layout.addWidget(QLabel("Pulse:"), alignment=Qt.AlignmentFlag.AlignLeft)
        self.pulse_state_box = SwitchButton()
        self.pulse_state_box.clicked.connect(self.switch_pulse_setting)
        pulse_state_layout.addWidget(self.pulse_state_box)
        pulse_state_layout.addStretch(1)
        pulse_value_layout = QHBoxLayout()
        pulse_value_layout.setContentsMargins(0, 0, 0, 0)
        pulse_value_layout.setSpacing(5)
        sweep_setting_layout.addLayout(pulse_value_layout)
        pulse_value_layout.addWidget(QLabel('Peak'))
        self.pulse_peak_value = QLineEdit("0.000")
        self.pulse_peak_value.setDisabled(True)
        self.pulse_peak_value.textChanged.connect(self.set_nplc_value)
        self.pulse_peak_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.pulse_peak_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pulse_value_layout.addWidget(self.pulse_peak_value, 2)
        pulse_value_layout.addWidget(QLabel("V"))
        pulse_value_layout.addStretch(1)
        pulse_value_layout.addWidget(QLabel('Delay'))
        self.pulse_delay_value = QLineEdit("0.000")
        self.pulse_delay_value.setDisabled(True)
        self.pulse_delay_value.textChanged.connect(self.set_nplc_value)
        self.pulse_delay_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.pulse_delay_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pulse_value_layout.addWidget(self.pulse_delay_value, 2)
        pulse_value_layout.addWidget(QLabel("s"))
        pulse_value_layout.addStretch(1)
        pulse_value_layout.addWidget(QLabel('Width'))
        self.pulse_width_value = QLineEdit("0")
        self.pulse_width_value.setDisabled(True)
        self.pulse_width_value.textChanged.connect(self.set_nplc_value)
        self.pulse_width_value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
        self.pulse_width_value.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        pulse_value_layout.addWidget(self.pulse_width_value, 2)
        pulse_value_layout.addWidget(QLabel("s"))

        sweep_apply_layout = QHBoxLayout()
        sweep_apply_layout.setContentsMargins(0, 0, 0, 0)
        sweep_apply_layout.setSpacing(5)
        sweep_setting_layout.addLayout(sweep_apply_layout)
        sweep_apply_btn = QPushButton("Apply Sweep & Pulse Setting")
        sweep_apply_btn.clicked.connect(self.apply_sweep_setting)
        sweep_apply_layout.addWidget(sweep_apply_btn, 1)
        sweep_run_btn = QPushButton("Run Sweep")
        sweep_run_btn.clicked.connect(self.run_sweep)
        sweep_apply_layout.addWidget(sweep_run_btn)

        layout.addStretch(1)

    def update_device(self, device):
        self.device = device

    @check_error
    def apply_setting(self):
        source_type = self.source_type_box.currentText()
        source_value = float(self.source_value_value.text())
        limit_value = float(self.source_limit_value.text())
        if source_type == "VOLTS":
            self.device.set_source_mode(self.index, mode="VOLTage")
            self.device.set_ch_voltage(self.index, voltage=source_value)
            self.device.set_ch_current(self.index, current=limit_value)
        else:
            self.device.set_source_mode(self.index, mode="CURRent")
            self.device.set_ch_current(self.index, current=source_value)
            self.device.set_ch_voltage(self.index, voltage=limit_value)

    @check_error
    def output_channel(self, state: bool):
        self.device.set_ch_output_state(self.index, state=state)

    @check_error
    def set_to_view(self):
        self.device.set_ch_to_view(self.index)

    def choose_source_type(self):
        source_type = self.source_type_box.currentText()
        if source_type == "VOLTS":
            self.source_unit.setText("V")
            self.source_limit_unit.setText("A")
        else:
            self.source_unit.setText("A")
            self.source_limit_unit.setText("V")

    def choose_meas_pre_type(self, meas_type: str):
        if meas_type == "VOLTS":
            self.meas_pre_unit.setText("V")
        elif meas_type == "AMPS":
            self.meas_pre_unit.setText("A")
        elif meas_type == "OHMS":
            self.meas_pre_unit.setText("Ω")
        elif meas_type == "WATTS":
            self.meas_pre_unit.setText("W")

    def choose_meas_next_type(self, meas_type: str):
        if meas_type == "VOLTS":
            self.meas_next_unit.setText("V")
        elif meas_type == "AMPS":
            self.meas_next_unit.setText("A")
        elif meas_type == "OHMS":
            self.meas_next_unit.setText("Ω")
        elif meas_type == "WATTS":
            self.meas_next_unit.setText("W")

    @check_error
    def get_meas_value(self):
        vol_value = self.device.measure_ch_voltage(self.index)
        cur_value = self.device.measure_ch_current(self.index)
        res_value = self.device.measure_ch_resistance(self.index)
        pow_value = vol_value * cur_value
        meas_pre_type = self.mes_pre_box.currentText()
        meas_next_type = self.mes_next_box.currentText()
        pre_value = "---.----"
        next_value = "---.----"
        if meas_pre_type == "VOLTS":
            pre_value = "%7f" % vol_value
        elif meas_pre_type == "AMPS":
            pre_value = "%7f" % cur_value
        elif meas_pre_type == "OHMS":
            pre_value = "%7f" % res_value
        elif meas_pre_type == "WATTS":
            pre_value = "%7f" % pow_value
        if meas_next_type == "VOLTS":
            next_value = "%7f" % vol_value
        elif meas_next_type == "AMPS":
            next_value = "%7f" % cur_value
        elif meas_next_type == "OHMS":
            next_value = "%7f" % res_value
        elif meas_next_type == "WATTS":
            next_value = "%7f" % pow_value
        self.meas_pre_value.setText(pre_value)
        self.meas_next_value.setText(next_value)

    def choose_speed_mode(self):
        mode = self.meas_speed_box.currentText()
        if mode == "MANUAL":
            self.speed_ms_value.setDisabled(False)
            self.speed_plc_value.setDisabled(False)
        else:
            self.speed_ms_value.setDisabled(True)
            self.speed_plc_value.setDisabled(True)

    @check_error
    def set_nplc_value(self, text):
        if not text:
            return
        if not self.frequency:
            self.frequency = float(self.device.send_command(":SYSTem:LFRequency?"))
        self.speed_plc_value.blockSignals(True)
        nplc = self.frequency * float(text) / 1000
        self.speed_plc_value.setText("%.3f" % nplc)
        self.speed_plc_value.blockSignals(False)

    def set_ms_value(self, text):
        if not text:
            return
        if not self.frequency:
            self.frequency = float(self.device.send_command(":SYSTem:LFRequency?"))
        self.speed_ms_value.blockSignals(True)
        ms = float(text) / self.frequency * 1000
        self.speed_ms_value.setText("%.3f" % ms)
        self.speed_ms_value.blockSignals(False)

    def choose_ohm_range(self):
        mode = self.range_ohm_box.currentText()
        self.range_vol_box.setDisabled(False)
        self.range_vol_value.setDisabled(False)
        self.range_cur_box.setDisabled(False)
        self.range_cur_value.setDisabled(False)
        self.range_ohm_neg_value.setDisabled(False)
        self.range_ohm_pos_value.setDisabled(False)
        if mode == "AUTO" or mode == "FIXED":
            self.range_vol_box.setCurrentText("FIXED")
            self.range_cur_box.setCurrentText("FIXED")
            self.range_vol_value.setCurrentText("2V")
            self.range_cur_value.setCurrentText("1A")
            self.range_ohm_pos_value.setCurrentText("200NΩ")
            self.range_vol_box.setDisabled(True)
            self.range_vol_value.setDisabled(True)
            self.range_cur_box.setDisabled(True)
            self.range_cur_value.setDisabled(True)
        if mode != "AUTO":
            self.range_ohm_neg_value.setDisabled(True)
        if mode != "AUTO" and mode != "FIXED":
            self.range_ohm_pos_value.setDisabled(True)
        if mode == "V/I" or mode == "AUTO" or mode == "FIXED":
            self.mes_pre_box.setCurrentText("OHMS")

    def check_ohm_limit(self):
        self.range_ohm_neg_value.blockSignals(True)
        self.range_ohm_pos_value.blockSignals(True)
        neg_limit = self.range_ohm_neg_value.currentText()
        neg_value = change_str_value_to_scale(neg_limit)
        pos_limit = self.range_ohm_pos_value.currentText()
        pos_value = change_str_value_to_scale(pos_limit)
        if neg_value > pos_value:
            self.range_ohm_neg_value.setCurrentText(pos_limit)
            self.range_ohm_pos_value.setCurrentText(neg_limit)
        self.range_ohm_neg_value.blockSignals(False)
        self.range_ohm_pos_value.blockSignals(False)

    @check_error
    def apply_meas_setting(self):
        speed_type = self.meas_speed_box.currentText()
        for func in ["VOLTage", "CURRent", "RESistance"]:
            if speed_type == "AUTO":
                self.device.set_ch_integration_time(self.index, function=func, mode=speed_type)
            elif speed_type == "SHORT":
                self.device.set_ch_integration_time(self.index, function=func, mode='NPLC', nplc="MINimum")
            elif speed_type == "NORMAL" or speed_type == "MEDIUM":
                self.device.set_ch_integration_time(self.index, function=func, mode='NPLC', nplc="DEFault")
            elif speed_type == "LONG":
                self.device.set_ch_integration_time(self.index, function=func, mode='NPLC', nplc="MAXimum")
            elif speed_type == "MANUAL":
                nplc = float(self.speed_plc_value.text())
                self.device.set_ch_integration_time(self.index, function=func, mode='NPLC', nplc=nplc)
        ohm_range_type = self.range_ohm_box.currentText()
        cur_neg_range_str = self.range_ohm_neg_value.currentText()
        cur_neg_range = change_str_value_to_scale(cur_neg_range_str)
        cur_pos_range_str = self.range_ohm_pos_value.currentText()
        cur_pos_range = change_str_value_to_scale(cur_pos_range_str)
        self.device.set_ch_resistance_range(
            self.index, ohm_range_type, range_val=cur_pos_range, low_range_val=cur_neg_range
        )
        if ohm_range_type == "V/I" or ohm_range_type == "OFF":
            vol_range_type = self.range_vol_box.currentText()
            vol_range_str = self.range_vol_value.currentText()
            vol_range = change_str_value_to_scale(vol_range_str)
            self.device.set_ch_voltage_range(self.index, vol_range_type, vol_range)

            cur_range_type = self.range_cur_box.currentText()
            cur_range_str = self.range_cur_value.currentText()
            cur_range = change_str_value_to_scale(cur_range_str)
            self.device.set_ch_current_range(self.index, cur_range_type, cur_range)

    def choose_sweep_mode(self, text: str):
        state = True if text == "OFF" else False
        self.sweep_start_value.setDisabled(state)
        self.sweep_stop_value.setDisabled(state)
        self.sweep_point_value.setDisabled(state or "Linear" in text)
        self.sweep_step_value.setDisabled(state or "Log" in text)

    def switch_pulse_setting(self, state: bool):
        self.pulse_peak_value.setDisabled(not state)
        self.pulse_delay_value.setDisabled(not state)
        self.pulse_width_value.setDisabled(not state)

    @check_error
    def apply_sweep_setting(self):
        sweep_state = self.sweep_state_box.currentText()
        start_value = float(self.sweep_start_value.text())
        stop_value = float(self.sweep_stop_value.text())
        point_value = int(self.sweep_point_value.text())
        step_value = float(self.sweep_step_value.text())
        self.device.set_sweep(
            channel=self.index, mode=sweep_state,
            start=start_value, stop=stop_value, points=point_value, step=step_value,
            double_stair=True if "double" in sweep_state.lower() else False
        )

        pulse_state = self.pulse_state_box.getState()
        peak_value = float(self.pulse_peak_value.text())
        delay_value = float(self.pulse_delay_value.text())
        width_value = float(self.pulse_width_value.text())
        self.device.set_pulse(channel=self.index, mode="ON" if pulse_state else "OFF",
                              peak=peak_value, delay=delay_value, width=width_value)

    @check_error
    def run_sweep(self):
        self.device.initiate_sweep()


class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = '1.0.0', logger: Logger = None, dry_run=False, data_path: Union[PathLike[str], str, None] = None, *args, **kwargs):
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
        self.devices_scan_list = get_device_patterns("B2900")
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: Optional[B2900Agent] = None
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
        self.view_box.addItems(['SINGle1', 'SINGle2', 'DUAL', 'GRAPh', 'ROLL'])
        view_layout.addWidget(self.view_box)
        view_btn = QPushButton("应用")
        view_btn.clicked.connect(self.device_change_view)
        view_layout.addWidget(view_btn)
        save_pic_btn = QPushButton("界面截图")
        save_pic_btn.clicked.connect(self.device_save_pic)
        scan_layout.addWidget(save_pic_btn)

        splitter = QSplitter(Qt.Orientation.Horizontal)
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
            if sn:
                sn_list.append(class_name + ": " + sn)
                self.devices_list[sn] = address
                self.logger.info(f"{index}.{sn}: {class_name}")
        self.logger.info(f"当前识别到了{len(sn_list)}个仪器")
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
            self.device = B2900Agent(instrument_address=self.devices_list[self.sn], logger=self.logger)
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
    def device_change_view(self):
        mode = self.view_box.currentText()
        self.device.set_view_mode(mode)

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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="B2900", version="0.0.1", logger=None, dry_run=True)
    window.show()
    sys.exit(app.exec())
