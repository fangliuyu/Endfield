
import logging
from pathlib import Path

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox

from ..protocol_frame import ProtocolFrame


class I2S_Frame(ProtocolFrame):
    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent, name, spec_path, logger)

        mode_setting_layout = QHBoxLayout()
        mode_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_setting_layout.setContentsMargins(0, 0, 0, 0)
        mode_setting_layout.setSpacing(5)
        self.main_layout.addLayout(mode_setting_layout)
        mode_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Mode</font>"))
        self.spec_mode_box = QComboBox()
        self.spec_mode_box.setEditable(True)
        self.spec_mode_box.addItems(["I2S", "TDM"])
        mode_setting_layout.addWidget(self.spec_mode_box)
        mode_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Direction</font>"))
        self.spec_direction_box = QComboBox()
        self.spec_direction_box.setEditable(True)
        self.spec_direction_box.addItems(["LSB", "RSB"])
        mode_setting_layout.addWidget(self.spec_direction_box)

        dout_setting_layout = QHBoxLayout()
        dout_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        dout_setting_layout.setContentsMargins(0, 0, 0, 0)
        dout_setting_layout.setSpacing(10)
        self.main_layout.addLayout(dout_setting_layout)
        self.dout_en_box = QCheckBox()
        self.dout_en_box.setChecked(True)
        dout_setting_layout.addWidget(self.dout_en_box)
        dout_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>DOUT</font>")
        dout_label.setFixedWidth(60)
        dout_setting_layout.addWidget(dout_label)
        dout_setting_layout.addWidget(QLabel("label"))
        self.dout_label_box = QLineEdit("DOUT")
        dout_setting_layout.addWidget(self.dout_label_box)
        dout_setting_layout.addWidget(QLabel("CH"))
        self.dout_ch_box = QComboBox()
        self.dout_ch_box.setEditable(True)
        self.dout_ch_box.addItems(["1", "2", "3", "4"])
        self.dout_ch_box.setCurrentIndex(0)
        dout_setting_layout.addWidget(self.dout_ch_box)

        din_setting_layout = QHBoxLayout()
        din_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        din_setting_layout.setContentsMargins(0, 0, 0, 0)
        din_setting_layout.setSpacing(10)
        self.main_layout.addLayout(din_setting_layout)
        self.din_en_box = QCheckBox()
        self.din_en_box.setChecked(True)
        din_setting_layout.addWidget(self.din_en_box)
        din_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>DIN</font>")
        din_label.setFixedWidth(60)
        din_setting_layout.addWidget(din_label)
        din_setting_layout.addWidget(QLabel("label"))
        self.din_label_box = QLineEdit("DIN")
        din_setting_layout.addWidget(self.din_label_box)
        din_setting_layout.addWidget(QLabel("CH"))
        self.din_ch_box = QComboBox()
        self.din_ch_box.setEditable(True)
        self.din_ch_box.addItems(["1", "2", "3", "4"])
        self.din_ch_box.setCurrentIndex(1)
        din_setting_layout.addWidget(self.din_ch_box)

        bclk_setting_layout = QHBoxLayout()
        bclk_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        bclk_setting_layout.setContentsMargins(0, 0, 0, 0)
        bclk_setting_layout.setSpacing(10)
        self.main_layout.addLayout(bclk_setting_layout)
        self.bclk_en_box = QCheckBox()
        self.bclk_en_box.setChecked(True)
        self.bclk_en_box.setDisabled(True)
        bclk_setting_layout.addWidget(self.bclk_en_box)
        bclk_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>BCLK</font>")
        bclk_label.setFixedWidth(60)
        bclk_setting_layout.addWidget(bclk_label)
        bclk_setting_layout.addWidget(QLabel("label"))
        self.bclk_label_box = QLineEdit("BCLK")
        bclk_setting_layout.addWidget(self.bclk_label_box)
        bclk_setting_layout.addWidget(QLabel("CH"))
        self.bclk_ch_box = QComboBox()
        self.bclk_ch_box.setEditable(True)
        self.bclk_ch_box.addItems(["1", "2", "3", "4"])
        self.bclk_ch_box.setCurrentIndex(2)
        bclk_setting_layout.addWidget(self.bclk_ch_box)

        lrck_setting_layout = QHBoxLayout()
        lrck_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        lrck_setting_layout.setContentsMargins(0, 0, 0, 0)
        lrck_setting_layout.setSpacing(10)
        self.main_layout.addLayout(lrck_setting_layout)
        self.lrck_en_box = QCheckBox()
        self.lrck_en_box.setChecked(True)
        self.lrck_en_box.setDisabled(True)
        lrck_setting_layout.addWidget(self.lrck_en_box)
        lrck_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>LRCK</font>")
        lrck_label.setFixedWidth(60)
        lrck_setting_layout.addWidget(lrck_label)
        lrck_setting_layout.addWidget(QLabel("label"))
        self.lrck_label_box = QLineEdit("LRCK")
        lrck_setting_layout.addWidget(self.lrck_label_box)
        lrck_setting_layout.addWidget(QLabel("CH"))
        self.lrck_ch_box = QComboBox()
        self.lrck_ch_box.setEditable(True)
        self.lrck_ch_box.addItems(["1", "2", "3", "4"])
        self.lrck_ch_box.setCurrentIndex(3)
        lrck_setting_layout.addWidget(self.lrck_ch_box)

    def load_config(self, config):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

        self.spec_mode_box.setCurrentText(self.config.protocol_configuration.get("Mode", 'I2S'))
        self.spec_direction_box.setCurrentText(self.config.protocol_configuration.get("Direction", 'master'))

        dout_en, dout_ch, dout_label = self.config.channel_list.get("DOUT", (True, 1, "DOUT"))
        self.dout_en_box.setChecked(dout_en)
        self.dout_label_box.setText(dout_label)
        self.din_ch_box.setCurrentText(str(dout_ch))

        din_en, din_ch, din_label = self.config.channel_list.get("DIN", (True, 2, "DIN"))
        self.din_en_box.setChecked(din_en)
        self.din_label_box.setText(din_label)
        self.din_ch_box.setCurrentText(str(din_ch))

        bclk_en, bclk_ch, bclk_label = self.config.channel_list.get("BCLK", (True, 3, "BCLK"))
        self.bclk_en_box.setChecked(bclk_en)
        self.bclk_label_box.setText(bclk_label)
        self.bclk_ch_box.setCurrentText(str(bclk_ch))

        lrck_en, lrck_ch, lrck_label = self.config.channel_list.get("LRCK", (True, 4, "LRCK"))
        self.lrck_en_box.setChecked(lrck_en)
        self.lrck_label_box.setText(lrck_label)
        self.lrck_ch_box.setCurrentText(str(lrck_ch))

    def dump_config(self):
        self.config.protocol = "I2S"
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))

        self.config.channel_list = {
            "DOUT": (self.dout_en_box.isChecked(), int(self.dout_ch_box.currentText()), self.dout_label_box.text()),
            "DIN": (self.din_en_box.isChecked(), int(self.din_ch_box.currentText()), self.din_label_box.text()),
            "BCLK": (self.bclk_en_box.isChecked(), int(self.bclk_ch_box.currentText()), self.bclk_label_box.text()),
            "LRCK": (self.lrck_en_box.isChecked(), int(self.lrck_ch_box.currentText()), self.lrck_label_box.text())
        }

        self.config.trigger_func = ("LRCK", "falling")

        self.config.protocol_configuration = {
            "Mode": self.spec_mode_box.currentText(),
            "Direction": self.spec_direction_box.currentText(),
        }

        return self.config
