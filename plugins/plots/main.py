import csv
import json
import logging
import re
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Optional, Union

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFrame, QGridLayout, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QFileDialog,
    QPlainTextEdit, QTabWidget, QMessageBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox as QComboBox2,
)
from PySide6.QtCore import Qt, QTimer

import matplotlib
import matplotlib.ticker as ticker
from matplotlib.figure import Figure
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from lib.customlog import create_logger

matplotlib.use('QtAgg')


# =============================================================================
# Tab 1: CSV 数据可视化
# =============================================================================

class PlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.csv_data = {}
        self.checkboxes = {}
        self.plot_names = []
        self.max_x = 0
        self.run_status = False

        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        # Control frame (checkboxes)
        self.control_frame = QFrame()
        self.control_frame.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(self.control_frame)
        self.checkbox_layout = QGridLayout(self.control_frame)
        self.checkbox_layout.setSpacing(3)

        # Axis config frame
        config_frame = QFrame()
        config_frame.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(config_frame)
        config_layout = QVBoxLayout(config_frame)
        config_layout.setSpacing(3)

        # Y axis config row
        y_row = QHBoxLayout()
        config_layout.addLayout(y_row)

        y_row.addWidget(QLabel("Y Min:"))
        self.y_min = QDoubleSpinBox()
        self.y_min.setRange(-1e12, 1e12)
        self.y_min.setDecimals(3)
        y_row.addWidget(self.y_min)

        y_row.addWidget(QLabel("Y Max:"))
        self.y_max = QDoubleSpinBox()
        self.y_max.setRange(-1e12, 1e12)
        self.y_max.setDecimals(3)
        y_row.addWidget(self.y_max)

        y_row.addWidget(QLabel("Y Step:"))
        self.y_step = QDoubleSpinBox()
        self.y_step.setRange(0, 1e12)
        self.y_step.setValue(100)
        self.y_step.setDecimals(3)
        y_row.addWidget(self.y_step)

        y_row.addWidget(QLabel("Y2 Min:"))
        self.y2_min = QDoubleSpinBox()
        self.y2_min.setRange(-1e12, 1e12)
        self.y2_min.setDecimals(3)
        y_row.addWidget(self.y2_min)

        y_row.addWidget(QLabel("Y2 Max:"))
        self.y2_max = QDoubleSpinBox()
        self.y2_max.setRange(-1e12, 1e12)
        self.y2_max.setDecimals(3)
        y_row.addWidget(self.y2_max)

        y_row.addWidget(QLabel("Y2 Step:"))
        self.y2_step = QDoubleSpinBox()
        self.y2_step.setRange(0, 1e12)
        self.y2_step.setValue(10)
        self.y2_step.setDecimals(3)
        y_row.addWidget(self.y2_step)

        # X axis config row
        x_row = QHBoxLayout()
        config_layout.addLayout(x_row)

        x_row.addWidget(QLabel("X Step:"))
        self.x_step = QSpinBox()
        self.x_step.setRange(1, 1000000)
        self.x_step.setValue(100)
        x_row.addWidget(self.x_step)

        x_row.addStretch()
        x_row.addWidget(QLabel("X Axis:"))
        self.x_combo = QComboBox()
        self.x_combo.setMinimumWidth(150)
        x_row.addWidget(self.x_combo)

        self.btn_file = QPushButton("选择文件")
        self.btn_file.clicked.connect(self.select_file)
        x_row.addWidget(self.btn_file)

        self.btn_draw = QPushButton("开始绘图")
        self.btn_draw.clicked.connect(self.draw_fig)
        x_row.addWidget(self.btn_draw)

        # Matplotlib figure
        figure_frame = QFrame()
        figure_frame.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(figure_frame, 1)

        fig_layout = QVBoxLayout(figure_frame)
        fig_layout.setContentsMargins(0, 0, 0, 0)

        self.fig = Figure()
        self.canvas = FigureCanvasQTAgg(self.fig)
        fig_layout.addWidget(self.canvas, 1)

        self.toolbar = NavigationToolbar2QT(self.canvas, figure_frame)
        fig_layout.addWidget(self.toolbar)

        # Animation timer
        self.timer = QTimer()
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update_step)

    def select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择CSV文件", "", "CSV文件 (*.csv);;所有文件 (*)"
        )
        if not file_path:
            return

        self.csv_data = {}
        with open(file_path, 'r') as f:
            csv_reader = csv.reader(f)
            column_names = next(csv_reader)
            for row in csv_reader:
                for i, key in enumerate(column_names):
                    self.csv_data.setdefault(key, []).append(row[i])

        # Clear existing checkboxes
        while self.checkbox_layout.count():
            item = self.checkbox_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.checkboxes = {}

        col = 0
        row = 0
        for name in self.csv_data.keys():
            cb = QCheckBox(name)
            self.checkbox_layout.addWidget(cb, row, col, Qt.AlignmentFlag.AlignLeft)
            self.checkboxes[name] = cb
            col += 1
            if col > 9:
                col = 0
                row += 1

        self.x_combo.clear()
        self.x_combo.addItems(list(self.csv_data.keys()))
        if self.x_combo.count() > 0:
            self.x_combo.setCurrentIndex(0)

    def draw_fig(self):
        if self.run_status:
            self.timer.stop()
            self.run_status = False
            self.btn_draw.setText("开始绘图")
            self.btn_file.setEnabled(True)
            return

        x_axis = self.x_combo.currentText()
        if not x_axis or not self.csv_data:
            return

        self.plot_names = [name for name, cb in self.checkboxes.items() if cb.isChecked()]
        if not self.plot_names:
            return

        self.max_x = len(self.csv_data[x_axis]) - 1
        self.current_index = 0
        self.x_axis_name = x_axis
        self.en_axis = len(self.plot_names) == 1

        self.running_y_min = float('inf')
        self.running_y_max = float('-inf')

        self.fig.clear()
        self.ax = self.fig.add_subplot()

        self.btn_file.setEnabled(False)
        self.btn_draw.setText("取消")

        self.x_data = []
        self.x_labels = []
        self.y_data = {name: [] for name in self.plot_names}
        self.plot_lines = {}
        self.ax2 = None

        y_max = self.y_max.value()
        y_min = self.y_min.value()

        if self.en_axis:
            self.ax.set_ylim(y_min * 0.9 if y_min else -1, y_max * 1.1 if y_max else 1)
            line, = self.ax.plot([], [], label=self.plot_names[0], scalex=True, scaley=True)
            self.plot_lines[self.plot_names[0]] = line
            self.ax.legend(bbox_to_anchor=(1.01, 1), loc='upper left', borderaxespad=0)
            self.fig.tight_layout()
            self.canvas.draw()
        else:
            max1 = 0
            max2 = 0
            ax1_labels = []
            ax2_labels = []
            for plot_label in self.plot_names:
                data = [float(v) for v in self.csv_data.get(plot_label, [])]
                mv = max(data)
                if max1 == 0 or max1 / mv < 2:
                    ax1_labels.append(plot_label)
                    if mv > max1:
                        max1 = mv
                else:
                    ax2_labels.append(plot_label)
                    if mv > max2:
                        max2 = mv

            color_idx = 0
            for label in ax1_labels:
                line, = self.ax.plot([], [], label=label, scalex=True, scaley=True, color=f'C{color_idx}')
                self.plot_lines[label] = line
                color_idx += 1

            if y_max > 0:
                self.ax.set_ylim(y_min * 0.9, y_max * 1.1)
            else:
                self.ax.set_ylim(y_min * 0.9, max1 * 1.1)
            self.ax.legend(bbox_to_anchor=(1.05, 1), loc='upper left', borderaxespad=0)

            if ax2_labels:
                y2_max = self.y2_max.value()
                y2_min = self.y2_min.value()
                self.ax2 = self.ax.twinx()
                for label in ax2_labels:
                    line, = self.ax2.plot([], [], label=label, scalex=True, scaley=True, color=f'C{color_idx}')
                    self.plot_lines[label] = line
                    color_idx += 1
                if y2_max > 0:
                    self.ax2.set_ylim(y2_min * 0.9, y2_max * 1.1)
                else:
                    self.ax2.set_ylim(y2_min * 0.9, max2 * 1.1)
                self.ax2.legend(bbox_to_anchor=(1.05, 1 - 0.1 * len(ax1_labels)),
                                loc='upper left', borderaxespad=0)
                self.ax2.yaxis.set_major_locator(ticker.MultipleLocator(float(self.y2_step.value())))

            self.fig.tight_layout()
            self.canvas.draw()

        self.ax.set_xlabel(self.x_axis_name)
        self.ax.yaxis.set_major_locator(ticker.MultipleLocator(float(self.y_step.value())))

        self.run_status = True
        self.timer.start()

    def update_step(self):
        x_step = self.x_step.value()
        x_name = self.csv_data[self.x_axis_name]

        for _ in range(5):
            if not self.run_status or self.current_index > self.max_x:
                self.timer.stop()
                self.run_status = False
                self.btn_draw.setText("开始绘图")
                self.btn_file.setEnabled(True)
                return

            idx = self.current_index
            self.x_data.append(idx)
            self.x_labels.append(x_name[idx])

            for name, line in self.plot_lines.items():
                y_value = float(self.csv_data[name][idx])
                self.y_data[name].append(y_value)

                if self.en_axis:
                    if y_value < self.running_y_min:
                        self.running_y_min = y_value
                    if y_value > self.running_y_max:
                        self.running_y_max = y_value
                    self.ax.set_ylim(self.running_y_min * 0.9, self.running_y_max * 1.1)

                self.ax.set_xticks(ticks=self.x_data, labels=self.x_labels, rotation='vertical')
                self.fig.tight_layout()
                self.canvas.draw()
                line.set_xdata(self.x_data)
                line.set_ydata(self.y_data[name])

            self.current_index += x_step

        self.fig.tight_layout()
        self.canvas.draw()

    def stop_plot(self):
        self.timer.stop()
        self.run_status = False
        self.btn_draw.setText("开始绘图")
        self.btn_file.setEnabled(True)


# =============================================================================
# Tab 2: 可配置的数据提取
# =============================================================================

@dataclass
class ExtractionRule:
    """一条提取规则"""
    enabled: bool = True
    name: str = ""  # 字段名 (内部标识)
    prefix: str = ""  # 值前面的文本
    suffix: str = ""  # 值后面的文本
    header: str = ""  # CSV 列名
    required: bool = False  # 找不到时是否跳过整行
    capture_type: str = "数字"  # 数字 / 文本 / 前缀前所有


DEFAULT_RULES = [
    ExtractionRule(name="log_time", prefix="|", suffix="", header="Time",
                   required=True, capture_type="前缀前所有"),
    ExtractionRule(name="voltage", prefix="V:", suffix="mV", header="V(mV)"),
    ExtractionRule(name="current", prefix="I:", suffix="mA", header="I(mA)"),
    ExtractionRule(name="soc", prefix="SOC:", suffix="%", header="SOC(%)"),
    ExtractionRule(name="rawsoc", prefix="RawSOC:", suffix="%", header="RawSOC(%)", required=True),
    ExtractionRule(name="tmlb", prefix="tMLB:", suffix="C", header="MLB Thermal(C)"),
    ExtractionRule(name="tbatt", prefix="tBatt:", suffix="C", header="Batt Thermal(C)"),
    ExtractionRule(name="cap", prefix="Cap:", suffix="mAh", header="Capture(mAh)"),
]

CAPTURE_TYPES = ["数字", "文本", "前缀前所有"]
COL_NAME = 0
COL_PREFIX = 1
COL_SUFFIX = 2
COL_HEADER = 3
COL_CAPTURE = 4
COL_ENABLED = 5
COL_REQUIRED = 6
COL_PREVIEW = 7


def build_regex(prefix: str, suffix: str, capture_type: str) -> str:
    """根据前缀/后缀/类型生成正则"""
    esc_prefix = re.escape(prefix) if prefix else ""
    esc_suffix = re.escape(suffix) if suffix else ""
    if capture_type == "前缀前所有":
        return esc_prefix + r'(.+)' if prefix else r'(.+)'
    elif capture_type == "文本":
        return esc_prefix + r'(.+?)' + esc_suffix
    else:  # 数字
        return esc_prefix + r'([\d.]+)' + esc_suffix


def compile_pattern(prefix: str, suffix: str, capture_type: str) -> re.Pattern:
    """编译正则, 数字/文本类型需要确保至少匹配到内容"""
    pattern_str = build_regex(prefix, suffix, capture_type)
    return re.compile(pattern_str)


class ExtractionRulesWidget(QWidget):
    """提取规则编辑表格"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rules: list[ExtractionRule] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        # Sample log line for testing
        sample_row = QHBoxLayout()
        layout.addLayout(sample_row)
        sample_row.addWidget(QLabel("日志示例:"))
        self.sample_input = QPlainTextEdit()
        self.sample_input.setMaximumBlockCount(1)
        self.sample_input.setPlaceholderText("在此粘贴一行日志用于测试提取规则...")
        self.sample_input.setFixedHeight(60)
        sample_row.addWidget(self.sample_input, 1)

        self.btn_test = QPushButton("测试提取")
        self.btn_test.clicked.connect(self.test_extraction)
        sample_row.addWidget(self.btn_test)

        self.test_result = QLabel("")
        sample_row.addWidget(self.test_result, 1)

        # Table
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["字段名", "前缀", "后缀", "保存名称",
                                              "提取类型", "启用", "必需", "正则预览"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_PREVIEW, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(COL_NAME, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_CAPTURE, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_ENABLED, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(COL_REQUIRED, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table, 1)

        # Buttons row
        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)

        self.btn_add = QPushButton("+ 添加规则")
        self.btn_add.clicked.connect(self.add_rule)
        btn_row.addWidget(self.btn_add)

        self.btn_remove = QPushButton("- 删除选中")
        self.btn_remove.clicked.connect(self.remove_selected)
        btn_row.addWidget(self.btn_remove)

        btn_row.addStretch()

        self.btn_save_cfg = QPushButton("保存配置")
        self.btn_save_cfg.clicked.connect(self.save_config)
        btn_row.addWidget(self.btn_save_cfg)

        self.btn_load_cfg = QPushButton("加载配置")
        self.btn_load_cfg.clicked.connect(self.load_config)
        btn_row.addWidget(self.btn_load_cfg)

        self.btn_reset = QPushButton("恢复默认")
        self.btn_reset.clicked.connect(self.reset_defaults)
        btn_row.addWidget(self.btn_reset)

        # Init with defaults
        self.reset_defaults()

    def reset_defaults(self):
        self.load_rules(DEFAULT_RULES)

    def load_rules(self, rules: list[ExtractionRule]):
        self.rules = list(rules)
        self._rebuild_table()

    def _rebuild_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            self._set_row(row, rule)
        self.table.blockSignals(False)

    def _set_row(self, row: int, rule: ExtractionRule):
        # 字段名
        item = QTableWidgetItem(rule.name)
        self.table.setItem(row, COL_NAME, item)

        # 前缀
        item = QTableWidgetItem(rule.prefix)
        self.table.setItem(row, COL_PREFIX, item)

        # 后缀
        item = QTableWidgetItem(rule.suffix)
        self.table.setItem(row, COL_SUFFIX, item)

        # 保存名称
        item = QTableWidgetItem(rule.header)
        self.table.setItem(row, COL_HEADER, item)

        # 提取类型 (combobox)
        cb = QComboBox2()
        cb.addItems(CAPTURE_TYPES)
        cb.setCurrentText(rule.capture_type)
        cb.currentTextChanged.connect(lambda: self._on_cell_changed())
        self.table.setCellWidget(row, COL_CAPTURE, cb)

        # 启用 (checkbox)
        enabled_cb = QCheckBox()
        enabled_cb.setChecked(rule.enabled)
        enabled_cb.stateChanged.connect(lambda: self._on_cell_changed())
        self.table.setCellWidget(row, COL_ENABLED, enabled_cb)

        # 必需 (checkbox)
        required_cb = QCheckBox()
        required_cb.setChecked(rule.required)
        required_cb.stateChanged.connect(lambda: self._on_cell_changed())
        self.table.setCellWidget(row, COL_REQUIRED, required_cb)

        # 正则预览 (read-only)
        preview = build_regex(rule.prefix, rule.suffix, rule.capture_type)
        preview_item = QTableWidgetItem(preview)
        preview_item.setFlags(preview_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        preview_item.setForeground(Qt.GlobalColor.gray)
        self.table.setItem(row, COL_PREVIEW, preview_item)

    def _on_cell_changed(self):
        """当表格内容变化时更新预览列和内部规则"""
        self.table.blockSignals(True)
        for row in range(self.table.rowCount()):
            name = self.table.item(row, COL_NAME).text() if self.table.item(row, COL_NAME) else ""
            prefix = self.table.item(row, COL_PREFIX).text() if self.table.item(row, COL_PREFIX) else ""
            suffix = self.table.item(row, COL_SUFFIX).text() if self.table.item(row, COL_SUFFIX) else ""
            header = self.table.item(row, COL_HEADER).text() if self.table.item(row, COL_HEADER) else ""

            capture_widget = self.table.cellWidget(row, COL_CAPTURE)
            capture_type = capture_widget.currentText() if capture_widget else "数字"

            enabled_widget = self.table.cellWidget(row, COL_ENABLED)
            enabled = enabled_widget.isChecked() if enabled_widget else True

            required_widget = self.table.cellWidget(row, COL_REQUIRED)
            required = required_widget.isChecked() if required_widget else False

            # Build and update preview
            preview = build_regex(prefix, suffix, capture_type)
            preview_item = self.table.item(row, COL_PREVIEW)
            if preview_item:
                preview_item.setText(preview)

            # Update internal rules
            if row < len(self.rules):
                rule = self.rules[row]
                rule.name = name
                rule.prefix = prefix
                rule.suffix = suffix
                rule.header = header
                rule.capture_type = capture_type
                rule.enabled = enabled
                rule.required = required
        self.table.blockSignals(False)

    def add_rule(self):
        """添加一条空规则"""
        rule = ExtractionRule(name="new_field", header="NewHeader")
        self.table.blockSignals(True)
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._set_row(row, rule)
        self.rules.append(rule)
        self.table.blockSignals(False)

    def remove_selected(self):
        """删除选中的行"""
        rows = set()
        for item in self.table.selectedItems():
            rows.add(item.row())
        if not rows:
            return
        self.table.blockSignals(True)
        for row in sorted(rows, reverse=True):
            self.table.removeRow(row)
            if row < len(self.rules):
                self.rules.pop(row)
        self.table.blockSignals(False)

    def get_active_rules(self) -> list[ExtractionRule]:
        """获取当前启用的规则"""
        self._on_cell_changed()  # sync first
        return [r for r in self.rules if r.enabled]

    def test_extraction(self):
        """用示例日志测试提取"""
        sample = self.sample_input.toPlainText().strip()
        if not sample:
            self.test_result.setText("请先输入日志示例")
            return

        rules = self.get_active_rules()
        results = []
        for rule in rules:
            pattern = compile_pattern(rule.prefix, rule.suffix, rule.capture_type)
            m = pattern.search(sample)
            if m:
                results.append(f"{rule.name}={m.group(1)}")
            else:
                results.append(f"{rule.name}=未匹配")

        self.test_result.setText(" | ".join(results))

    def save_config(self):
        """保存规则配置到 JSON 文件"""
        self._on_cell_changed()
        path, _ = QFileDialog.getSaveFileName(self, "保存规则配置", "",
                                              "JSON文件 (*.json);;所有文件 (*)")
        if not path:
            return
        data = [asdict(r) for r in self.rules]
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_config(self):
        """从 JSON 文件加载规则配置"""
        path, _ = QFileDialog.getOpenFileName(self, "加载规则配置", "",
                                              "JSON文件 (*.json);;所有文件 (*)")
        if not path:
            return
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        rules = [ExtractionRule(**d) for d in data]
        self.load_rules(rules)


class DataGetWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        # Rule editor
        rule_label = QLabel("提取规则配置:")
        rule_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(rule_label)

        self.rule_editor = ExtractionRulesWidget()
        layout.addWidget(self.rule_editor, 1)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(sep)

        # Execution area
        exec_label = QLabel("执行数据提取:")
        exec_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(exec_label)

        # File selection
        file_frame = QFrame()
        file_frame.setFrameStyle(QFrame.Shape.Box)
        layout.addWidget(file_frame)
        file_layout = QVBoxLayout(file_frame)

        txt_row = QHBoxLayout()
        file_layout.addLayout(txt_row)
        txt_row.addWidget(QLabel("日志文件(TXT):"))
        self.txt_path = QLabel("未选择")
        self.txt_path.setStyleSheet("color: #888;")
        txt_row.addWidget(self.txt_path, 1)
        self.btn_txt = QPushButton("浏览")
        self.btn_txt.clicked.connect(self.select_txt)
        txt_row.addWidget(self.btn_txt)

        csv_row = QHBoxLayout()
        file_layout.addLayout(csv_row)
        csv_row.addWidget(QLabel("数据文件(CSV):"))
        self.csv_path = QLabel("未选择")
        self.csv_path.setStyleSheet("color: #888;")
        csv_row.addWidget(self.csv_path, 1)
        self.btn_csv = QPushButton("浏览")
        self.btn_csv.clicked.connect(self.select_csv)
        csv_row.addWidget(self.btn_csv)

        # Execute + output
        btn_row = QHBoxLayout()
        layout.addLayout(btn_row)
        self.btn_exec = QPushButton("执行数据提取")
        self.btn_exec.clicked.connect(self.execute)
        self.btn_exec.setMinimumHeight(36)
        btn_row.addWidget(self.btn_exec)
        btn_row.addStretch()

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        self.log_output.setStyleSheet("""
            QPlainTextEdit {
                font-family: 'Courier New', monospace;
                font-size: 12px;
                background-color: #1e1e1e;
                color: #d4d4d4;
            }
        """)
        layout.addWidget(self.log_output, 1)

        self.selected_txt = ""
        self.selected_csv = ""

    def select_txt(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择日志文件", "",
                                              "文本文件 (*.txt *.log);;所有文件 (*)")
        if path:
            self.selected_txt = path
            self.txt_path.setText(path)
            self.txt_path.setStyleSheet("color: #000;")

    def select_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择数据文件", "",
                                              "CSV文件 (*.csv);;所有文件 (*)")
        if path:
            self.selected_csv = path
            self.csv_path.setText(path)
            self.csv_path.setStyleSheet("color: #000;")

    def log(self, message: str):
        self.log_output.appendPlainText(message)
        QApplication.processEvents()

    def execute(self):
        if not self.selected_txt or not self.selected_csv:
            QMessageBox.warning(self, "提示", "请先选择日志文件和数据文件")
            return

        rules = self.rule_editor.get_active_rules()
        if not rules:
            QMessageBox.warning(self, "提示", "没有启用的提取规则")
            return

        self.log_output.clear()
        self.log("开始数据提取...")
        self.btn_exec.setEnabled(False)

        try:
            self._do_extract(rules)
            self.log("数据提取完成！")
        except Exception as e:
            self.log(f"错误: {e}")
            import traceback
            self.log(traceback.format_exc())
        finally:
            self.btn_exec.setEnabled(True)

    def _do_extract(self, rules: list[ExtractionRule]):
        self.log(f"日志文件: {self.selected_txt}")
        self.log(f"数据文件: {self.selected_csv}")
        self.log(f"启用规则: {', '.join(r.name for r in rules)}")

        # Parse log file with rules
        log_data = []
        compiled_rules = [(r, compile_pattern(r.prefix, r.suffix, r.capture_type)) for r in rules]

        with open(self.selected_txt, 'r') as f:
            logs = f.readlines()

        self.log(f"读取日志共 {len(logs)} 行")

        for line_no, data in enumerate(logs, 1):
            row = []
            skip = False
            for rule, pattern in compiled_rules:
                m = pattern.search(data)
                if m:
                    row.append(m.group(1).strip())
                elif rule.required:
                    skip = True
                    break
                else:
                    row.append("")
            if skip:
                continue
            log_data.append(row)

        self.log(f"解析日志得到 {len(log_data)} 条记录")

        # Build CSV headers
        csv_headers = [r.header for r in rules]

        # Merge with CSV
        base_path = str(Path(self.selected_txt).parent)
        with open(self.selected_csv, 'r') as f:
            csv_reader = csv.reader(f)
            column_names = next(csv_reader)
            csv_headers.extend(column_names[1:])

            i = 0
            skipped = 0
            for row in csv_reader:
                if i >= len(log_data):
                    break

                csv_ts = (datetime.fromtimestamp(int(row[0]))
                          if row[0].isdigit()
                          else datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S.%f"))

                log_ts = datetime.strptime(log_data[i][0], "%Y-%m-%d %H:%M:%S.%f")

                if log_ts > csv_ts:
                    skipped += 1
                    continue

                if i < len(log_data) - 2:
                    next_log_ts = datetime.strptime(log_data[i + 1][0], "%Y-%m-%d %H:%M:%S.%f")
                    if next_log_ts <= csv_ts:
                        skipped += 1
                        continue

                log_data[i].extend(row[1:])
                i += 1

        self.log(f"匹配合并 {i} 条数据 (跳过 {skipped} 条不匹配)")

        # Write output
        output_path = Path(base_path) / 'points.csv'
        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter=',', quotechar='|', quoting=csv.QUOTE_MINIMAL)
            writer.writerow(csv_headers)
            writer.writerows(log_data)

        self.log(f"输出文件: {output_path}")
        QMessageBox.information(self, "完成", f"数据提取完成！\n输出: {output_path}")


# =============================================================================
# MainWindow
# =============================================================================

class MainWindow(QMainWindow):
    def __init__(self, name: str, version: str = "1.0.0", logger: Optional[logging.Logger] = None,
                 data_path: Union[PathLike[str], str, None] = None, dryrun: bool = False, *args, **kwargs):
        super().__init__()
        self.widget_name = name
        self.logger = logger
        self.data_path = Path.cwd()
        if data_path:
            self.data_path = Path(data_path)
        self.data_path.mkdir(exist_ok=True)
        if not self.logger:
            log_path = self.data_path / "script_log"
            log_path.mkdir(exist_ok=True)
            self.logger = create_logger(name=name, level=logging.DEBUG, log_path=log_path)
        self.logger.info(f"{name} logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        self.setWindowTitle(f"数据工具 v{version}")
        self.resize(1000, 700)

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        self.plot_widget = PlotWidget()
        tabs.addTab(self.plot_widget, "数据绘图")

        self.dataget_widget = DataGetWidget()
        tabs.addTab(self.dataget_widget, "数据提取")

        tabs.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index: int):
        if index != 0:
            self.plot_widget.stop_plot()

    def closeEvent(self, event):
        self.plot_widget.stop_plot()
        super().closeEvent(event)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="plots", version="0.0.1")
    window.show()
    sys.exit(app.exec())
