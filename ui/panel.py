import inspect
import shutil
import sys
import logging
import traceback
import importlib
from concurrent.futures import ThreadPoolExecutor
from importlib import util
from pathlib import Path
from typing import Optional, Dict, List

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget,
    QPushButton, QLabel, QFrame, QButtonGroup,
    QMessageBox, QMenu, QFileDialog, QComboBox,
    QLineEdit, QDialog, QApplication
)
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QCursor, QIcon

from lib.customlog import create_logger
from lib.filetools import read_data_from_yaml, save_data_to_yaml
from lib.qtui.custom_widget import (
    HorizontalWheelScrollArea, ImageTextButton,
    LogWidget, LoadingDialog, SignalWrapper
)
from src.build_custom_plugin import build_plugin
from lib.deviceCheck import check_error
from src.base import builtin_plugins_path, custom_plugins_path, main_path, root_log, root_path
from src.plugin_manager import PluginManager, PluginInfo


class NewPluginDialog(QDialog):
    """配置对话框"""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.plugins_data: dict = self.controller.plugin_category.copy()
        self.folder_ptah = Path()
        self.plugin_data: PluginInfo = PluginInfo(name="")

        self.setWindowTitle("new plugin info")
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        file_layout = QHBoxLayout()
        layout.addLayout(file_layout)
        self.folder_txt = QLineEdit()
        self.folder_txt.setPlaceholderText("选择后会自动以文件夹名命名Name")
        self.folder_txt.setReadOnly(True)
        file_layout.addWidget(self.folder_txt, 1)
        choose_btn = QPushButton("choose tool folder")
        choose_btn.clicked.connect(self.choose_folder_path)
        file_layout.addWidget(choose_btn)

        info_layout = QHBoxLayout()
        layout.addLayout(info_layout)
        info_layout.addWidget(QLabel("Name:"))
        self.name_txt = QLineEdit()
        self.name_txt.setFixedWidth(120)
        info_layout.addWidget(self.name_txt)
        info_layout.addStretch()
        info_layout.addWidget(QLabel("Auther:"))
        self.auther_txt = QLineEdit()
        self.auther_txt.setFixedWidth(80)
        info_layout.addWidget(self.auther_txt)
        info_layout.addStretch()
        info_layout.addWidget(QLabel("Version:"))
        self.version_txt = QLineEdit()
        self.version_txt.setFixedWidth(60)
        info_layout.addWidget(self.version_txt)

        introduction_layout = QHBoxLayout()
        layout.addLayout(introduction_layout)
        introduction_layout.addWidget(QLabel("Introduction:"))
        self.introduction_txt = QLineEdit()
        introduction_layout.addWidget(self.introduction_txt, 1)

        category_layout = QHBoxLayout()
        layout.addLayout(category_layout)
        category_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        for category in self.plugins_data.keys():
            if category == "ALL":
                continue
            self.category_combo.addItem(category)
        self.category_combo.setEditable(True)
        self.category_combo.setCurrentIndex(0)
        category_layout.addWidget(self.category_combo)
        category_layout.addStretch()
        category_layout.addWidget(QLabel("ToolType:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["QT", "Command"])
        self.type_combo.currentTextChanged.connect(self.show_setting)
        category_layout.addWidget(self.type_combo)

        self.qt_widget = QWidget()
        layout.addWidget(self.qt_widget)
        qt_info_layout = QHBoxLayout(self.qt_widget)
        qt_info_layout.addWidget(QLabel("PacketPath:"))
        self.packet_txt = QLineEdit("main_window")
        qt_info_layout.addWidget(self.packet_txt)
        qt_info_layout.addStretch()
        qt_info_layout.addWidget(QLabel("ModuleName:"))
        self.module_txt = QLineEdit("MainWindow")
        qt_info_layout.addWidget(self.module_txt)

        self.commands_widget = QWidget()
        layout.addWidget(self.commands_widget)
        commands_layout = QHBoxLayout(self.commands_widget)
        commands_layout.addWidget(QLabel("Commands:"))
        self.commands_txt = QLineEdit()
        commands_layout.addWidget(self.commands_txt, 1)
        self.commands_widget.hide()

        buttons_layout = QHBoxLayout()
        add_btn = QPushButton("ADD")
        buttons_layout.addStretch()
        add_btn.setFixedHeight(30)
        add_btn.clicked.connect(self.add_plugin)
        buttons_layout.addWidget(add_btn, 1)
        buttons_layout.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.clicked.connect(self.close)
        buttons_layout.addWidget(cancel_btn, 1)
        layout.addLayout(buttons_layout)
        buttons_layout.addStretch()

    def show_setting(self, text):
        if text == "QT":
            self.commands_widget.hide()
            self.qt_widget.show()
        else:
            self.qt_widget.hide()
            self.commands_widget.show()

    def choose_folder_path(self):
        new_path = QFileDialog.getExistingDirectory(None, "Choose plugin Folder", "")
        self.folder_ptah = Path(new_path)
        self.folder_txt.setText(new_path)
        self.name_txt.setText(self.folder_ptah.name)

        if (self.folder_ptah / "__init__.py").exists():
            plugin_init_path = self.folder_ptah / "__init__.py"
            unique_module_name = f"custom_{self.folder_ptah.name}_plugin"
            spec = importlib.util.spec_from_file_location(unique_module_name, plugin_init_path)
            self.controller.logger.info(f"set spec to modulename {unique_module_name} from path {plugin_init_path}")
            module = importlib.util.module_from_spec(spec)
            self.controller.logger.info(f"load module from spec successfully")
            plugin_dir_path = self.folder_ptah
            if str(plugin_dir_path) not in sys.path:
                self.controller.logger.info(f"add {plugin_dir_path} to sys path")
                sys.path.insert(0, str(plugin_dir_path))
            sys.modules[unique_module_name] = module
            spec.loader.exec_module(module)
            self.controller.logger.info(f"builder {module} successfully")
            self.plugin_data = PluginInfo(name=self.folder_ptah.name)
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if hasattr(attr, '_plugin_metadata'):
                    self.plugin_data = attr._plugin_metadata  # NOQA
                    if self.plugin_data.handler == attr:
                        self.controller.logger.info(f"通过 register().handler() 找到插件: {attr_name}")
                        break
            if not self.plugin_data.handler:
                self.controller.logger.error(f"插件 {self.folder_ptah.name} 未找到任何可用的插件类")
                return
            self.name_txt.setText(self.plugin_data.name)
            self.auther_txt.setText(self.plugin_data.author)
            self.version_txt.setText(self.plugin_data.version)
            self.category_combo.setCurrentText(self.plugin_data.category)
            self.introduction_txt.setText(self.plugin_data.introduction)
            self.type_combo.setCurrentText("QT")
            handler = self.plugin_data.handler
            self.packet_txt.setText(Path(inspect.getfile(handler)).stem)
            self.module_txt.setText(handler.__name__)

    def add_plugin(self):
        plugin_name = self.name_txt.text()
        if plugin_name in self.plugins_data["ALL"]:
            QMessageBox.warning(self, "警告", "该工具名已存在!")
            return
        try:
            new_path = custom_plugins_path / plugin_name
            if new_path.exists():
                QMessageBox.warning(self, "警告", f"目录已存在: {new_path}")
                return
            new_path.mkdir()

            plugin_type = self.type_combo.currentText()
            has_folder = bool(self.folder_ptah) and self.folder_ptah != Path() and self.folder_ptah.exists()

            plugin_build = build_plugin(
                name=self.name_txt.text(),
                author=self.auther_txt.text(),
                version=self.version_txt.text(),
                category=self.category_combo.currentText(),
                introduction=self.introduction_txt.text(),
            )
            plugin_build.set_root_dir(new_path)

            if plugin_type == "QT":
                if has_folder:
                    # 有文件夹：复制用户代码并按用户指定的 packet/module 生成 __init__.py
                    shutil.copytree(self.folder_ptah, new_path, dirs_exist_ok=True)
                    plugin_build.set_handler_path(
                        packet_path=self.packet_txt.text(),
                        module_name=self.module_txt.text()
                    )
                    if (self.folder_ptah / "__init__.py").exists():
                        plugin_build.update_init_file()
                    else:
                        plugin_build.add_init_file()
                else:
                    # 无文件夹：以 example 插件为模板生成骨架
                    plugin_build.build_from_template()
            else:
                commands = [cmd for cmd in self.commands_txt.text().split("\n")]
                plugin_build.set_terminal_handler(commands)
                if has_folder and (self.folder_ptah / "__init__.py").exists():
                    shutil.copytree(self.folder_ptah, new_path, dirs_exist_ok=True)
                    plugin_build.update_init_file()
                else:
                    if has_folder:
                        shutil.copytree(self.folder_ptah, new_path, dirs_exist_ok=True)
                    plugin_build.add_init_file()

            # 从磁盘加载新生成的插件，由 plugin_loaded 信号触发按钮创建
            self.controller.plugin_manager.load_plugin(plugin_name, "custom", True)
            QMessageBox.information(self, "成功", "添加成功!")
        except Exception as e:
            self.controller.logger.error(traceback.format_exc())
            QMessageBox.information(self, "添加失败", str(e))
        self.close()


class FloatingPanel(QWidget):
    """桌面浮动面板"""

    def __init__(self, parent=None, logger: logging.Logger = root_log, data_path: Optional[Path] = main_path):
        super().__init__(parent)

        # 窗口属性
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MouseTracking, True)

        # 应用配置
        self.data_path = data_path
        self.logger = logger
        self.logger.info("Endfield logging started")
        self.base_dir = root_path
        self.favorites_file = self.data_path / "favorites.yaml"

        # 数据
        self.plugin_buttons: Dict[str, ImageTextButton] = {}
        self.plugin_category: Dict[str, List[str]] = {"ALL": []}
        self.category_disable_list: List[str] = []
        self.plugin_disable_list: List[str] = []
        self.plugin_source: Dict[str, str] = {}
        self.default_plugin = ""
        self.current_category = None
        self.plugin_windows: Dict[str, QWidget] = {}
        self.all_plugin_windows: List[QWidget] = []
        self._first_launch = True
        self.is_visible = False
        self.no_limit_widget = False
        self.expand_enable = True

        # 调试和加载
        self.debug_widget = LogWidget(self)
        self.debug_widget.log_box.set_logger(self.logger, level=logging.DEBUG)
        self.loading_dialog = LoadingDialog(self)
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.finish_signal = SignalWrapper(bool)
        self.finish_signal.Signal.connect(self.on_data_loaded)

        # 面板尺寸
        screen_geo = QApplication.primaryScreen().availableGeometry()
        self.trigger_height = 1
        self.expanded_height = 160
        self.panel_width = int(screen_geo.width() * 2 / 3)

        # 动画
        self._target_height = self.trigger_height
        self.animation_timer = QTimer(self)
        self.animation_timer.timeout.connect(self.animate_step)
        self.animation_timer.setInterval(10)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.start_shrink)

        # 全局鼠标轮询：当其他应用在前台时，检测鼠标是否到达触发区域
        self._cursor_timer = QTimer(self)
        self._cursor_timer.timeout.connect(self._poll_cursor)
        self._cursor_timer.setInterval(100)
        self._cursor_timer.start()

        """初始化面板UI"""
        self.setObjectName("FloatingPanel")
        self.setStyleSheet("""
            QWidget#FloatingPanel {
                background: rgba(245, 245, 245, 230);
                border: 1px solid #ccc;
                border-radius: 10px;
            }
        """)

        float_layout = QVBoxLayout(self)
        float_layout.setContentsMargins(10, 5, 10, 5)
        float_layout.setSpacing(5)

        # 第一行：分类按钮
        category_frame = QFrame()
        category_frame.setFixedHeight(30)
        category_frame.setStyleSheet("QFrame { background: transparent; border: none; }")
        category_layout = QHBoxLayout(category_frame)
        category_layout.setContentsMargins(0, 0, 0, 0)
        category_layout.setSpacing(10)

        category_scroll = HorizontalWheelScrollArea()
        category_scroll.setFixedHeight(30)
        category_scroll.setWidgetResizable(True)

        self.category_frame = QFrame()
        self.category_layout = QHBoxLayout(self.category_frame)
        self.category_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.category_layout.setContentsMargins(0, 0, 0, 0)
        self.category_layout.setSpacing(5)

        self.category_group = QButtonGroup(self)
        self.category_group.buttonClicked.connect(self.on_category_changed)
        category_scroll.setWidget(self.category_frame)
        category_layout.addWidget(category_scroll)

        btn_style = """
            QPushButton { background: #e0e0e0; border: none; border-radius: 5px; font-weight: bold; }
            QPushButton:checked { background: #007acc; color: white; }
            QPushButton:hover { background: #d0d0d0; }
        """
        refresh_btn = QPushButton("🔄刷新列表")
        refresh_btn.setCheckable(True)
        refresh_btn.setFixedSize(80, 30)
        refresh_btn.setStyleSheet(btn_style)
        refresh_btn.clicked.connect(self.init_gui)
        category_layout.addWidget(refresh_btn)

        float_layout.addWidget(category_frame)

        # 第二行：工具选择按钮
        plugins_frame = QFrame()
        plugins_frame.setFixedHeight(110)
        plugins_frame.setStyleSheet("border: 1px solid #ddd; border-radius: 5px; background: white;")
        plugins_layout = QHBoxLayout(plugins_frame)
        plugins_layout.setContentsMargins(5, 0, 5, 0)
        plugins_layout.setSpacing(0)

        plugin_scroll = HorizontalWheelScrollArea()
        plugin_scroll.setStyleSheet("border: none; background: transparent;")
        plugin_scroll.setFixedHeight(110)
        plugin_scroll.setWidgetResizable(True)
        plugin_scroll.setContentsMargins(0, 0, 0, 0)

        self.plugin_frame = QWidget()
        self.plugin_frame.setStyleSheet("border: none; background: transparent;")
        self.plugin_layout = QHBoxLayout(self.plugin_frame)
        self.plugin_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.plugin_layout.setContentsMargins(0, 0, 0, 0)
        self.plugin_layout.setSpacing(5)

        self.plugins_group = QButtonGroup(self)
        self.plugins_group.buttonClicked.connect(self.plugin_selected)
        plugin_scroll.setWidget(self.plugin_frame)
        plugins_layout.addWidget(plugin_scroll, 1)

        add_plugin_btn = ImageTextButton(
            text="添加工具",
            logo_image=(builtin_plugins_path / ".add_logo.png").as_posix(),
            tip_text="添加自定义的工具"
        )
        add_plugin_btn.clicked.connect(self.add_new_plugin)
        plugins_layout.addWidget(add_plugin_btn)

        float_layout.addWidget(plugins_frame)

        # 强制初始触发条高度（布局完成后约束）
        self.setFixedHeight(self.trigger_height)

        # 定位并显示
        x = (screen_geo.width() - self.panel_width) // 2
        self.setGeometry(x, 0, self.panel_width, self.trigger_height)
        self.show()

        # 插件管理器
        self.plugin_manager = PluginManager(
            builtin_plugins_dir=builtin_plugins_path.as_posix(),
            custom_plugins_dir=custom_plugins_path.as_posix(),
            logger=self.logger
        )

        # 加载插件
        QTimer.singleShot(100, self.init_gui)

    # === 动画 ===

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hide_timer.stop()
        self.start_expand()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hide_timer.start(1000)

    def start_expand(self):
        if self._target_height != self.expanded_height:
            self.is_visible = False
            self._target_height = self.expanded_height
            if not self.animation_timer.isActive():
                self.animation_timer.start()
            self.raise_()
            self.activateWindow()

    def start_shrink(self):
        if self._target_height != self.trigger_height:
            self.is_visible = True
            self._target_height = self.trigger_height
            if not self.animation_timer.isActive():
                self.animation_timer.start()

    def change_state(self):
        if self.is_visible:
            self.hide_timer.stop()
            self.start_expand()
        else:
            self.start_shrink()

    def animate_step(self):
        current = self.height()
        step = 12
        if current < self._target_height:
            self.setFixedHeight(min(current + step, self._target_height))
        elif current > self._target_height:
            self.setFixedHeight(max(current - step, self._target_height))
        else:
            self.animation_timer.stop()

    def _poll_cursor(self):
        """全局鼠标轮询：跨应用检测鼠标是否到达触发区"""
        cursor_y = QCursor.pos().y()
        cursor_x = QCursor.pos().x()
        if not (self.panel_width/2 < cursor_x < self.panel_width):
            return

        # 鼠标到达触发区且面板处于收缩状态 → 展开
        if cursor_y <= self.trigger_height:
            if (not self.is_visible) or (not self.expand_enable):
                return
            self.hide_timer.stop()
            if self.height() <= self.trigger_height:
                self.start_expand()

        # 鼠标远离展开面板 → 延迟收缩
        elif (cursor_y > self.expanded_height + 20 and self.height() > self.trigger_height
              and not self.is_visible):
            if not self.hide_timer.isActive():
                self.hide_timer.start(1000)

    # === 插件管理 ===

    def add_plugin_btn(self, plugin_object: PluginInfo, source: str):
        name = plugin_object.name
        self.plugin_source[name] = source
        self.logger.info(f"plugin_source '{name}' set source {source}")

        if name in self.plugin_buttons:
            self.logger.info(f"plugin_buttons '{name}' has created, remove")
            btn = self.plugin_buttons[name]
            btn.setParent(None)
            btn.deleteLater()
            self.plugin_buttons.pop(name)
        self.build_plugin_btn(plugin_object)

        if name not in self.plugin_category["ALL"]:
            self.plugin_category["ALL"].append(name)
            self.logger.info(f"plugin_category 'All' add plugin {name}")

        category = plugin_object.category
        if isinstance(category, str):
            plugin_category = [category]
        else:
            plugin_category = category
        for category in plugin_category:
            if category not in self.category_disable_list:
                if category not in self.plugin_category:
                    self.plugin_category[category] = []
                if name not in self.plugin_category[category]:
                    self.plugin_category[category].append(name)
                    self.logger.info(f"plugin_category '{category}' add plugin {name}")
                else:
                    self.logger.warning(f"plugin_category '{category}' has had plugin {name}, skip add")

    def build_plugin_btn(self, plugin: PluginInfo):
        name = plugin.name
        plugin_btn = ImageTextButton(name, logo_image=plugin.logo_path, tip_text=plugin.__str__())
        plugin_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        plugin_btn.customContextMenuRequested.connect(self.show_plugin_context_menu)
        self.plugin_buttons[name] = plugin_btn
        self.logger.info(f"plugin_buttons '{name}' connected btn {plugin_btn}")

    def init_gui(self):
        self.debug_widget.show()
        if not self.loading_dialog:
            self.loading_dialog = LoadingDialog(self)
        self.loading_dialog.show()
        self.executor.submit(self.executor_future)

    def executor_future(self):
        self.plugin_manager.discover_all_plugins()
        self.finish_signal.Signal.emit(True)

    @Slot(bool)
    def on_data_loaded(self, state):
        self.logger.info(f"[{state}]插件加载完成")
        if self._first_launch:
            self.load_favorites()
            self.plugin_manager.plugin_loaded.connect(self.plugin_update)
        self.debug_widget.hide()
        self.loading_dialog.close()

        # 首次启动：展开面板 5 秒后缩回
        if self._first_launch:
            self._first_launch = False
            self.start_expand()
            QTimer.singleShot(5000, self.start_shrink)

    def plugin_update(self, plugin_object: PluginInfo, source: str):
        self.add_plugin_btn(plugin_object, source)
        self.refresh_ui()

    def refresh_ui(self):
        for i in reversed(range(self.category_layout.count())):
            widget = self.category_layout.itemAt(i).widget()
            if widget:
                self.category_group.removeButton(widget)  # NOQA
                widget.setParent(None)
                widget.deleteLater()

        categories = sorted(self.plugin_category.keys())
        for i, category in enumerate(categories):
            btn = QPushButton(category)
            btn.setCheckable(True)
            btn.setFixedSize(80, 30)
            btn.setStyleSheet("""
                QPushButton { background: #e0e0e0; border: none; border-radius: 5px; font-weight: bold; }
                QPushButton:checked { background: #007acc; color: white; }
                QPushButton:hover { background: #d0d0d0; }
            """)
            self.category_group.addButton(btn, i)
            self.category_layout.addWidget(btn)
            if i == 0:
                btn.setChecked(True)
                self.current_category = category
                self.show_category_plugins(category)
        self.logger.info("refresh ui")

    def on_category_changed(self, button):
        category = button.text()
        self.logger.info(f"user changed category from {self.current_category} to {category}")
        self.current_category = category
        self.show_category_plugins(category)

    def show_category_plugins(self, category):
        while self.plugin_layout.count() > 0:
            item = self.plugin_layout.takeAt(0)
            if item.widget():
                self.plugins_group.removeButton(item.widget())  # NOQA
                item.widget().setParent(None)

        if category in self.plugin_category.keys():
            plugins = sorted(self.plugin_category[category])
            for plugin_name in plugins:
                plugin_btn = self.plugin_buttons[plugin_name]
                self.plugins_group.addButton(plugin_btn)
                self.plugin_layout.addWidget(plugin_btn)

    def plugin_selected(self, button: ImageTextButton):
        self.on_plugin_selected(button.btn_name)

    def on_plugin_selected(self, plugin_name):
        """打开插件为独立窗口（单例模式）"""
        self.logger.info(f"工具被选择: {plugin_name}")
        try:
            if (not self.no_limit_widget) and plugin_name in self.plugin_windows:
                self.logger.info(f"{plugin_name} has been opened, raise the window.")
                window = self.plugin_windows[plugin_name]
                # 最小化状态先恢复
                if window.isMinimized():
                    window.setWindowState(window.windowState() & ~Qt.WindowState.WindowMinimized)
                window.show()
                window.raise_()
                window.activateWindow()
                return

            source = self.plugin_source[plugin_name]
            plugin = self.plugin_manager.get_plugin(plugin_name, source)
            self.logger.info(f"load {plugin.name} plugin")

            plugin_log = create_logger(
                name=plugin_name, level=logging.DEBUG,
                log_path=self.data_path / "script_log"
            )
            window = plugin.handler(
                name=plugin.name,
                version=plugin.version,
                data_path=self.data_path / "data" / plugin_name,
                logger=plugin_log,
                **plugin.parameters
            )

            window.name = plugin_name

            if not self.no_limit_widget:
                self.plugin_windows[plugin_name] = window
            self.all_plugin_windows.append(window)

            def on_window_closed(obj=None):
                if not self.no_limit_widget:
                    self.plugin_windows.pop(plugin_name, None)
                if window in self.all_plugin_windows:
                    self.all_plugin_windows.remove(window)
                self.logger.info(f"{plugin_name}窗口关闭,当前还有{len(self.all_plugin_windows)}个窗口开着")
                if len(self.all_plugin_windows) <= 0:
                    self.start_expand()

            window.destroyed.connect(on_window_closed)
            window.setWindowIcon(QIcon(plugin.logo_path))
            window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            window.show()

            screen_geometry = QApplication.primaryScreen().availableGeometry()
            win_geo = window.frameGeometry()
            win_geo.moveCenter(screen_geometry.center())
            window.move(win_geo.topLeft())
            self.logger.info(f"plugin '{plugin_name}' opened as standalone window")

            self.start_shrink()
        except Exception as e:
            self.logger.exception(traceback.format_exc())
            QMessageBox.warning(self, "失败", f"工具 '{plugin_name}' 加载失败!\n{e}")

    def show_plugin_context_menu(self, pos):
        plugin_btn = self.sender()
        if not plugin_btn:
            return
        plugin_name = getattr(plugin_btn, "btn_name")

        menu = QMenu(self)
        set_menu = menu.addMenu("添加到分类")
        move_menu = menu.addMenu("移动到分类")
        for category in self.plugin_category.keys():
            if category != "ALL" and category != self.current_category:
                action = set_menu.addAction(category)
                action.triggered.connect(lambda checked, c=category, t=plugin_name: self.set_plugin_to_category(t, c))
                action = move_menu.addAction(category)
                action.triggered.connect(
                    lambda checked, oc=self.current_category, nc=category, t=plugin_name:
                    self.move_plugin_to_category(t, oc, nc)
                )
        delete_action = menu.addAction("删除工具")
        delete_action.triggered.connect(lambda: self.delete_plugin(plugin_name))
        global_pos = plugin_btn.mapToGlobal(pos)
        menu.exec(global_pos)

    def set_plugin_to_category(self, plugin_name, target_category):
        if target_category in self.plugin_category.keys():
            if plugin_name in self.plugin_category[target_category]:
                return
            self.plugin_category[target_category].append(plugin_name)
            self.plugin_category[target_category].sort()
            self.refresh_ui()
            _ = self.save_favorites()
            self.logger.info(f"user add plugin '{plugin_name}' to {target_category}")
            QMessageBox.information(self, "成功", f"工具 '{plugin_name}' 已添加到 '{target_category}' 分类!")

    def move_plugin_to_category(self, plugin_name, current_category, target_category):
        if current_category != "ALL":
            if current_category in self.plugin_category.keys():
                if plugin_name in self.plugin_category[current_category]:
                    index = self.plugin_category[current_category].index(plugin_name)
                    self.plugin_category[current_category].pop(index)
                    self.logger.info(f"remove category {current_category} {index} plugin {plugin_name}")
                if len(self.plugin_category[current_category]) == 0:
                    self.plugin_category.pop(current_category)
        if target_category in self.plugin_category.keys():
            if plugin_name not in self.plugin_category[target_category]:
                self.plugin_category[target_category].append(plugin_name)
                self.plugin_category[target_category].sort()
        self.refresh_ui()
        _ = self.save_favorites()
        self.logger.info(f"user move plugin '{plugin_name}' to {target_category}")
        QMessageBox.information(self, "成功", f"工具 '{plugin_name}' 已移动到 '{target_category}' 分类!")

    def delete_plugin(self, plugin_name):
        reply = QMessageBox.question(self, "确认删除", f"确定要删除工具 '{plugin_name}' 吗？")
        if reply == QMessageBox.StandardButton.Yes:
            if plugin_name in self.plugin_category[self.current_category]:
                index = self.plugin_category[self.current_category].index(plugin_name)
                self.plugin_category[self.current_category].pop(index)
            if self.current_category == "ALL":
                for category, plugins in self.plugin_category.items():
                    if plugin_name in plugins:
                        index = self.plugin_category[category].index(plugin_name)
                        self.plugin_category[category].pop(index)
                self.plugin_disable_list.append(plugin_name)
            self.logger.info(f"user remove plugin '{plugin_name}' on {self.current_category}")
            QMessageBox.information(self, "成功", f"工具 '{plugin_name}' 删除成功!")
            _ = self.save_favorites()
            self.refresh_ui()

    def get_all_plugins(self):
        all_plugins = []
        for plugins in self.plugin_category.values():
            all_plugins.extend(plugins)
        return set(all_plugins)

    def add_new_plugin(self):
        new_plugin_dialog = NewPluginDialog(self)
        new_plugin_dialog.exec()
        self.refresh_ui()

    # === 配置持久化 ===

    def reset_favorites(self):
        if self.favorites_file.exists():
            self.favorites_file.unlink()
            self.logger.info("remove user favorites file.")
        for btn in self.plugin_buttons.values():
            btn.deleteLater()
        self.plugin_buttons = {}
        self.plugin_category = {"ALL": []}
        for plugin_object, source in self.plugin_manager.get_all_plugins():
            self.add_plugin_btn(plugin_object, source)
        self.logger.info("reset favorites successfully.")
        self.refresh_ui()

    @check_error
    def load_favorites(self):
        structure = {}
        favorites_exists = self.favorites_file.exists()

        if favorites_exists:
            self.logger.info("加载用户配置")
            self.plugin_category = {"ALL": []}
            config = read_data_from_yaml(self.favorites_file)
            self.expand_enable = config.get("auto_expand", True)
            self.no_limit_widget = config.get("limit widget", False)
            self.default_plugin = config.get("default_plugin", "")
            structure = config.get("plugins_structure", {})
            self.category_disable_list = config.get("category_disable", [])
            self.plugin_disable_list = config.get("plugins_disable", [])

        update = False
        self.logger.info("=" * 50)
        for plugin_object, source in self.plugin_manager.get_all_plugins():
            name = plugin_object.name
            category = plugin_object.category
            self.logger.info(f"load plugin {name} info : category-{category}, source-{source}")
            if source == "custom" and name in self.plugin_source:
                self.logger.info(f"plugin '{name}' change source {self.plugin_source[name]} to  {source}")
                self.plugin_source[name] = source
            for user_category, plugins in structure.items():
                if name not in plugins:
                    continue
                if name in self.plugin_category["ALL"]:
                    if user_category not in self.plugin_category:
                        self.plugin_category[user_category] = []
                    if name not in self.plugin_category[user_category]:
                        self.logger.info(f"plugin '{name}' add to  {user_category}")
                        self.plugin_category[user_category].append(name)
                    else:
                        self.logger.info(f"{user_category} really at plugin '{name}', skip.")
                else:
                    plugin_object.category = user_category
                    self.logger.info(f"plugin '{name}' change category {category} to  {plugin_object.category}")
                    self.add_plugin_btn(plugin_object, source)
            if name not in self.plugin_category["ALL"] and name not in self.plugin_disable_list:
                update = True
                self.logger.info(f"plugin {name} is new plugin, add plugin")
                self.add_plugin_btn(plugin_object, source)
            self.logger.info("=" * 50)
        if favorites_exists and update:
            self.logger.info(f"found new plugin, update favorites...")
            self.save_favorites()
        self.refresh_ui()

        if self.default_plugin and self.default_plugin in self.get_all_plugins():
            QTimer.singleShot(100, lambda: self.on_plugin_selected(self.default_plugin))

    def save_favorites(self) -> bool:
        try:
            config = {
                "auto_expand": self.expand_enable,
                "limit widget": self.no_limit_widget,
                "default_plugin": self.default_plugin,
                "plugins_structure": {},
                "category_disable": [],
                "plugins_disable": [],
            }
            for category, plugins in self.plugin_category.items():
                if category == "ALL":
                    continue
                config["plugins_structure"][category] = plugins
            config["category_disable"] = self.category_disable_list
            config["plugins_disable"] = self.plugin_disable_list
            save_data_to_yaml(config, self.favorites_file)
            self.logger.info("save user favorite successfully.")
            return True
        except Exception as e:
            self.logger.error(str(e))
            return False
