
from typing import List
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout,QPushButton,
    QLabel, QMessageBox, QInputDialog,
    QComboBox, QListWidget, QDialog, QCheckBox
)
from PySide6.QtCore import Qt


class ConfigurationDialog(QDialog):
    """配置对话框"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.default_plugin = self.controller.default_plugin
        self.plugin_category: dict[str: list] = self.controller.plugin_category.copy()
        self.rm_category_list: List[str] = self.controller.category_disable_list.copy()

        self.setWindowTitle("工具配置")
        self.setFixedSize(400, 300)
        self.setModal(True)
        layout = QVBoxLayout(self)

        ui_setting_layout = QHBoxLayout()
        layout.addLayout(ui_setting_layout)
        self.panel_switch = QCheckBox("自动显示面板")
        self.panel_switch.setChecked(self.controller.expand_enable)
        ui_setting_layout.addWidget(self.panel_switch)
        self.limit_switch = QCheckBox("允许插件开启多个")
        self.limit_switch.setChecked(self.controller.no_limit_widget)
        ui_setting_layout.addWidget(self.limit_switch)
        ui_setting_layout.addStretch()
        debug_switch = QCheckBox("debug")
        debug_switch.setChecked(not self.controller.debug_widget.isHidden())
        debug_switch.checkStateChanged.connect(self.switch_debug)
        ui_setting_layout.addWidget(debug_switch)

        default_setting_layout = QHBoxLayout()
        layout.addLayout(default_setting_layout)
        default_setting_layout.addWidget(QLabel("设置默认启动工具:"))
        self.default_combo = QComboBox()
        all_plugins = self.controller.get_all_plugins()
        self.default_combo.addItems([""] + sorted(set(all_plugins)))
        if self.default_plugin:
            index = self.default_combo.findText(self.default_plugin)
            if index >= 0:
                self.default_combo.setCurrentIndex(index)
        default_setting_layout.addWidget(self.default_combo, 1)

        category_label = QLabel("工具分类管理:")
        layout.addWidget(category_label)
        self.category_list = QListWidget()
        layout.addWidget(self.category_list)

        category_buttons_layout = QHBoxLayout()
        add_category_btn = QPushButton("添加分类")
        add_category_btn.clicked.connect(self.add_category)
        category_buttons_layout.addWidget(add_category_btn)
        remove_category_btn = QPushButton("删除分类")
        remove_category_btn.clicked.connect(self.remove_category)
        category_buttons_layout.addWidget(remove_category_btn)
        layout.addLayout(category_buttons_layout)

        buttons_layout = QHBoxLayout()
        save_btn = QPushButton("应用")
        save_btn.clicked.connect(self.save_config)
        buttons_layout.addWidget(save_btn)
        reset_btn = QPushButton("重置")
        reset_btn.clicked.connect(self.reset_config)
        buttons_layout.addWidget(reset_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        buttons_layout.addWidget(cancel_btn)
        layout.addLayout(buttons_layout)

        self.refresh_category_list()

    def switch_debug(self, state):
        debug_widget = self.controller.debug_widget
        if state == Qt.CheckState.Checked:
            debug_widget.show()
        else:
            debug_widget.hide()

    def refresh_category_list(self):
        self.category_list.clear()
        for category in self.plugin_category.keys():
            plugin_count = len(self.plugin_category[category])
            self.category_list.addItem(f"{category} ({plugin_count}个工具)")

    def add_category(self):
        name, ok = QInputDialog.getText(self, "添加分类", "请输入分类名称:")
        if ok and name:
            if name in self.plugin_category:
                return
            if name in self.rm_category_list:
                index = self.rm_category_list.index(name)
                self.rm_category_list.pop(index)
            self.plugin_category[name] = []
            self.refresh_category_list()

    def remove_category(self):
        current_item = self.category_list.currentItem()
        if current_item:
            category_name = current_item.text().split(" ")[0]
            if category_name in ["ALL"]:
                QMessageBox.warning(self, "警告", "系统默认分类不能删除!")
                return
            reply = QMessageBox.question(self, "确认删除", f"确定要删除分类 '{category_name}' 吗？")
            if reply == QMessageBox.StandardButton.Yes:
                del self.plugin_category[category_name]
                self.rm_category_list.append(category_name)
                self.refresh_category_list()

    def save_config(self):
        self.controller.expand_enable = self.panel_switch.isChecked()
        self.controller.no_limit_widget = self.limit_switch.isChecked()
        self.controller.default_plugin = self.default_combo.currentText()
        self.controller.category_disable_list = self.rm_category_list.copy()
        self.controller.plugin_category = self.plugin_category.copy()
        ok = self.controller.save_favorites()
        if ok:
            QMessageBox.information(self, "成功", "配置保存成功!")
        self.close()

    def reset_config(self):
        self.controller.reset_favorites()
        self.plugin_category = self.controller.plugin_category.copy()
        self.refresh_category_list()
        QMessageBox.information(self, "成功", "已重置!")
