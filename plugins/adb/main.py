import logging
import os
import subprocess
import sys
import threading
import traceback
from logging import Logger
from os import PathLike
from pathlib import Path
from typing import Optional, Union
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QListWidget, QTreeWidget, QTreeWidgetItem,
    QLabel, QComboBox, QLineEdit, QTabWidget, QMessageBox,
    QFileDialog, QDialog, QDialogButtonBox, QFrame,
    QToolButton, QMenu, QCompleter
)
from PySide6.QtCore import QThread, Signal, QSettings, Qt, QStringListModel, QPoint
from PySide6.QtGui import QFont, QTextCursor, QCursor

from lib.customlog import create_logger


class ADBPathDialog(QDialog):
    """ADB路径设置对话框"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger: logging.Logger = getattr(parent, "logger", None)
        self.setWindowTitle("ADB路径设置")
        self.setModal(True)
        self.setMinimumWidth(500)

        layout = QVBoxLayout(self)

        # 说明标签
        info_label = QLabel(
            "请选择ADB可执行文件路径。\n"
            "如果系统已配置环境变量，程序会自动检测。\n"
            "如果未配置环境变量，请手动选择ADB文件位置。"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        # 路径选择区域
        path_layout = QHBoxLayout()

        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("选择adb可执行文件路径...")
        self.path_input.setReadOnly(True)

        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self.browse_adb_path)

        path_layout.addWidget(self.path_input)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 检测按钮
        detect_layout = QHBoxLayout()

        self.detect_btn = QPushButton("自动检测")
        self.detect_btn.clicked.connect(self.auto_detect_adb)

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_adb)

        detect_layout.addWidget(self.detect_btn)
        detect_layout.addWidget(self.test_btn)
        detect_layout.addStretch()
        layout.addLayout(detect_layout)

        # 状态显示
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        # 按钮
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        # 加载已保存的配置
        self.load_settings()

    def browse_adb_path(self):
        """浏览选择 ADB 文件"""
        if sys.platform == "win32":
            file_filter = "可执行文件 (*.exe);;所有文件 (*.*)"
        else:
            file_filter = "可执行文件 (*);;所有文件 (*.*)"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择 ADB 可执行文件",
            "",
            file_filter
        )

        if file_path:
            self.path_input.setText(file_path)
            self.status_label.setText(f"已选择: {file_path}")
            self.status_label.setStyleSheet("color: green;")
            if self.logger:
                self.logger.info(f"user choose adb file: {file_path}")

    def auto_detect_adb(self):
        """自动检测ADB"""
        self.status_label.setText("正在检测ADB...")
        self.status_label.setStyleSheet("color: blue;")
        if self.logger:
            self.logger.info("正在检测ADB...")

        # 尝试检测系统环境变量中的adb
        try:
            command = "where adb" if sys.platform == "win32" else "which adb"
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if self.logger:
                self.logger.info(f"send command: {command}")
                self.logger.info(f"return result: {result.stdout}")

            if result.returncode == 0 and result.stdout.strip():
                adb_path = result.stdout.strip().split('\n')[0]
                self.path_input.setText(adb_path)
                self.status_label.setText(f"系统环境变量中找到ADB: {adb_path}")
                self.status_label.setStyleSheet("color: green;")
                return
        except Exception as e:
            if self.logger:
                self.logger.warning(str(e))

        # 尝试常见路径
        if sys.platform == "win32":
            common_paths = [
                "adb.exe",
                r"platform-tools\adb.exe",
                r"C:\Program Files\Android\platform-tools\adb.exe",
                r"C:\Program Files (x86)\Android\platform-tools\adb.exe",
            ]
        else:
            # macOS / Linux
            common_paths = [
                "adb",
                "platform-tools/adb",
                "/usr/bin/adb",
                "/usr/local/bin/adb",
                "/opt/homebrew/bin/adb",  # Apple Silicon Mac
                "~/Android/Sdk/platform-tools/adb",
            ]
        for path in common_paths:
            expanded_path = os.path.expanduser(path)
            if os.path.isfile(expanded_path) and os.access(expanded_path, os.X_OK):
                self.path_input.setText(expanded_path)
                self.status_label.setText(f"在常见路径中找到ADB: {expanded_path}")
                self.status_label.setStyleSheet("color: green;")
                if self.logger:
                    self.logger.info(f"在常见路径中找到ADB: {expanded_path}")
                return

        self.status_label.setText("未找到ADB，请手动选择")
        self.status_label.setStyleSheet("color: red;")
        if self.logger:
            self.logger.info("未找到ADB")

    def test_adb(self):
        """测试ADB连接"""
        adb_path = self.path_input.text().strip()
        if not adb_path:
            QMessageBox.warning(self, "警告", "请先选择ADB路径")
            return

        self.status_label.setText("正在测试ADB...")
        self.status_label.setStyleSheet("color: blue;")

        try:
            result = subprocess.run(
                f'"{adb_path}" version',
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            if result.returncode == 0:
                version_info = result.stdout.strip()
                self.status_label.setText(f"ADB测试成功: {version_info}")
                self.status_label.setStyleSheet("color: green;")
            else:
                self.status_label.setText(f"ADB测试失败: {result.stderr}")
                self.status_label.setStyleSheet("color: red;")
        except Exception as e:
            if self.logger:
                self.logger.info(f"ADB测试失败: {str(e)}")
            self.status_label.setText(f"ADB测试失败: {str(e)}")
            self.status_label.setStyleSheet("color: red;")

    def load_settings(self):
        """加载已保存的设置"""
        settings = QSettings("Endfield", "ADBDebugger")
        saved_path = settings.value("adb_path", "")
        if saved_path:
            self.path_input.setText(str(saved_path))
            self.status_label.setText(f"已加载保存的配置: {saved_path}")
            self.status_label.setStyleSheet("color: green;")
            if self.logger:
                self.logger.info(f"已加载保存的配置: {saved_path}")

    def get_adb_path(self):
        """获取ADB路径"""
        return self.path_input.text().strip()


class ADBWorker(QThread):
    """ADB命令执行工作线程"""
    output_received = Signal(str)
    error_received = Signal(str)
    finished = Signal(int)

    def __init__(self, adb_path, command, timeout=30):
        super().__init__()
        self.adb_path = adb_path
        self.command = command
        self.timeout = timeout
        self.process = None

    def run(self):
        try:
            self.process = subprocess.Popen(
                self.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                bufsize=1
            )

            # 读取输出
            for line in iter(self.process.stdout.readline, ''):
                if line:
                    self.output_received.emit(line.rstrip())

            # 读取错误
            for line in iter(self.process.stderr.readline, ''):
                if line:
                    self.error_received.emit(line.rstrip())

            self.process.stdout.close()
            self.process.stderr.close()
            return_code = self.process.wait(timeout=self.timeout)
            self.finished.emit(return_code)

        except subprocess.TimeoutExpired:
            self.error_received.emit("命令执行超时")
            if self.process:
                self.process.kill()
            self.finished.emit(-1)
        except Exception as e:
            self.error_received.emit(f"执行错误: {str(e)}")
            self.finished.emit(-1)

    def stop(self):
        if self.process:
            self.process.kill()


class LogMonitor(QThread):
    """日志监控线程"""
    log_received = Signal(str)

    def __init__(self, adb_path, device_serial=None, log_level="V"):
        super().__init__()
        self.adb_path = adb_path
        self.device_serial = device_serial
        self.log_level = log_level
        self.running = True
        self.process = None

    def run(self):
        cmd = f'"{self.adb_path}" logcat'
        if self.device_serial:
            cmd = f'"{self.adb_path}" -s {self.device_serial} logcat'

        # 添加日志级别过滤
        level_map = {"V": "*:V", "D": "*:D", "I": "*:I", "W": "*:W", "E": "*:E"}
        if self.log_level in level_map:
            cmd += f" {level_map[self.log_level]}"

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True,
                text=True,
                bufsize=1
            )

            while self.running:
                line = self.process.stdout.readline()
                if line:
                    self.log_received.emit(line.rstrip())

        except Exception as e:
            self.log_received.emit(f"日志监控错误: {str(e)}")
        finally:
            if self.process:
                self.process.kill()

    def stop(self):
        self.running = False
        if self.process:
            self.process.kill()


class MainWindow(QMainWindow):
    def __init__(
            self,
            name: str,
            version: str = "1.0.0",
            logger: Optional[Logger] = None,
            data_path: Union[PathLike[str], str, None] = None,
            *args,
            **kwargs,
    ):
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

        self.devices = []
        self.current_device = None
        self.log_monitor = None
        self.worker = None
        self.adb_path = self.load_adb_path()
        self.command_history = self.load_command_history()
        self.history_max_count = 100  # 历史记录最大保存数量

        self.setWindowTitle(f"{name} V{version}")
        self.resize(800, 600)

        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # 工具栏
        toolbar_layout = QHBoxLayout()

        # ADB路径显示和设置
        self.adb_path_label = QLabel(f"ADB: {self.adb_path if self.adb_path else '未设置'}")
        self.adb_path_label.setStyleSheet("color: gray; font-size: 10px;")

        adb_settings_btn = QPushButton("ADB设置")
        adb_settings_btn.clicked.connect(self.show_adb_settings)

        toolbar_layout.addWidget(self.adb_path_label)
        toolbar_layout.addWidget(adb_settings_btn)

        # 使用QFrame作为分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setFixedWidth(2)
        toolbar_layout.addWidget(separator)

        # 设备选择
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(200)
        self.device_combo.currentIndexChanged.connect(self.on_device_changed)

        # 刷新设备按钮
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.clicked.connect(self.refresh_devices)

        # 连接设备按钮
        connect_btn = QPushButton("连接设备")
        connect_btn.clicked.connect(self.connect_device)

        # 断开设备按钮
        disconnect_btn = QPushButton("断开设备")
        disconnect_btn.clicked.connect(self.disconnect_device)

        toolbar_layout.addWidget(QLabel("设备:"))
        toolbar_layout.addWidget(self.device_combo)
        toolbar_layout.addWidget(refresh_btn)
        toolbar_layout.addWidget(connect_btn)
        toolbar_layout.addWidget(disconnect_btn)
        toolbar_layout.addStretch()

        main_layout.addLayout(toolbar_layout)

        # 创建标签页
        self.tab_widget = QTabWidget()

        # 命令标签页
        self.command_tab = QWidget()
        self.command_layout = QVBoxLayout(self.command_tab)

        # 命令输入区域
        input_layout = QHBoxLayout()
        self.command_input = QLineEdit()
        self.command_input.setPlaceholderText("输入ADB命令（可不需要adb前缀）")
        self.command_input.returnPressed.connect(self.execute_command)

        # 添加历史指令下拉选择
        self.history_menu_btn = QToolButton()
        self.history_menu_btn.setText("历史")
        self.history_menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.history_menu_btn.setToolTip("查看历史指令")
        self.history_menu = QMenu(self)
        self.history_menu_btn.setMenu(self.history_menu)
        self.history_menu.aboutToShow.connect(self.update_history_menu)

        # 自动补全模型
        self.command_completer_model = QStringListModel(self.command_history, self)
        self.command_completer = QCompleter(self.command_completer_model, self)
        self.command_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.command_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.command_completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.command_input.setCompleter(self.command_completer)

        execute_btn = QPushButton("执行")
        execute_btn.clicked.connect(self.execute_command)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(lambda: self.command_output.clear())

        input_layout.addWidget(self.command_input)
        input_layout.addWidget(self.history_menu_btn)
        input_layout.addWidget(execute_btn)
        input_layout.addWidget(clear_btn)

        self.command_layout.addLayout(input_layout)

        # 常用命令快捷按钮
        quick_commands = QHBoxLayout()
        commands = [
            ("设备信息", "shell getprop"),
            ("CPU信息", "shell cat /proc/cpuinfo"),
            ("内存信息", "shell cat /proc/meminfo"),
            ("网络信息", "shell ifconfig"),
            ("进程列表", "shell ps"),
            ("安装应用", "install"),
        ]

        for name, cmd in commands:
            btn = QPushButton(name)
            btn.clicked.connect(lambda checked, c=cmd: self.quick_command(c))
            quick_commands.addWidget(btn)

        self.command_layout.addLayout(quick_commands)

        # 输出区域
        self.command_output = QTextEdit()
        self.command_output.setReadOnly(True)
        self.command_output.setFont(QFont("Consolas", 10))
        self.command_layout.addWidget(self.command_output)

        # 日志标签页
        self.log_tab = QWidget()
        self.log_layout = QVBoxLayout(self.log_tab)

        # 日志控制区域
        control_layout = QHBoxLayout()

        # 日志级别选择
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["V", "D", "I", "W", "E"])
        self.log_level_combo.setCurrentText("V")

        # 过滤输入
        self.log_filter = QLineEdit()
        self.log_filter.setPlaceholderText("过滤关键词")

        # 控制按钮
        self.start_log_btn = QPushButton("开始监控")
        self.start_log_btn.clicked.connect(self.toggle_log_monitor)

        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.clicked.connect(lambda: self.log_output.clear())

        control_layout.addWidget(QLabel("日志级别:"))
        control_layout.addWidget(self.log_level_combo)
        control_layout.addWidget(QLabel("过滤:"))
        control_layout.addWidget(self.log_filter)
        control_layout.addWidget(self.start_log_btn)
        control_layout.addWidget(clear_log_btn)
        control_layout.addStretch()

        self.log_layout.addLayout(control_layout)

        # 日志输出
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFont(QFont("Consolas", 10))
        self.log_layout.addWidget(self.log_output)

        # 文件浏览器标签页
        self.file_tab = QWidget()
        self.file_layout = QVBoxLayout(self.file_tab)

        # 路径导航
        nav_layout = QHBoxLayout()
        self.path_input = QLineEdit("/")
        self.path_input.returnPressed.connect(self.browse_files)

        browse_btn = QPushButton("浏览")
        browse_btn.clicked.connect(self.browse_files)

        nav_layout.addWidget(QLabel("路径:"))
        nav_layout.addWidget(self.path_input)
        nav_layout.addWidget(browse_btn)

        self.file_layout.addLayout(nav_layout)

        # 文件树
        self.file_tree = QTreeWidget()
        self.file_tree.setHeaderLabels(["名称", "大小", "权限", "修改时间"])
        self.file_tree.setColumnWidth(0, 300)
        self.file_tree.setColumnWidth(1, 100)
        self.file_tree.setColumnWidth(2, 100)
        self.file_tree.itemDoubleClicked.connect(self.on_file_double_click)

        self.file_layout.addWidget(self.file_tree)

        # 操作按钮
        btn_layout = QHBoxLayout()
        pull_btn = QPushButton("拉取文件")
        pull_btn.clicked.connect(self.pull_file)

        push_btn = QPushButton("推送文件")
        push_btn.clicked.connect(self.push_file)

        delete_btn = QPushButton("删除文件")
        delete_btn.clicked.connect(self.delete_file)

        btn_layout.addWidget(pull_btn)
        btn_layout.addWidget(push_btn)
        btn_layout.addWidget(delete_btn)
        btn_layout.addStretch()

        self.file_layout.addLayout(btn_layout)

        # 应用管理标签页
        self.app_tab = QWidget()
        self.app_layout = QVBoxLayout(self.app_tab)

        # 应用列表
        self.app_list = QListWidget()
        self.app_layout.addWidget(self.app_list)

        # 操作按钮
        btn_layout = QHBoxLayout()
        refresh_apps_btn = QPushButton("刷新应用列表")
        refresh_apps_btn.clicked.connect(self.refresh_apps)

        uninstall_btn = QPushButton("卸载应用")
        uninstall_btn.clicked.connect(self.uninstall_app)

        clear_data_btn = QPushButton("清除数据")
        clear_data_btn.clicked.connect(self.clear_app_data)

        btn_layout.addWidget(refresh_apps_btn)
        btn_layout.addWidget(uninstall_btn)
        btn_layout.addWidget(clear_data_btn)
        btn_layout.addStretch()

        self.app_layout.addLayout(btn_layout)

        self.tab_widget.addTab(self.command_tab, "命令")
        self.tab_widget.addTab(self.log_tab, "日志")
        self.tab_widget.addTab(self.file_tab, "文件浏览器")
        self.tab_widget.addTab(self.app_tab, "应用管理")
        main_layout.addWidget(self.tab_widget)

        # 状态栏
        self.status_label = QLabel("就绪")
        self.statusBar().addWidget(self.status_label)

        # 初始化设备列表
        self.refresh_devices()

    def load_adb_path(self):
        """加载保存的ADB路径"""
        settings = QSettings("Endfield", "ADBDebugger")
        saved_path = settings.value("adb_path", "")

        if saved_path and os.path.isfile(str(saved_path)):
            self.logger.info(f"加载adb路径{saved_path}")
            return saved_path

        # 尝试从环境变量检测
        try:
            result = subprocess.run(
                "where adb" if sys.platform == "win32" else "which adb",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split('\n')[0]
        except Exception as e:
            self.logger.warning(str(e))

        return ""

    def save_adb_path(self, path):
        """保存ADB路径"""
        settings = QSettings("Endfield", "ADBDebugger")
        settings.setValue("adb_path", path)
        self.adb_path = path
        self.logger.info(f"已保存配置: {path}")

    def show_adb_settings(self):
        """显示ADB设置对话框"""
        dialog = ADBPathDialog(self)
        if dialog.exec():
            adb_path = dialog.get_adb_path()
            if adb_path:
                self.logger.info(f"ADB路径已设置: {adb_path}")
                self.save_adb_path(adb_path)
                self.status_label.setText("ADB路径已设置")
                self.refresh_devices()
            else:
                QMessageBox.warning(self, "警告", "未设置ADB路径，部分功能可能无法使用")

    def refresh_devices(self):
        """刷新设备列表"""
        if not self.adb_path:
            self.status_label.setText("请先设置ADB路径")
            return

        self.device_combo.clear()
        self.devices = []

        try:
            result = subprocess.run(
                f'"{self.adb_path}" devices',
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )

            lines = result.stdout.strip().split('\n')
            for line in lines[1:]:  # 跳过第一行 "List of devices attached"
                if line.strip() and '\tdevice' in line:
                    serial = line.split('\t')[0]
                    self.devices.append(serial)
                    self.device_combo.addItem(serial)

            if not self.devices:
                self.device_combo.addItem("无设备连接")
                self.status_label.setText("未检测到设备")
            else:
                self.status_label.setText(f"已检测到 {len(self.devices)} 个设备")

        except Exception as e:
            self.logger.error(f"设备检测失败: {str(e)}")
            self.logger.error(traceback.format_exc())
            self.status_label.setText(f"设备检测失败: {str(e)}")

    def on_device_changed(self, index):
        """设备选择改变"""
        if 0 <= index < len(self.devices):
            self.current_device = self.devices[index]
            self.status_label.setText(f"当前设备: {self.current_device}")
        else:
            self.current_device = None

    def connect_device(self):
        """连接设备"""
        # 这里可以添加IP地址输入对话框
        QMessageBox.information(self, "连接设备", "请输入设备IP地址")

    def disconnect_device(self):
        """断开设备"""
        if self.current_device:
            self.execute_adb_command(f"disconnect {self.current_device}")
            self.refresh_devices()

    def execute_command(self):
        """执行命令"""
        command = self.command_input.text().strip()
        if not command:
            return

        self.command_output.append(f"\n> {command}")
        self.execute_adb_command(command)
        self.add_command_history(command)
        self.command_input.clear()

    def load_command_history(self):
        """加载历史指令列表"""
        settings = QSettings("Endfield", "ADBDebugger")
        history = settings.value("command_history", [])
        if history is None:
            return []
        if isinstance(history, str):
            return [history]
        return [str(item) for item in history]

    def save_command_history(self):
        """保存历史指令列表"""
        settings = QSettings("Endfield", "ADBDebugger")
        settings.setValue("command_history", self.command_history)

    def add_command_history(self, command):
        """添加一条历史指令（去重、最新置顶、限制数量）"""
        if not command:
            return
        if command in self.command_history:
            self.command_history.remove(command)
        self.command_history.insert(0, command)
        if len(self.command_history) > self.history_max_count:
            self.command_history = self.command_history[:self.history_max_count]
        self.save_command_history()
        if self.command_completer_model:
            self.command_completer_model.setStringList(self.command_history)
        self.logger.info(f"已记录指令历史: {command}")

    def update_history_menu(self):
        """在弹出菜单前刷新历史指令条目"""
        self.history_menu.clear()
        if not self.command_history:
            action = self.history_menu.addAction("(暂无历史指令)")
            action.setEnabled(False)
            return

        for cmd in self.command_history:
            display = cmd if len(cmd) <= 60 else cmd[:57] + "..."
            action = self.history_menu.addAction(display)
            action.setToolTip(cmd)
            action.triggered.connect(lambda checked=False, c=cmd: self.use_history_command(c))

        self.history_menu.addSeparator()
        clear_action = self.history_menu.addAction("清空历史")
        clear_action.triggered.connect(self.clear_command_history)

    def use_history_command(self, command):
        """从历史菜单选择一条指令填入输入框"""
        self.command_input.setText(command)
        self.command_input.setFocus()
        self.command_input.setCursorPosition(len(command))

    def clear_command_history(self):
        """清空全部历史指令"""
        self.command_history = []
        self.save_command_history()
        if self.command_completer_model:
            self.command_completer_model.setStringList([])
        self.logger.info("已清空指令历史")

    def quick_command(self, command):
        """快速命令"""
        self.command_input.setText(command)
        self.execute_command()

    def execute_adb_command(self, command, output_widget=None):
        """执行ADB命令"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        if output_widget is None:
            output_widget = self.command_output
        if command.startswith("adb"):
            command = command.replace("adb", "")
        # 构建完整命令
        full_command = f'"{self.adb_path}" {command}'
        if self.current_device and not command.startswith("devices"):
            full_command = f'"{self.adb_path}" -s {self.current_device} {command}'

        def run_command():
            try:
                result = subprocess.run(
                    full_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30
                )

                if result.stdout:
                    output_widget.append(result.stdout)
                if result.stderr:
                    output_widget.append(f"错误: {result.stderr}")

            except subprocess.TimeoutExpired:
                output_widget.append("命令执行超时")
            except Exception as e:
                output_widget.append(f"执行错误: {str(e)}")

        # 在新线程中执行
        thread = threading.Thread(target=run_command)
        thread.daemon = True
        thread.start()

    def toggle_log_monitor(self):
        """切换日志监控"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        if self.log_monitor and self.log_monitor.isRunning():
            self.log_monitor.stop()
            self.log_monitor.wait()
            self.start_log_btn.setText("开始监控")
            self.status_label.setText("日志监控已停止")
        else:
            self.log_monitor = LogMonitor(
                adb_path=self.adb_path,
                device_serial=self.current_device,
                log_level=self.log_level_combo.currentText()
            )
            self.log_monitor.log_received.connect(self.on_log_received)
            self.log_monitor.start()
            self.start_log_btn.setText("停止监控")
            self.status_label.setText("日志监控中...")

    def on_log_received(self, log_line):
        """接收日志"""
        # 过滤
        filter_text = self.log_filter.text()
        if filter_text and filter_text not in log_line:
            return

        # 添加时间戳
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        formatted_log = f"[{timestamp}] {log_line}"

        self.log_output.append(formatted_log)

        # 自动滚动到底部
        cursor = self.log_output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_output.setTextCursor(cursor)

    def browse_files(self):
        """浏览文件"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        path = self.path_input.text().strip()
        if not path:
            path = "/"

        self.file_tree.clear()

        command = f'"{self.adb_path}" shell ls -la {path}'
        if self.current_device:
            command = f'"{self.adb_path}" -s {self.current_device} shell ls -la {path}'

        def parse_and_display():
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.stdout:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if line.strip():
                            parts = line.split()
                            if len(parts) >= 8:
                                permissions = parts[0]
                                size = parts[4]
                                date = f"{parts[5]} {parts[6]} {parts[7]}"
                                name = ' '.join(parts[8:])

                                item = QTreeWidgetItem(self.file_tree)
                                item.setText(0, name)
                                item.setText(1, size)
                                item.setText(2, permissions)
                                item.setText(3, date)

                                # 如果是目录，添加展开标记
                                if permissions.startswith('d'):
                                    item.setChildIndicatorPolicy(
                                        QTreeWidgetItem.ChildIndicatorPolicy.ShowIndicator
                                    )

            except Exception as e:
                self.status_label.setText(f"文件浏览错误: {str(e)}")

        thread = threading.Thread(target=parse_and_display)
        thread.daemon = True
        thread.start()

    def on_file_double_click(self, item, column):  # NOQA
        """文件双击事件"""
        name = item.text(0)
        permissions = item.text(2)

        current_path = self.path_input.text().strip()
        if current_path.endswith('/'):
            new_path = f"{current_path}{name}"
        else:
            new_path = f"{current_path}/{name}"

        # 如果是目录，进入该目录
        if permissions.startswith('d'):
            self.path_input.setText(new_path)
            self.browse_files()

    def pull_file(self):
        """拉取文件"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        selected = self.file_tree.currentItem()
        if selected:
            file_name = selected.text(0)
            path = self.path_input.text().strip()
            if path.endswith('/'):
                full_path = f"{path}{file_name}"
            else:
                full_path = f"{path}/{file_name}"

            self.execute_adb_command(f"pull {full_path}")
            self.status_label.setText(f"正在拉取: {full_path}")

    def push_file(self):
        """推送文件"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        QMessageBox.information(self, "推送文件", "请选择要推送的文件")

    def delete_file(self):
        """删除文件"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        selected = self.file_tree.currentItem()
        if selected:
            file_name = selected.text(0)
            path = self.path_input.text().strip()
            if path.endswith('/'):
                full_path = f"{path}{file_name}"
            else:
                full_path = f"{path}/{file_name}"

            reply = QMessageBox.question(
                self, "确认删除",
                f"确定要删除 {full_path} 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.execute_adb_command(f"shell rm -rf {full_path}")
                self.browse_files()

    def refresh_apps(self):
        """刷新应用列表"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        self.app_list.clear()

        command = f'"{self.adb_path}" shell pm list packages -3'
        if self.current_device:
            command = f'"{self.adb_path}" -s {self.current_device} shell pm list packages -3'

        def get_apps():
            try:
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=10
                )

                if result.stdout:
                    packages = result.stdout.strip().split('\n')
                    for package in packages:
                        if package.startswith("package:"):
                            app_name = package[8:]  # 移除 "package:" 前缀
                            self.app_list.addItem(app_name)

            except Exception as e:
                self.status_label.setText(f"获取应用列表错误: {str(e)}")

        thread = threading.Thread(target=get_apps)
        thread.daemon = True
        thread.start()

    def uninstall_app(self):
        """卸载应用"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        selected = self.app_list.currentItem()
        if selected:
            package_name = selected.text()

            reply = QMessageBox.question(
                self, "确认卸载",
                f"确定要卸载 {package_name} 吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.execute_adb_command(f"uninstall {package_name}")
                self.refresh_apps()

    def clear_app_data(self):
        """清除应用数据"""
        if not self.adb_path:
            QMessageBox.warning(self, "警告", "请先设置ADB路径")
            return

        selected = self.app_list.currentItem()
        if selected:
            package_name = selected.text()

            reply = QMessageBox.question(
                self, "确认清除",
                f"确定要清除 {package_name} 的数据吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.Yes:
                self.execute_adb_command(f"shell pm clear {package_name}")

    def deleteLater(self, /):
        if self.log_monitor and self.log_monitor.isRunning():
            self.log_monitor.stop()
            self.log_monitor.wait()

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        if self.log_monitor and self.log_monitor.isRunning():
            self.log_monitor.stop()
            self.log_monitor.wait()

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="example")
    window.show()
    sys.exit(app.exec())
