
import logging
from pathlib import Path

from PySide6.QtGui import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QComboBox, QCheckBox

from ..protocol_frame import ProtocolFrame


class OneWire_Frame(ProtocolFrame):
    def __init__(self, parent, name: str, spec_path: Path, logger: logging.Logger):
        super().__init__(parent, name, spec_path, logger)

        mode_setting_layout = QHBoxLayout()
        mode_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        mode_setting_layout.setContentsMargins(0, 0, 0, 0)
        mode_setting_layout.setSpacing(5)
        self.main_layout.addLayout(mode_setting_layout)
        mode_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>Additional</font>"))
        self.freq_en_box = QCheckBox("Frequency")
        self.freq_en_box.setChecked(False)
        mode_setting_layout.addWidget(self.freq_en_box)
        self.width_en_box = QCheckBox("Width")
        self.width_en_box.setChecked(False)
        mode_setting_layout.addWidget(self.width_en_box)
        self.duty_en_box = QCheckBox("Duty")
        self.duty_en_box.setChecked(False)
        mode_setting_layout.addWidget(self.duty_en_box)

        wire_setting_layout = QHBoxLayout()
        wire_setting_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        wire_setting_layout.setContentsMargins(0, 0, 0, 0)
        wire_setting_layout.setSpacing(10)
        self.main_layout.addLayout(wire_setting_layout)
        wire_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>label</font>"))
        self.wire_label_box = QLineEdit("DOUT")
        wire_setting_layout.addWidget(self.wire_label_box)
        wire_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>CH</font>"))
        self.wire_ch_box = QComboBox()
        self.wire_ch_box.setEditable(True)
        self.wire_ch_box.addItems(["1", "2", "3", "4"])
        self.wire_ch_box.setCurrentIndex(0)
        wire_setting_layout.addWidget(self.wire_ch_box)
        wire_setting_layout.addWidget(QLabel("<font style='font-weight: bold;'>edge</font>"))
        self.wire_trigger_box = QComboBox()
        self.wire_trigger_box.setEditable(False)
        self.wire_trigger_box.addItems(["rising", "falling"])
        self.wire_trigger_box.setCurrentIndex(0)
        wire_setting_layout.addWidget(self.wire_trigger_box)

    def load_config(self, config):
        self.config = config
        self.spec_file_box.setCurrentText(self.config.spec_file)
        self.spec_vol_box.setCurrentText(str(self.config.base_voltage))
        threshold_lower, threshold_upper = self.config.thresholds
        self.threshold_lower.setText(str(threshold_lower))
        self.threshold_upper.setText(str(threshold_upper))

        self.freq_en_box.setChecked(self.config.protocol_configuration.get("Frequency", False))
        self.width_en_box.setChecked(self.config.protocol_configuration.get("Width", False))
        self.duty_en_box.setChecked(self.config.protocol_configuration.get("Duty", False))

        _, dout_ch, wire_label = self.config.channel_list.get("OneWire", (True, 1, "OneWire"))
        _, trigger_edge = self.config.trigger_func
        self.wire_label_box.setText(wire_label)
        self.wire_ch_box.setCurrentText(str(dout_ch))
        self.wire_trigger_box.setCurrentText(trigger_edge)

    def dump_config(self):
        self.config.protocol = "OneWire"
        self.config.spec_file = self.spec_file_box.currentText()
        self.config.base_voltage = self.spec_vol_box.currentText()
        threshold_lower, threshold_upper = self.threshold_lower.text(), self.threshold_upper.text()
        self.config.thresholds = (float(threshold_lower), float(threshold_upper))

        self.config.channel_list = {
            "OneWire": (True, int(self.wire_ch_box.currentText()), self.wire_label_box.text())
        }

        self.config.trigger_func = ("OneWire", self.wire_trigger_box.currentText())

        self.config.protocol_configuration = {
            "Frequency": self.freq_en_box.isChecked(),
            "Width": self.width_en_box.isChecked(),
            "Duty": self.duty_en_box.isChecked(),
        }

        return self.config
