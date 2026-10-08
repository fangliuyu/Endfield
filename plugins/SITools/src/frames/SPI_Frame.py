
import logging
from pathlib import Path

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox

from ..protocol_frame import ProtocolFrame


class SPI_Frame(ProtocolFrame):
    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent, name, spec_path, logger)

        mode_setting_layout = QHBoxLayout()
        mode_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_setting_layout.setContentsMargins(0, 0, 0, 0)
        mode_setting_layout.setSpacing(5)
        self.main_layout.addLayout(mode_setting_layout)
        mode_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Clock Mode</font>"))
        self.clk_mode_box = QComboBox()
        self.clk_mode_box.setEditable(True)
        self.clk_mode_box.addItems(["0", "1", "2", "3"])
        mode_setting_layout.addWidget(self.clk_mode_box)

        mosi_setting_layout = QHBoxLayout()
        mosi_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mosi_setting_layout.setContentsMargins(0, 0, 0, 0)
        mosi_setting_layout.setSpacing(10)
        self.main_layout.addLayout(mosi_setting_layout)
        self.mosi_en_box = QCheckBox()
        self.mosi_en_box.setChecked(True)
        mosi_setting_layout.addWidget(self.mosi_en_box)
        mosi_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>MOSI</font>")
        mosi_label.setFixedWidth(60)
        mosi_setting_layout.addWidget(mosi_label)
        mosi_setting_layout.addWidget(QLabel("label"))
        self.mosi_label_box = QLineEdit("MOSI")
        mosi_setting_layout.addWidget(self.mosi_label_box)
        mosi_setting_layout.addWidget(QLabel("CH"))
        self.mosi_ch_box = QComboBox()
        self.mosi_ch_box.setEditable(True)
        self.mosi_ch_box.addItems(["1", "2", "3", "4"])
        self.mosi_ch_box.setCurrentIndex(0)
        mosi_setting_layout.addWidget(self.mosi_ch_box)

        miso_setting_layout = QHBoxLayout()
        miso_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        miso_setting_layout.setContentsMargins(0, 0, 0, 0)
        miso_setting_layout.setSpacing(10)
        self.main_layout.addLayout(miso_setting_layout)
        self.miso_en_box = QCheckBox()
        self.miso_en_box.setChecked(True)
        miso_setting_layout.addWidget(self.miso_en_box)
        miso_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>SCLK</font>")
        miso_label.setFixedWidth(60)
        miso_setting_layout.addWidget(miso_label)
        miso_setting_layout.addWidget(QLabel("label"))
        self.miso_label_box = QLineEdit("MISO")
        miso_setting_layout.addWidget(self.miso_label_box)
        miso_setting_layout.addWidget(QLabel("CH"))
        self.miso_ch_box = QComboBox()
        self.miso_ch_box.setEditable(True)
        self.miso_ch_box.addItems(["1", "2", "3", "4"])
        self.miso_ch_box.setCurrentIndex(1)
        miso_setting_layout.addWidget(self.miso_ch_box)

        sclk_setting_layout = QHBoxLayout()
        sclk_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        sclk_setting_layout.setContentsMargins(0, 0, 0, 0)
        sclk_setting_layout.setSpacing(10)
        self.main_layout.addLayout(sclk_setting_layout)
        self.sclk_en_box = QCheckBox()
        self.sclk_en_box.setChecked(True)
        self.sclk_en_box.setDisabled(True)
        sclk_setting_layout.addWidget(self.sclk_en_box)
        sclk_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>SCLK</font>")
        sclk_label.setFixedWidth(60)
        sclk_setting_layout.addWidget(sclk_label)
        sclk_setting_layout.addWidget(QLabel("label"))
        self.sclk_label_box = QLineEdit("SCLK")
        sclk_setting_layout.addWidget(self.sclk_label_box)
        sclk_setting_layout.addWidget(QLabel("CH"))
        self.sclk_ch_box = QComboBox()
        self.sclk_ch_box.setEditable(True)
        self.sclk_ch_box.addItems(["1", "2", "3", "4"])
        self.sclk_ch_box.setCurrentIndex(2)
        sclk_setting_layout.addWidget(self.sclk_ch_box)

        cs_setting_layout = QHBoxLayout()
        cs_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        cs_setting_layout.setContentsMargins(0, 0, 0, 0)
        cs_setting_layout.setSpacing(10)
        self.main_layout.addLayout(cs_setting_layout)
        self.cs_en_box = QCheckBox()
        self.cs_en_box.setChecked(True)
        self.cs_en_box.setDisabled(True)
        cs_setting_layout.addWidget(self.cs_en_box)
        cs_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>CS</font>")
        cs_label.setFixedWidth(60)
        cs_setting_layout.addWidget(cs_label)
        cs_setting_layout.addWidget(QLabel("label"))
        self.cs_label_box = QLineEdit("CS")
        cs_setting_layout.addWidget(self.cs_label_box)
        cs_setting_layout.addWidget(QLabel("CH"))
        self.cs_ch_box = QComboBox()
        self.cs_ch_box.setEditable(True)
        self.cs_ch_box.addItems(["1", "2", "3", "4"])
        self.cs_ch_box.setCurrentIndex(3)
        cs_setting_layout.addWidget(self.cs_ch_box)

    def load_config(self, config):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

        self.clk_mode_box.setCurrentText(self.config.protocol_configuration.get("Clock Mode", '0'))

        mosi_en, mosi_ch, mosi_label = self.config.channel_list.get("MOSI", (True, 1, "MOSI"))
        self.mosi_en_box.setChecked(mosi_en)
        self.mosi_label_box.setText(mosi_label)
        self.miso_ch_box.setCurrentText(str(mosi_ch))

        miso_en, miso_ch, miso_label = self.config.channel_list.get("MISO", (True, 2, "MISO"))
        self.miso_en_box.setChecked(miso_en)
        self.miso_label_box.setText(miso_label)
        self.miso_ch_box.setCurrentText(str(miso_ch))

        sclk_en, sclk_ch, sclk_label = self.config.channel_list.get("SCLK", (True, 3, "SCLK"))
        self.sclk_en_box.setChecked(sclk_en)
        self.sclk_label_box.setText(sclk_label)
        self.sclk_ch_box.setCurrentText(str(sclk_ch))

        cs_en, cs_ch, cs_label = self.config.channel_list.get("CS", (True, 4, "CS"))
        self.cs_en_box.setChecked(cs_en)
        self.cs_label_box.setText(cs_label)
        self.cs_ch_box.setCurrentText(str(cs_ch))

    def dump_config(self):
        self.config.protocol = "SPI"
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))

        self.config.channel_list = {
            "MOSI": (self.mosi_en_box.isChecked(), int(self.mosi_ch_box.currentText()), self.mosi_label_box.text()),
            "MISO": (self.miso_en_box.isChecked(), int(self.miso_ch_box.currentText()), self.miso_label_box.text()),
            "SCLK": (self.sclk_en_box.isChecked(), int(self.sclk_ch_box.currentText()), self.sclk_label_box.text()),
            "CS": (self.cs_en_box.isChecked(), int(self.cs_ch_box.currentText()), self.cs_label_box.text())
        }

        self.config.trigger_func = ("CS", "falling")

        self.config.protocol_configuration = {
            "Clock Mode": self.clk_mode_box.currentText(),
        }

        return self.config
