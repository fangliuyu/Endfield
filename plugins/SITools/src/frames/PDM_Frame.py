
import logging
from pathlib import Path

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox

from ..protocol_frame import ProtocolFrame


class PDM_Frame(ProtocolFrame):
    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent, name, spec_path, logger)

        mode_setting_layout = QHBoxLayout()
        mode_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_setting_layout.setContentsMargins(0, 0, 0, 0)
        mode_setting_layout.setSpacing(5)
        self.main_layout.addLayout(mode_setting_layout)
        mode_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Data sample</font>"))
        self.data_side_box = QComboBox()
        self.data_side_box.setEditable(True)
        self.data_side_box.addItems(["LR", "L", "R"])
        mode_setting_layout.addWidget(self.data_side_box)

        sda_setting_layout = QHBoxLayout()
        sda_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        sda_setting_layout.setContentsMargins(0, 0, 0, 0)
        sda_setting_layout.setSpacing(10)
        self.main_layout.addLayout(sda_setting_layout)
        self.sda_en_box = QCheckBox()
        self.sda_en_box.setChecked(True)
        self.sda_en_box.setDisabled(True)
        sda_setting_layout.addWidget(self.sda_en_box)
        sda_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>DATA</font>")
        sda_label.setFixedWidth(60)
        sda_setting_layout.addWidget(sda_label)
        sda_setting_layout.addWidget(QLabel("label"))
        self.sda_label_box = QLineEdit("DATA")
        sda_setting_layout.addWidget(self.sda_label_box)
        sda_setting_layout.addWidget(QLabel("CH"))
        self.sda_ch_box = QComboBox()
        self.sda_ch_box.setEditable(True)
        self.sda_ch_box.addItems(["1", "2", "3", "4"])
        self.sda_ch_box.setCurrentIndex(0)
        sda_setting_layout.addWidget(self.sda_ch_box)

        scl_setting_layout = QHBoxLayout()
        scl_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        scl_setting_layout.setContentsMargins(0, 0, 0, 0)
        scl_setting_layout.setSpacing(10)
        self.main_layout.addLayout(scl_setting_layout)
        self.scl_en_box = QCheckBox()
        self.scl_en_box.setChecked(True)
        self.scl_en_box.setDisabled(True)
        scl_setting_layout.addWidget(self.scl_en_box)
        scl_label = QLabel("<font style='font-size: 18px; font-weight: bold;'>CLK</font>")
        scl_label.setFixedWidth(60)
        scl_setting_layout.addWidget(scl_label)
        scl_setting_layout.addWidget(QLabel("label"))
        self.scl_label_box = QLineEdit("CLK")
        scl_setting_layout.addWidget(self.scl_label_box)
        scl_setting_layout.addWidget(QLabel("CH"))
        self.scl_ch_box = QComboBox()
        self.scl_ch_box.setEditable(True)
        self.scl_ch_box.addItems(["1", "2", "3", "4"])
        self.scl_ch_box.setCurrentIndex(1)
        scl_setting_layout.addWidget(self.scl_ch_box)

    def load_config(self, config):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

        self.data_side_box.setCurrentText(self.config.protocol_configuration.get("Data Side", "LR"))

        _, sda_ch, sda_label = self.config.channel_list.get("DATA", (True, 1, "DATA"))
        self.sda_label_box.setText(sda_label)
        self.scl_ch_box.setCurrentText(str(sda_ch))
        _, scl_ch, scl_label = self.config.channel_list.get("CLK", (True, 2, "CLK"))
        self.scl_label_box.setText(scl_label)
        self.scl_ch_box.setCurrentText(str(scl_ch))

    def dump_config(self):
        self.config.protocol = "PDM"
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))

        self.config.channel_list = {
            "DATA": (True, int(self.sda_ch_box.currentText()), self.sda_label_box.text()),
            "CLK": (True, int(self.scl_ch_box.currentText()), self.scl_label_box.text())
        }

        edge = "falling" if self.data_side_box.currentText() == "R" else "rising"
        self.config.trigger_func = ("CLK", edge)

        self.config.protocol_configuration = {
            "Data Side": self.data_side_box.currentText()
        }

        return self.config
