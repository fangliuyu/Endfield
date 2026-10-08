import logging
import os
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Union

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton,
    QFileDialog, QMessageBox, QVBoxLayout,
    QHBoxLayout, QScrollArea, QComboBox
)
from PySide6.QtCore import Qt

from lib.customlog import create_logger
from lib.filetools import read_data_from_yaml, save_data_to_yaml
from .keynote_manager import KeynoteManager
from .ppt_manager import PPTManager

file_types = [
    ('所有支持的文件', '*.pptx *.key'),
    ('PowerPoint 演示文稿', '*.pptx'),
    ('Keynote 演示文稿', '*.key'),
    ('启动宏的PowerPoint 演示文稿', '*.pptm'),
    ('PowerPoint 97-2003 演示文稿', '*.ppt'),
    ('PowerPoint 设计模板', '*.potx'),
    ('启动宏的PowerPoint 设计模板', '*.potm'),
    ('PowerPoint 97-2003 设计模板', '*.pot'),
    ('all file', '*.*')
]

# 用于AppleScript写入时的Keynote文件类型
keynote_save_types = [('Keynote 演示文稿', '*.key')]
pptx_save_types = [
    ('PowerPoint 演示文稿', '*.pptx'),
    ('PowerPoint 97-2003 演示文稿', '*.ppt'),
]


def _get_text_elements(text: str):
    """从文本中提取 {name} 占位符"""
    text_elements = {}
    for m in re.finditer(r'\{([^}]+)}', text):
        placeholder = m.group(0)  # {XXX}
        name = m.group(1)  # XXX
        text_elements[name] = placeholder
    return text_elements


def hide_middle_path(path_str: Path) -> str:
    """
    将路径中间部分替换为 "//"
    """
    path = Path(path_str)
    parts = path.parts

    # 如果路径部分少于3个，直接返回
    if len(parts) <= 3:
        return str(path)

    # 保留部分
    length = len(parts)//3 or 0
    first_part = parts[length]
    last_part = parts[-(length or 1)]

    # 构建新路径
    result = Path(first_part) / "..." / last_part
    return result.as_posix()


class MainWindow(QWidget):
    def __init__(
            self, name: str, version: str = '1.0.0', logger: logging.Logger = None,
            data_path: Union[os.PathLike[str], str, None] = None, *args, **kwargs
    ):
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
        self.temp_dir = self.data_path / "Template"
        if not self.temp_dir.exists():
            self.temp_dir.mkdir()
        self.default_file = self.temp_dir / "sample.pptx"
        if os.name == 'posix':
            self.default_file = self.temp_dir / "sample.key"
        if not self.default_file.exists():
            src_file = Path(__file__).parent / self.default_file.name
            shutil.copy2(src_file, self.default_file)
        self.current_ext = self.default_file.suffix
        self.setting_file = self.data_path / "setting.yaml"

        self.file_manager: Union[PPTManager, KeynoteManager, None] = None
        self.history_list = []
        self.elements = {}
        self.fields = {}            # name -> QLineEdit

        self.setWindowTitle('FA报告生成器 V'+version)
        self._setup_ui()
        self.load_setting()

    # ── UI 构建 ────────────────────────────────────────────────

    def _setup_ui(self):
        self.resize(500, 400)

        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        file_layout = QHBoxLayout()
        root_layout.addLayout(file_layout)
        file_layout.addWidget(QLabel('FA报告模板'))
        self.file_path_box = QComboBox()
        self.file_path_box.currentTextChanged.connect(self.choose_file_list)
        file_layout.addWidget(self.file_path_box, 1)
        browse_btn = QPushButton('选择模版')
        browse_btn.clicked.connect(self._choose_file)
        file_layout.addWidget(browse_btn)
        open_btn = QPushButton('编辑模版')
        open_btn.clicked.connect(self._open_sample_file)
        file_layout.addWidget(open_btn)

        self.info_label = QLabel("请选择报告模版...")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setStyleSheet('color: #888;')
        root_layout.addWidget(self.info_label)

        scroll_area = QScrollArea()
        scroll_area.setMinimumHeight(400)
        scroll_area.setMinimumWidth(680)
        scroll_area.setWidgetResizable(True)
        root_layout.addWidget(scroll_area, stretch=2)
        self.scroll_layout = QVBoxLayout()
        self.scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_area.setLayout(self.scroll_layout)

        generate_btn = QPushButton('生成FA报告')
        generate_btn.clicked.connect(self._generate)
        root_layout.addWidget(generate_btn)

    def deleteLater(self, /):
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        self.save_setting()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()

    def choose_file_list(self, current_text):
        self.file_path_box.blockSignals(True)
        file_path = self.file_path_box.currentData()
        self.logger.info(f"user choose {current_text} path is {file_path}")
        # current_text = self.file_path_box.currentData()
        self.load_file(file_path)
        self.file_path_box.blockSignals(False)

    # ── 加载配置 ────────────────────────────────────────────────

    def load_setting(self):
        data = {}
        if self.setting_file.exists():
            data = read_data_from_yaml(self.setting_file)
        self.file_path_box.clear()
        default_item = hide_middle_path(self.default_file)
        self.file_path_box.addItem(default_item, self.default_file.as_posix())
        default_file = data.get("default", "")
        if default_file:
            self.default_file = Path(default_file)
        self.history_list = data.get("history", [])
        for file_path in self.history_list:
            path = Path(file_path)
            if path.exists() and self.file_path_box.findData(file_path) == -1:
                self.file_path_box.addItem(hide_middle_path(path), path.as_posix())
        self.file_path_box.setCurrentText(default_item)

    def save_setting(self):
        data = {
            "default": self.default_file.as_posix(),
            "history": self.history_list,
        }
        save_data_to_yaml(data, self.setting_file)
        self.logger.info("保存用户数据成功")

    # ── 选择文件 ────────────────────────────────────────────────

    def _choose_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择报告模板', self.temp_dir.as_posix(), ';;'.join(t[1] for t in file_types)
        )
        if filepath:
            self.load_file(filepath)

    def load_file(self, filepath: str):
        if not filepath:
            return
        self.default_file = Path(filepath)
        tittle = hide_middle_path(self.default_file)
        if filepath not in self.history_list:
            self.history_list.append(filepath)
        if self.file_path_box.findData(filepath) == -1:
            self.file_path_box.addItem(tittle, filepath)
        self.file_path_box.setCurrentText(tittle)
        self.current_ext = self.default_file.suffix.lower()

        # 清除旧字段
        self._clear_fields()

        # 构建解析器
        try:
            if self.current_ext == ".key":
                self.file_manager = KeynoteManager(filepath)
            else:
                self.file_manager = PPTManager(filepath)
        except Exception as e:
            self.info_label.setText(f'文件加载失败, {e}')
            self.info_label.setStyleSheet('color: #d45e67;')
            QMessageBox.information(None, "错误", str(e))
            self.logger.exception(traceback.format_exc())
            return

        # 扫描占位符
        self.elements = self.scan_elements()

        # 动态生成输入框
        if not self.elements:
            self.info_label.setText('（文件中未找到占位符，请确认模板中包含 {name} 格式的标记）')
            self.info_label.setStyleSheet('color: #d45e67;')
            return

        for name in self.elements:
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(5, 2, 5, 2)

            label = QLabel(name)
            label.setFixedWidth(120)
            edit = QLineEdit()
            edit.setPlaceholderText(f'输入 {name} 的值...')
            row_layout.addWidget(label)
            row_layout.addWidget(edit, stretch=1)

            self.fields[name] = edit
            self.scroll_layout.addWidget(row_widget)

        self.info_label.setText("加载完成,请填写对应内容")
        self.info_label.setStyleSheet('color: #57b888;')

    def _open_sample_file(self):
        choose_file = self.file_path_box.currentData()
        file_path = Path(choose_file)
        if file_path:
            if sys.platform == 'win32':
                os.startfile(file_path)
            else:
                subprocess.run(['open', file_path])

    def _clear_fields(self):
        self.fields.clear()
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self.info_label.setText("正在加载文件")
        self.info_label.setStyleSheet('color: #ed8332;')

    def scan_elements(self):
        elements = {}
        text_list = self.file_manager.extract_all_text()
        for text in text_list:
            element_dict = _get_text_elements(text)
            elements.update(element_dict)
        return elements

    # ── 生成文件 ────────────────────────────────────────────────

    def _generate(self):
        if not self.default_file:
            QMessageBox.warning(self, '提示', '请先选择模板文件')
            return

        # 收集用户输入
        mapping = {}
        for name, edit in self.fields.items():
            val = edit.text().strip()
            mapping[self.elements[name]] = val

        # 构建默认文件名
        if self.current_ext == ".key":
            save_types = keynote_save_types
        else:
            save_types = pptx_save_types

        dst, _ = QFileDialog.getSaveFileName(
            self, '保存报告', '', ';;'.join(t[1] for t in save_types)
        )
        if not dst:
            return

        try:
            for old_text, new_text in mapping.items():
                self.file_manager.replace_all_text(old_text, new_text)

            dst = self.file_manager.save(dst)

            self.info_label.setText(f'报告已生成到{dst}')
            QMessageBox.information(self, '完成', f'报告已生成:\n{dst}')

            # 打开文件
            subprocess.run(['open', dst])

        except Exception as e:
            self.info_label.setText(f"生成失败, {e}")
            self.info_label.setStyleSheet('color: #ed8332;')
            self.logger.error(traceback.format_exc())
            QMessageBox.critical(self, '生成失败', str(e))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    win = MainWindow(name="FAreport")
    win.show()
    sys.exit(app.exec())
