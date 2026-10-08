
import logging
import sys
import traceback
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Union, List, Optional

from PySide6.QtGui import QIntValidator, QDoubleValidator
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel,
                               QFrame, QGridLayout, QComboBox, QSizePolicy, QLineEdit, QMessageBox,
                               QCheckBox, QButtonGroup, QToolButton, QMenu, QWidgetAction, QFileDialog)
from PySide6.QtCore import Qt

from lib.deviceCheck import check_error
from lib.instruments.modules_check import register_module_config_path, load_multi
from lib.qtui.custom_widget import CHANNEL_COLORS, build_group_box, SwitchButton, show_toast
from lib.customlog import create_logger
from lib.instruments.instrument import get_device_list, check_device_module
from lib.instruments.device_list import load_global_config
from lib.instruments.instrument_n6700 import N6700Agent, Instrument_Dryrun, identifier, ModuleInfo, FUNC_Shape


class PowerWidget(QWidget):
    def __init__(self, index: int, module_info: ModuleInfo, device: N6700Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.module_info = module_info
        self.device = device
        self.logger = logger
        self.pref_enable = True if self.module_info.ModuleType in ["N6761A", "N6762A"] else False

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        self.setLayout(layout)

        vol_group, vol_layout = build_group_box("Voltage", QHBoxLayout())
        layout.addWidget(vol_group)
        vol_layout.addWidget(QLabel("Voltage"))
        self.vol_text = QLineEdit("0.02")
        double_validator = QDoubleValidator(0, self.module_info.VoltageRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.vol_text.setValidator(double_validator)
        vol_layout.addWidget(self.vol_text)
        vol_layout.addWidget(QLabel("V"))
        vol_layout.addStretch()
        vol_layout.addWidget(QLabel("Range"))
        self.vol_range_box = QComboBox()
        if self.module_info.VoltageRange:
            self.vol_range_box.addItems([str(value) for value in self.module_info.VoltageRange])
            self.vol_range_box.setCurrentIndex(len(self.module_info.VoltageRange) - 1)
        self.vol_range_box.setEditable(False)
        vol_layout.addWidget(self.vol_range_box)

        cur_group, cur_layout = build_group_box("Current", QHBoxLayout())
        layout.addWidget(cur_group)
        cur_layout.addWidget(QLabel("Current"))
        self.cur_text = QLineEdit(str(self.module_info.CurrentRating))
        double_validator = QDoubleValidator(0, self.module_info.CurrentRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.cur_text.setValidator(double_validator)
        cur_layout.addWidget(self.cur_text)
        cur_layout.addWidget(QLabel("A"))
        cur_layout.addStretch(1)
        cur_layout.addWidget(QLabel("Range"))
        self.cur_range_box = QComboBox()
        if self.module_info.CurrentRange:
            self.cur_range_box.addItems([str(value) for value in self.module_info.CurrentRange])
            self.cur_range_box.setCurrentIndex(len(self.module_info.VoltageRange) - 1)
        self.cur_range_box.setEditable(False)
        cur_layout.addWidget(self.cur_range_box)

        power_layout = QHBoxLayout()
        power_layout.setContentsMargins(5, 5, 5, 5)
        power_layout.setSpacing(5)
        layout.addLayout(power_layout)
        power_layout.addWidget(QLabel("Power Limit"))
        self.pwr_text = QLineEdit(str(self.module_info.PowerRating))
        double_validator = QDoubleValidator(0, self.module_info.PowerRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.pwr_text.setValidator(double_validator)
        power_layout.addWidget(self.pwr_text)
        power_layout.addWidget(QLabel("W"))
        power_layout.addStretch(1)

        pref_layout = QHBoxLayout()
        pref_layout.setContentsMargins(5, 5, 5, 5)
        pref_layout.setSpacing(5)
        layout.addLayout(pref_layout)
        if self.pref_enable:
            pref_layout.addWidget(QLabel("Turn-on Pref"))
            self.pref_box = QComboBox()
            self.pref_box.addItems(["Voltage", "Current"])
            self.pref_box.setCurrentIndex(0)
            self.pref_box.setEditable(False)
            pref_layout.addWidget(self.pref_box)
            pref_layout.addStretch(1)
            self.pol_box = QCheckBox("Reverse Polarity")
            pref_layout.addWidget(self.pol_box)
        pref_layout.addStretch(1)

        apply_layout = QHBoxLayout()
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(5)
        layout.addLayout(apply_layout)
        arb_setting_btn = QToolButton()
        arb_setting_btn.setText("ARB  ")
        arb_setting_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        apply_layout.addWidget(arb_setting_btn)
        meas_menu = QMenu(self)
        meas_menu_widget = QWidget()
        meas_menu_layout = QVBoxLayout(meas_menu_widget)
        meas_menu_layout.setContentsMargins(5, 5, 5, 5)
        meas_menu_layout.setSpacing(0)
        arb_widget = ArbWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        meas_menu_layout.addWidget(arb_widget)
        meas_widget_action = QWidgetAction(meas_menu)
        meas_widget_action.setDefaultWidget(meas_menu_widget)
        meas_menu.addAction(meas_widget_action)
        arb_setting_btn.setMenu(meas_menu)
        apply_layout.addStretch()
        self.btn_connect = QPushButton("Apply")
        self.btn_connect.clicked.connect(self.apply_channel_setting)
        apply_layout.addWidget(self.btn_connect, 1)
        apply_layout.addStretch()
        run_btn = SwitchButton()
        run_btn.clicked.connect(self.channel_output)
        apply_layout.addWidget(run_btn, 1)

    @check_error
    def apply_channel_setting(self):
        max_voltage = float(self.vol_range_box.currentText())
        voltage = float(self.vol_text.text())
        if voltage > max_voltage:
            QMessageBox.information(self, "错误", f"Voltage max value is {max_voltage}")
            return
        max_current = float(self.cur_range_box.currentText())
        current = float(self.cur_text.text())
        if current > max_current:
            QMessageBox.information(self, "错误", f"Current max value is {max_current}")
            return
        power = float(self.pwr_text.text())
        if power > self.module_info.PowerRating:
            QMessageBox.information(self, "错误", f"Current max value is {self.module_info.PowerRating}")
            return
        self.device.set_ch_voltage_range(self.index, max_voltage)
        self.device.set_ch_voltage(self.index, voltage)
        self.device.set_ch_current_range(self.index, max_current)
        self.device.set_ch_current(self.index, current)
        self.device.set_ch_power_limit(self.index, power)
        if self.pref_enable:
            operating = self.pref_box.currentText()
            self.device.set_ch_operating(self.index, operating)
            polarity_state = self.pol_box.isChecked()
            self.device.set_output_polarity(self.index, polarity_state)

    @check_error
    def channel_output(self, state: bool):
        self.device.set_ch_output_state(self.index, state=state)


class SMUWidget(QWidget):
    def __init__(self, index: int, module_info: ModuleInfo, device: N6700Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.module_info = module_info
        self.device = device
        self.logger = logger

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)

        mode_group, mode_layout = build_group_box("Mode", QVBoxLayout())
        mode_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(mode_group)

        emu_layout = QHBoxLayout()
        emu_layout.setContentsMargins(0, 0, 0, 0)
        emu_layout.setSpacing(5)
        emu_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_layout.addLayout(emu_layout)
        emu_layout.addWidget(QLabel("Emulating"))
        self.emu_box = QComboBox()
        if self.module_info.Emulation:
            self.emu_box.addItems(self.module_info.Emulation)
            self.emu_box.setCurrentIndex(0)
        self.emu_box.setEditable(False)
        self.emu_box.currentTextChanged.connect(self.choose_emulating)
        emu_layout.addWidget(self.emu_box)

        option_layout = QHBoxLayout()
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(5)
        option_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_layout.addLayout(option_layout)
        option_layout.addWidget(QLabel("Operating In"))
        self.opt_box = QComboBox()
        if self.module_info.Operating:
            self.opt_box.addItems(self.module_info.Operating)
            self.opt_box.setCurrentIndex(0)
        self.opt_box.setEditable(False)
        self.opt_box.currentTextChanged.connect(self.choose_operating)
        option_layout.addWidget(self.opt_box)
        option_layout.addWidget(QLabel("Priority"))

        range_layout = QHBoxLayout()
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(5)
        layout.addLayout(range_layout)
        self.value_label = QLabel("Voltage")
        range_layout.addWidget(self.value_label)
        self.value_text = QLineEdit("0.02")
        double_validator = QDoubleValidator(-self.module_info.VoltageRating, self.module_info.VoltageRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.value_text.setValidator(double_validator)
        range_layout.addWidget(self.value_text)
        self.value_unit_label = QLabel("V")
        range_layout.addWidget(self.value_unit_label)
        range_layout.addStretch(1)
        range_layout.addWidget(QLabel("Range"))
        self.value_range_box = QComboBox()
        if self.module_info.VoltageRange:
            self.value_range_box.addItems([str(value) for value in self.module_info.VoltageRange])
            self.value_range_box.setCurrentIndex(1)
        self.value_range_box.setEditable(False)
        range_layout.addWidget(self.value_range_box)

        limit_layout = QHBoxLayout()
        limit_layout.setContentsMargins(0, 0, 0, 0)
        limit_layout.setSpacing(5)
        layout.addLayout(limit_layout)
        self.limit_label = QLabel("Current")
        limit_layout.addWidget(self.limit_label)
        limit_layout.addWidget(QLabel("Limit"))
        self.limit_neg_text = QLineEdit("-0.61200")
        double_validator = QDoubleValidator(-self.module_info.CurrentRating, 0, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.limit_neg_text.setValidator(double_validator)
        self.limit_neg_text.setDisabled(True)
        limit_layout.addWidget(self.limit_neg_text)
        limit_layout.addWidget(QLabel("~"))
        self.limit_pos_text = QLineEdit("3.060")
        double_validator = QDoubleValidator(0, self.module_info.CurrentRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.limit_pos_text.setValidator(double_validator)
        limit_layout.addWidget(self.limit_pos_text)
        self.limit_unit_label = QLabel("A")
        limit_layout.addWidget(self.limit_unit_label)
        limit_layout.addStretch(1)
        self.limit_sw_box = QCheckBox("Tracking Limits")
        self.limit_sw_box.setChecked(True)
        self.limit_sw_box.stateChanged.connect(self.switch_limit)
        limit_layout.addWidget(self.limit_sw_box)

        apply_layout = QHBoxLayout()
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(5)
        layout.addLayout(apply_layout)
        arb_setting_btn = QToolButton()
        arb_setting_btn.setText("ARB  ")
        arb_setting_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        apply_layout.addWidget(arb_setting_btn)
        meas_menu = QMenu(self)
        meas_menu_widget = QWidget()
        meas_menu_layout = QVBoxLayout(meas_menu_widget)
        meas_menu_layout.setContentsMargins(5, 5, 5, 5)
        meas_menu_layout.setSpacing(0)
        arb_widget = ArbWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        meas_menu_layout.addWidget(arb_widget)
        meas_widget_action = QWidgetAction(meas_menu)
        meas_widget_action.setDefaultWidget(meas_menu_widget)
        meas_menu.addAction(meas_widget_action)
        arb_setting_btn.setMenu(meas_menu)
        apply_layout.addStretch()
        self.btn_connect = QPushButton("Apply")
        self.btn_connect.clicked.connect(self.apply_channel_setting)
        apply_layout.addWidget(self.btn_connect, 1)
        apply_layout.addStretch()
        run_btn = SwitchButton()
        run_btn.clicked.connect(self.channel_output)
        apply_layout.addWidget(run_btn, 1)

    def choose_emulating(self):
        emulating = self.emu_box.currentText()
        self.opt_box.setDisabled(False)
        self.value_text.setDisabled(False)
        self.value_range_box.setDisabled(False)
        self.limit_neg_text.setDisabled(False)
        self.limit_pos_text.setDisabled(False)
        self.limit_sw_box.setDisabled(False)
        if emulating in ["BATTery", "CHARger", "CCLoad", "CVLoad", "VMETer", "AMETer"]:
            if emulating == "CCLoad" or emulating == "VMETer":
                self.opt_box.setCurrentText("Current")
            elif emulating == "CVLoad" or emulating == "AMETer":
                self.opt_box.setCurrentText("Voltage")
            if emulating in ["VMETer", "AMETer"]:
                self.limit_sw_box.setChecked(False)
                self.limit_sw_box.setDisabled(True)
                self.value_text.setDisabled(True)
                self.value_range_box.setDisabled(True)
                self.limit_neg_text.setDisabled(True)
                self.limit_pos_text.setDisabled(True)
            if emulating == "CCLoad":
                self.limit_sw_box.setChecked(False)
                self.limit_sw_box.setDisabled(True)
                self.limit_neg_text.setText("-0.01")
                self.limit_neg_text.setDisabled(True)
            if emulating == "CVLoad":
                self.limit_sw_box.setChecked(False)
                self.limit_sw_box.setDisabled(True)
                self.limit_pos_text.setText("0.02")
                self.limit_pos_text.setDisabled(True)
            self.opt_box.setDisabled(True)
        else:
            operating = self.opt_box.currentText()
            self.limit_sw_box.setChecked(True)
            self.limit_neg_text.setDisabled(True)
            if emulating in ["PS4Q", "PS2Q"]:
                if operating == "Voltage":
                    self.limit_neg_text.setText("-3.06")
                else:
                    self.limit_neg_text.setText("-6.12")
            elif emulating in ["PS1Q"]:
                if operating == "Voltage":
                    self.limit_neg_text.setText("-0.612")
                else:
                    self.limit_neg_text.setText("-0.01")

    def choose_operating(self):
        operating = self.opt_box.currentText()
        range_list = []
        if operating == "Voltage":
            self.value_label.setText(operating)
            self.value_unit_label.setText("V")
            range_list = self.module_info.VoltageRange
            self.limit_label.setText("Current")
            double_validator = QDoubleValidator(-self.module_info.CurrentRating, 0, 6)
            double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.limit_neg_text.setValidator(double_validator)
            self.limit_pos_text.setText("3.06")
            double_validator = QDoubleValidator(0, self.module_info.CurrentRating, 6)
            double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.limit_pos_text.setValidator(double_validator)
            self.limit_unit_label.setText("A")
        elif operating == "Current":
            self.value_label.setText(operating)
            self.value_unit_label.setText("A")
            range_list = self.module_info.CurrentRange
            self.limit_label.setText("Voltage")
            double_validator = QDoubleValidator(-self.module_info.VoltageRating, 0, 6)
            double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.limit_neg_text.setValidator(double_validator)
            self.limit_pos_text.setText("6.12")
            double_validator = QDoubleValidator(0, self.module_info.VoltageRating, 6)
            double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
            self.limit_pos_text.setValidator(double_validator)
            self.limit_unit_label.setText("V")
        self.value_range_box.clear()
        if range_list:
            self.value_range_box.addItems([str(value) for value in range_list])
            self.value_range_box.setCurrentIndex(1)

    def switch_limit(self):
        self.limit_neg_text.setDisabled(self.limit_sw_box.isChecked())

    @check_error
    def apply_channel_setting(self):
        emulating = self.emu_box.currentText()
        operating = self.opt_box.currentText()
        range_value = float(self.value_range_box.currentText())
        value = float(self.value_text.text())
        if value < 0 and operating == "Voltage" and emulating != "PS4Q":
            raise ValueError(f"{emulating} {operating} value must be > 0")
        if abs(value) > range_value:
            raise ValueError(f"{operating} value must be < range vale {range_value}")
        neg_limit = float(self.limit_neg_text.text())
        if neg_limit > 0:
            raise ValueError(f"{self.limit_label} Negative value must be < 0")
        pos_limit = float(self.limit_pos_text.text())
        if 0.02 > pos_limit or pos_limit * range_value / 1.02 > self.module_info.PowerRating:
            raise ValueError(f"{self.limit_label} Positive value must be > 0.02 "
                             f"and Power Rating is {self.module_info.PowerRating}")
        self.device.set_ch_emulation(self.index, emulating)
        self.device.set_ch_operating(self.index, operating)
        if operating.lower() == "voltage":
            self.device.set_ch_voltage_range(self.index, range_value)
            self.device.set_ch_voltage(self.index, value)
            self.device.set_ch_voltage_limit(
                self.index, pos_limit,
                None if self.limit_sw_box.isChecked() else neg_limit
            )
        elif operating.lower() == "current":
            self.device.set_ch_current_range(self.index, range_value)
            self.device.set_ch_current(self.index, value)
            self.device.set_ch_current_limit(
                self.index, pos_limit,
                None if self.limit_sw_box.isChecked() else neg_limit
            )

        show_toast(self, "应用成功")

    @check_error
    def channel_output(self, state: bool):
        self.device.set_ch_output_state(self.index, state=state)


class ELoadWidget(QWidget):
    def __init__(self, index: int, module_info: ModuleInfo, device: N6700Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.module_info = module_info
        self.device = device
        self.logger = logger

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)

        option_layout = QHBoxLayout()
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(5)
        option_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(option_layout)
        option_layout.addWidget(QLabel("Operating In"))
        self.opt_box = QComboBox()
        if self.module_info.Operating:
            self.opt_box.addItems(self.module_info.Operating)
            self.opt_box.setCurrentIndex(1)
        self.opt_box.setEditable(False)
        self.opt_box.currentTextChanged.connect(self.choose_operating)
        option_layout.addWidget(self.opt_box)
        option_layout.addWidget(QLabel("Priority"))

        range_layout = QGridLayout()
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(5)
        layout.addLayout(range_layout)
        self.value_label = QLabel("Current")
        range_layout.addWidget(self.value_label, 0, 0, alignment=Qt.AlignmentFlag.AlignRight)
        self.value_text = QLineEdit("0.01")
        double_validator = QDoubleValidator(0, self.module_info.CurrentRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.value_text.setValidator(double_validator)
        range_layout.addWidget(self.value_text, 0, 1)
        self.value_unit_label = QLabel("A")
        range_layout.addWidget(self.value_unit_label, 0, 2, alignment=Qt.AlignmentFlag.AlignLeft)
        range_layout.addWidget(QLabel("Range"), 0, 3, alignment=Qt.AlignmentFlag.AlignRight)
        self.value_range_box = QComboBox()
        if self.module_info.VoltageRange:
            self.value_range_box.addItems([str(value) for value in self.module_info.VoltageRange])
            self.value_range_box.setCurrentIndex(0)
        self.value_range_box.setEditable(False)
        range_layout.addWidget(self.value_range_box, 0, 4)

        range_layout.addWidget(QLabel("Current Limit"), 1, 0, alignment=Qt.AlignmentFlag.AlignRight)
        self.limit_text = QLineEdit("20.4")
        double_validator = QDoubleValidator(0, self.module_info.CurrentRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.limit_text.setValidator(double_validator)
        self.limit_text.setDisabled(True)
        range_layout.addWidget(self.limit_text, 1, 1)
        range_layout.addWidget(QLabel("A"), 1, 2, alignment=Qt.AlignmentFlag.AlignLeft)

        mode_group, mode_layout = build_group_box("Under Voltage Inhibit", QHBoxLayout())
        mode_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(mode_group)
        mode_layout.addWidget(QLabel("Mode"))
        self.mode_box = QComboBox()
        self.mode_box.addItems(["OFF", "LIVE", "LATChing"])
        self.mode_box.setCurrentIndex(0)
        self.mode_box.setEditable(False)
        self.mode_box.currentTextChanged.connect(self.choose_mode)
        mode_layout.addWidget(self.mode_box)
        mode_layout.addStretch()
        mode_layout.addWidget(QLabel("Voltage On"))
        self.trigger_text = QLineEdit("0.01")
        double_validator = QDoubleValidator(0, self.module_info.VoltageRating, 6)
        double_validator.setNotation(QDoubleValidator.Notation.StandardNotation)
        self.trigger_text.setValidator(double_validator)
        self.trigger_text.setDisabled(True)
        mode_layout.addWidget(self.trigger_text)
        mode_layout.addWidget(QLabel("V"))

        apply_layout = QHBoxLayout()
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(5)
        layout.addLayout(apply_layout)
        arb_setting_btn = QToolButton()
        arb_setting_btn.setText("ARB  ")
        arb_setting_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        apply_layout.addWidget(arb_setting_btn)
        meas_menu = QMenu(self)
        meas_menu_widget = QWidget()
        meas_menu_layout = QVBoxLayout(meas_menu_widget)
        meas_menu_layout.setContentsMargins(5, 5, 5, 5)
        meas_menu_layout.setSpacing(0)
        arb_widget = ArbWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        meas_menu_layout.addWidget(arb_widget)
        meas_widget_action = QWidgetAction(meas_menu)
        meas_widget_action.setDefaultWidget(meas_menu_widget)
        meas_menu.addAction(meas_widget_action)
        arb_setting_btn.setMenu(meas_menu)
        apply_layout.addStretch()
        self.short_sw_box = QCheckBox("Enable short")
        apply_layout.addWidget(self.short_sw_box)
        apply_layout.addStretch()
        self.btn_connect = QPushButton("Apply")
        self.btn_connect.clicked.connect(self.apply_channel_setting)
        apply_layout.addWidget(self.btn_connect, 1)
        apply_layout.addStretch()
        run_btn = SwitchButton()
        run_btn.clicked.connect(self.channel_output)
        apply_layout.addWidget(run_btn, 1)

    def choose_mode(self):
        mode = self.mode_box.currentText()
        self.trigger_text.setDisabled(True if mode == "Off" else False)

    def choose_operating(self):
        operating = self.opt_box.currentText()
        range_list = []
        self.value_label.setText(operating)
        if operating == "Voltage":
            self.value_unit_label.setText("V")
            range_list = self.module_info.VoltageRange
            self.mode_box.setCurrentText("OFF")
            self.mode_box.setDisabled(True)
            self.limit_text.setDisabled(False)
        elif operating == "Current":
            self.value_unit_label.setText("A")
            range_list = self.module_info.CurrentRange
            self.mode_box.setDisabled(False)
            self.limit_text.setDisabled(True)
        elif operating == "Power":
            self.value_unit_label.setText("W")
            range_list = self.module_info.PowerRange
            self.mode_box.setDisabled(False)
            self.limit_text.setDisabled(True)
        elif operating == "Resistance":
            self.value_unit_label.setText("Ω")
            range_list = self.module_info.ResistanceRange
            self.mode_box.setDisabled(False)
            self.limit_text.setDisabled(True)
        self.value_range_box.clear()
        if range_list:
            self.value_range_box.addItems([str(value) for value in range_list])
            self.value_range_box.setCurrentIndex(0)

    @check_error
    def apply_channel_setting(self):
        operating = self.opt_box.currentText()
        range_value = float(self.value_range_box.currentText())
        value = float(self.value_text.text())
        mode = self.mode_box.currentText()
        if abs(value) > range_value:
            raise ValueError(f"{operating} value must be < range vale {range_value}")
        limit = float(self.limit_text.text())
        if limit > -0.02:
            raise ValueError(f"limit value must be > -0.02")
        self.device.set_ch_operating(self.index, operating)
        self.device.set_output_inhibit(self.index, mode)
        if mode != "OFF":
            trigger_value = float(self.trigger_text.text())
            self.device.set_ch_voltage(self.index, trigger_value)
            self.device.set_ch_voltage_limit(self.index, trigger_value, None)
        if operating == "Voltage":
            self.device.set_ch_voltage_range(self.index, range_value)
            self.device.set_ch_voltage(self.index, value)
            self.device.set_ch_current_limit(self.index, limit, None)
        elif operating == "Current":
            self.device.set_ch_current_range(self.index, range_value)
            self.device.set_ch_current(self.index, value)
        elif operating == "Power":
            self.device.set_ch_power_limit(self.index, range_value)
            self.device.set_ch_power(self.index, value)
        elif operating == "Resistance":
            self.device.set_ch_resistance_range(self.index, range_value)
            self.device.set_ch_resistance(self.index, value)
        self.device.set_output_short(self.index, self.short_sw_box.isChecked())

    @check_error
    def channel_output(self, state: bool):
        self.device.set_ch_output_state(self.index, state=state)


class ArbWidget(QWidget):
    def __init__(self, index: int, module_info: ModuleInfo, device: N6700Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.module_info = module_info
        self.device = device
        self.logger = logger

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)
        self.setLayout(layout)

        arb_type_layout = QHBoxLayout()
        arb_type_layout.setContentsMargins(0, 0, 0, 0)
        arb_type_layout.setSpacing(5)
        arb_type_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addLayout(arb_type_layout)
        arb_type_layout.addWidget(QLabel("Arb Type:"))
        self.arb_type_box = QComboBox()
        arb_type = ["Voltage", "Current"]
        if identifier.is_module_supported(self.module_info.ModuleType, identifier.ELoad):
            arb_type += ["Resistance", "Power"]
        self.arb_type_box.addItems(arb_type)
        self.arb_type_box.setCurrentIndex(0)
        self.arb_type_box.setEditable(False)
        self.arb_type_box.currentIndexChanged.connect(self.choose_type)
        arb_type_layout.addWidget(self.arb_type_box)
        arb_type_layout.addStretch(1)
        arb_type_layout.addWidget(QLabel("Output Type:"))
        self.output_type_box = QComboBox()
        self.output_type_box.addItems(FUNC_Shape)
        self.output_type_box.setCurrentIndex(0)
        self.output_type_box.setEditable(False)
        self.output_type_box.currentIndexChanged.connect(self.choose_type)
        arb_type_layout.addWidget(self.output_type_box)
        arb_type_layout.addStretch(1)

        property_group, self.property_layout = build_group_box("Properties", QGridLayout())
        property_group.setFixedHeight(80)
        layout.addWidget(property_group)

        self.units = {"Voltage": "V", "Current": "A", "Resistance": "Ω", "Power": "W"}
        self.names = {"Voltage": "V", "Current": "I", "Resistance": "R", "Power": "P"}
        self.properties = {}
        self.properties_layout = {}
        self.build_widget("None")

        after_group, after_layout = build_group_box("Current After Arb", QHBoxLayout())
        after_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(after_group)
        self.after_btn_group = QButtonGroup(self)
        dc_btn = QCheckBox("Return to DC Value")
        dc_btn.setChecked(True)
        self.after_btn_group.addButton(dc_btn, id=0)
        after_layout.addWidget(dc_btn)
        after_layout.addStretch()
        arb_btn = QCheckBox("Last Arb Value")
        self.after_btn_group.addButton(arb_btn, id=1)
        after_layout.addWidget(arb_btn)

        repeat_layout = QHBoxLayout()
        repeat_layout.setContentsMargins(0, 0, 0, 0)
        repeat_layout.setSpacing(5)
        layout.addLayout(repeat_layout)
        self.continue_sw_box = QCheckBox("Continuous")
        self.continue_sw_box.stateChanged.connect(self.switch_continue)
        repeat_layout.addWidget(self.continue_sw_box)
        repeat_layout.addStretch(1)
        repeat_layout.addWidget(QLabel("Repeat Count"))
        self.count_text = QLineEdit("1")
        self.count_text.setValidator(QIntValidator(1, 255))
        repeat_layout.addWidget(self.count_text, 1)

        apply_layout = QHBoxLayout()
        apply_layout.setContentsMargins(0, 0, 0, 0)
        apply_layout.setSpacing(5)
        layout.addLayout(apply_layout)
        apply_btn = QPushButton("Apply")
        apply_btn.clicked.connect(self.apply_channel_setting)
        apply_layout.addWidget(apply_btn, 2)
        apply_layout.addStretch()
        run_btn = QPushButton("ArbRun")
        run_btn.clicked.connect(self.run_arb)
        apply_layout.addWidget(run_btn)

    def choose_type(self):
        output_type = self.output_type_box.currentText()
        self.build_widget(output_type)

    def build_widget(self, output_type: str):
        for name, layout in self.properties_layout.items():
            for widget in self.properties[name]:  # type: QWidget
                widget.deleteLater()
                layout.removeWidget(widget)

            self.property_layout.removeItem(layout)
        self.properties_layout.clear()
        self.properties.clear()
        if output_type == "NONE":
            return
        widgets_config = []
        name_label = self.arb_type_box.currentText()
        name_str = self.names[name_label]
        unit_str = self.units[name_label]
        if output_type == "STEP":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("t0", "0", "s", (1, 0)),
                ("t1", "0", "s", (1, 1)),
            ]
        elif output_type == "RAMP":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("t0", "0", "s", (1, 0)),
                ("t1", "0", "s", (1, 1)),
                ("t2", "0", "s", (1, 2)),
            ]
        elif output_type == "STAircase":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("step", "0", "", (0, 2)),
                ("t0", "0", "s", (1, 0)),
                ("t1", "0", "s", (1, 1)),
                ("t2", "0", "s", (1, 2)),
            ]
        elif output_type == "SINusoid":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("freq", "0", "Hz", (1, 0)),
            ]
        elif output_type == "PULSe":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("t0", "0", "s", (1, 0)),
                ("t1", "0", "s", (1, 1)),
                ("t2", "0", "s", (1, 2)),
            ]
        elif output_type == "TRAPezoid":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("t0", "0", "s", (0, 2)),
                ("t1", "0", "s", (1, 0)),
                ("t2", "0", "s", (1, 1)),
                ("t3", "0", "s", (1, 2)),
                ("t4", "0", "s", (1, 3)),
            ]
        elif output_type == "EXPonential":
            widgets_config = [
                (f"{name_str}0", "0", unit_str, (0, 0)),
                (f"{name_str}1", "0", unit_str, (0, 1)),
                ("t0", "0", "s", (1, 0)),
                ("t1", "0", "s", (1, 1)),
                ("tc", "0", "s", (1, 2)),
            ]

        for (name, value, unit, widget_pos) in widgets_config:
            value_layout = QHBoxLayout()
            value_layout.setContentsMargins(0, 0, 0, 0)
            value_layout.setSpacing(5)
            self.property_layout.addLayout(value_layout, *widget_pos)
            self.properties_layout[name] = value_layout
            name_widget = QLabel(name, alignment=Qt.AlignmentFlag.AlignRight)
            name_widget.setMinimumWidth(30)
            value_layout.addWidget(name_widget)
            value_widget = QLineEdit(value)
            value_layout.addWidget(value_widget)
            unit_widget = QLabel(unit, alignment=Qt.AlignmentFlag.AlignLeft)
            unit_widget.setMinimumWidth(20)
            value_layout.addWidget(unit_widget)
            self.properties[name] = [name_widget, value_widget, unit_widget]

    @check_error
    def apply_channel_setting(self):
        arb_type = self.output_type_box.currentText()
        out_type = self.arb_type_box.currentText()
        name_str = self.names[out_type]

        after = 'Arb' if self.after_btn_group.checkedId() else 'DC'
        repeat = "continuous" if self.continue_sw_box.isChecked() else int(self.count_text.text())

        self.device.set_arb_type(self.index, out_type)
        if arb_type == "STEP":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            self.device.set_arb_step_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()),
            )
        elif arb_type == "RAMP":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            _, t2_text, _ = self.properties[f"t2"]  # type: QLineEdit
            self.device.set_arb_ramp_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()), t2=float(t2_text.text()),
                after_sate=after, repeat=repeat
            )
        elif arb_type == "STAircase":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, step_text, _ = self.properties[f"step"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            _, t2_text, _ = self.properties[f"t2"]  # type: QLineEdit
            self.device.set_arb_stair_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()), step=int(step_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()), t2=float(t2_text.text()),
                after_sate=after, repeat=repeat
            )
        elif arb_type == "SINusoid":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, freq_text, _ = self.properties[f"freq"]  # type: QLineEdit
            self.device.set_arb_sine_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()), freq=float(freq_text.text()),
                after_sate=after, repeat=repeat
            )
        elif arb_type == "PULSe":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            _, t2_text, _ = self.properties[f"t2"]  # type: QLineEdit
            self.device.set_arb_pulse_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()), t2=float(t2_text.text()),
                after_sate=after, repeat=repeat
            )
        elif arb_type == "TRAPezoid":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            _, t2_text, _ = self.properties[f"t2"]  # type: QLineEdit
            _, t3_text, _ = self.properties[f"t3"]  # type: QLineEdit
            _, t4_text, _ = self.properties[f"t4"]  # type: QLineEdit
            self.device.set_arb_trap_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()), t2=float(t2_text.text()),
                t3=float(t3_text.text()), t4=float(t4_text.text()),
                after_sate=after, repeat=repeat
            )
        elif arb_type == "EXPonential":
            _, v0_text, _ = self.properties[f"{name_str}0"]  # type: QLineEdit
            _, v1_text, _ = self.properties[f"{name_str}1"]  # type: QLineEdit
            _, t0_text, _ = self.properties[f"t0"]  # type: QLineEdit
            _, t1_text, _ = self.properties[f"t1"]  # type: QLineEdit
            _, tc_text, _ = self.properties[f"tc"]  # type: QLineEdit
            self.device.set_arb_expon_options(
                self.index,
                v0=float(v0_text.text()), v1=float(v1_text.text()),
                t0=float(t0_text.text()), t1=float(t1_text.text()), tc=float(tc_text.text()),
                after_sate=after, repeat=repeat
            )

    def switch_continue(self):
        self.count_text.setDisabled(self.continue_sw_box.isChecked())

    @check_error
    def run_arb(self):
        self.device.press_arb_run()


class NoModuleUI(QFrame):
    def __init__(self, index: int):
        super().__init__()
        self.index = index
        self.black_color = CHANNEL_COLORS[index]

        self.setObjectName("ModuleUI")
        self.setStyleSheet("""
            QFrame#ModuleUI {
                background-color: %s;
                padding: 2px 4px;
                border: 1px solid %s;
                border-radius: 5px;
            }
        """ % (self.black_color, self.black_color))

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        tittle_layout = QHBoxLayout()
        tittle_layout.setContentsMargins(0, 0, 0, 0)
        tittle_layout.setSpacing(5)
        tittle_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addLayout(tittle_layout)
        index_label = QLabel(str(self.index), alignment=Qt.AlignmentFlag.AlignVCenter)
        index_label.setFixedHeight(35)
        index_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        index_label.setStyleSheet(
            "background-color: %s;border: 1px solid;border-radius: 5px;font-size: 32px;" % self.black_color
        )
        tittle_layout.addWidget(index_label)
        tittle_layout.addStretch(1)

        info_label = QLabel("No Module", alignment=Qt.AlignmentFlag.AlignCenter)
        info_label.setStyleSheet("font-size: 42px;")
        layout.addWidget(info_label, 1)


class ModuleUI(QFrame):
    def __init__(self, index: int, module_info: ModuleInfo, device: N6700Agent, logger: logging.Logger):
        super().__init__()
        self.index = index
        self.module_info = module_info
        self.device = device
        self.logger = logger
        self.black_color = CHANNEL_COLORS[index]

        self.setObjectName("ModuleUI")
        self.setStyleSheet("""
            QFrame#ModuleUI {
                background-color: %s;
                padding: 2px 4px;
                border: 1px solid %s;
                border-radius: 5px;
            }
        """ % (self.black_color, self.black_color))

        self.setMinimumWidth(100)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        tittle_layout = QHBoxLayout()
        tittle_layout.setContentsMargins(0, 0, 0, 0)
        tittle_layout.setSpacing(5)
        tittle_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        layout.addLayout(tittle_layout)
        index_label = QLabel(str(self.index), alignment=Qt.AlignmentFlag.AlignVCenter)
        index_label.setFixedHeight(35)
        index_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        index_label.setStyleSheet(
            "background-color: %s;border: 1px solid;border-radius: 5px;font-size: 32px;" % self.black_color
        )
        tittle_layout.addWidget(index_label)
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(0)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        tittle_layout.addLayout(info_layout, 1)
        info_layout.addWidget(QLabel(self.module_info.ModuleType))
        info_layout.addWidget(QLabel(self.module_info.Description))

        if identifier.is_module_supported(self.module_info.ModuleType, identifier.SMU):
            setting_widget = SMUWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        elif identifier.is_module_supported(self.module_info.ModuleType, identifier.ELoad):
            setting_widget = ELoadWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        else:
            setting_widget = PowerWidget(index=index, module_info=module_info, device=self.device, logger=self.logger)
        layout.addWidget(setting_widget, 1)


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
        self.pic_dir = self.data_path / "pictures"
        if not self.pic_dir.exists():
            self.pic_dir.mkdir()
        cfg = load_global_config()
        self.devices_scan_list = cfg["N6700"]
        register_module_config_path(self.data_path)
        module_cfg = load_multi()
        identifier.update_config({
            "Patterns": module_cfg["n6700_patterns"],
            "Modules": module_cfg["n6700_modules"],
        })
        self.devices_list = {}
        self.name = ""
        self.sn = ""
        self.device: N6700Agent = None  # NOQA
        self.connected = False

        self.setWindowTitle(f"N67xx系列直流电源分析仪控制器V{version}")
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
        save_pic_btn = QPushButton("界面截图")
        save_pic_btn.clicked.connect(self.device_save_pic)
        scan_layout.addWidget(save_pic_btn)
        arb_run_btn = QPushButton("ARB run")
        arb_run_btn.clicked.connect(self.device_run_arb)
        scan_layout.addWidget(arb_run_btn)

        module_frame = QFrame()
        module_frame.setMinimumWidth(400)
        module_frame.setFrameStyle(QFrame.Shape.Box)
        module_frame.setLineWidth(1)
        main_layout.addWidget(module_frame, 1)
        self.module_layout = QGridLayout()
        self.module_layout.setContentsMargins(5, 5, 5, 5)
        self.module_layout.setSpacing(10)
        self.module_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        module_frame.setLayout(self.module_layout)

        self.widgets: List[Optional[QWidget]] = [None, None, None, None]
        for i in range(1, 5):
            self.add_widget(index=i)

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
            self.device = N6700Agent(instrument_address=self.devices_list[self.sn], logger=self.logger)
        self.device.connect(reset=False)
        self.btn_connect.setText("Disconnect")
        self.devices_box.setEnabled(False)
        self.connected = True
        modules = self.device.get_all_module_info()
        for i in range(1, 5):
            self.remove_widget(i)
            if i not in modules.keys():
                self.add_widget(i)
            else:
                self.add_widget(i, module_info=modules[i])

    def disconnect_device(self):
        if self.device and self.connected:
            self.device.disconnect()
            self.btn_connect.setText("Connect")
            self.devices_box.setEnabled(True)
            self.device = None
            self.connected = False
        for i in range(1, 5):
            self.remove_widget(i)
            self.add_widget(i)

    @check_error
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
            QMessageBox.information(self, "信息", f"截图已保存至:\n{file_name}")
        except Exception as e:
            self.logger.error(traceback.format_exc())
            QMessageBox.information(self, "错误", f"截图保存失败{e}")

    @check_error
    def device_run_arb(self):
        self.device.press_arb_run()

    def add_widget(self, index: int, module_info: ModuleInfo = None):
        if not module_info:
            widget = NoModuleUI(index=index)
        else:
            widget = ModuleUI(index=index, module_info=module_info, device=self.device, logger=self.logger)
        widget_index = index - 1
        row = widget_index // 2
        col = widget_index % 2

        self.module_layout.addWidget(widget, row, col)
        self.module_layout.setRowStretch(row, 1)
        self.module_layout.setColumnStretch(col, 1)
        self.widgets[widget_index] = widget

        self.logger.info(f"Module{index}: {'No Module' if not module_info else module_info.Description} UI 添加成功")

    def remove_widget(self, index: int):
        widget_index = index - 1
        widget = self.widgets[widget_index]
        self.module_layout.removeWidget(widget)
        widget.setHidden(True)
        widget.deleteLater()
        self.widgets[widget_index] = None


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="N6700", version="0.0.1", logger=None, dry_run=True)
    window.show()
    sys.exit(app.exec())
