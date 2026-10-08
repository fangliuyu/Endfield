import logging
from os import PathLike
import shlex
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Union, Callable, Type


from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QTextEdit, QLineEdit
from PySide6.QtGui import QTextCursor

from lib.customlog import create_logger


def make_command_transformer(plugin_dir):
    """构造命令补全函数：把指向插件目录内文件的 token 自动替换为绝对路径"""

    plugin_path = Path(plugin_dir) if plugin_dir else None
    # 这些 token 是 shell 操作符，不能被 shlex.quote 加引号
    shell_ops = {'|', '>', '<', '>>', '<<', '&&', '||', ';', '&', '2>', '1>&2', '2>&1'}

    def needs_quote(tok: str) -> bool:
        # 含空格或 shell 元字符的 token 需要 quote 以保留语义
        return any(c in tok for c in " \t'\"\\$`<>|;&(){}")

    def transformer(command: str) -> str:
        if not plugin_path or not command.strip():
            return command
        try:
            tokens = shlex.split(command)
        except ValueError:
            # 引号不闭合等场景，原样返回避免破坏用户输入
            return command
        changed = False
        new_tokens = []
        for tok in tokens:
            if tok in shell_ops or tok.startswith("-"):
                new_tokens.append(tok)
                continue
            candidate = plugin_path / tok
            if candidate.exists():
                new_tokens.append(candidate.as_posix())
                changed = True
            else:
                new_tokens.append(shlex.quote(tok) if needs_quote(tok) else tok)
        if not changed:
            return command
        return " ".join(new_tokens)

    return transformer


class TerminalWidget(QWidget):
    def __init__(self, logger: logging.Logger, parent=None,
                 working_directory: Optional[Union[str, Path]] = None,
                 environment: Optional[dict] = None,
                 command_transformer: Optional[Callable[[str], str]] = None):
        super().__init__(parent)
        self.logger = logger
        self._command_transformer = command_transformer or (lambda x: x)
        self.input_line = ''
        self.output_text = ''
        layout = QVBoxLayout(self)

        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        layout.addWidget(self.output_text)

        self.input_line = QLineEdit()
        self.input_line.returnPressed.connect(self.write_to_process)
        layout.addWidget(self.input_line)

        self.process = QProcess()
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.readyReadStandardError.connect(self.read_error)

        # 工作目录：决定子进程的 cwd，脚本输出到相对路径会落在这里
        if working_directory is not None:
            self.process.setWorkingDirectory(str(working_directory))

        # 环境变量：继承系统环境并合并用户传入的变量
        env = QProcessEnvironment.systemEnvironment()
        if environment:
            for key, value in environment.items():
                env.insert(key, str(value))
        self.process.setProcessEnvironment(env)

        # 根据操作系统启动相应的shell
        if sys.platform == "win32":
            self.process.start("cmd.exe")
        else:
            self.process.start("bash")

    def deleteLater(self, /):
        """重写关闭事件，确保进程正常退出"""
        if self.process.state() == QProcess.ProcessState.Running:
            # 先尝试正常终止
            self.process.terminate()
            # 等待进程退出（最多等待3秒）
            if not self.process.waitForFinished(3000):
                # 如果正常终止失败，强制杀死进程
                self.process.kill()
                self.process.waitForFinished(1000)

    def closeEvent(self, event):
        """重写关闭事件，确保进程正常退出"""
        if self.process.state() == QProcess.ProcessState.Running:
            # 先尝试正常终止
            self.process.terminate()
            # 等待进程退出（最多等待3秒）
            if not self.process.waitForFinished(3000):
                # 如果正常终止失败，强制杀死进程
                self.process.kill()
                self.process.waitForFinished(1000)
        event.accept()

    def read_output(self):
        data = self.process.readAllStandardOutput()
        text = data.data().decode('utf-8', errors='ignore')
        self.logger.debug(text)
        self.append_text(text)

    def read_error(self):
        data = self.process.readAllStandardError()
        text = data.data().decode('utf-8', errors='ignore')
        self.logger.error(text)
        self.append_text(text)

    def append_text(self, text):
        cursor = self.output_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output_text.setTextCursor(cursor)
        self.output_text.ensureCursorVisible()

    def write_to_process(self):
        raw = self.input_line.text()
        self.input_line.clear()
        command = self._command_transformer(raw)
        command_full = command + "\n"
        self.logger.info(f"user input command: {raw}" + (f" -> {command}" if command != raw else ""))
        self._echo_command(command_full)
        self.process.write(command_full.encode())

    def send(self, text):
        command = self._command_transformer(text)
        command_full = command + "\n"
        self.logger.info(f"send command: {text}" + (f" -> {command}" if command != text else ""))
        self._echo_command(command_full)
        self.process.write(command_full.encode())

    def _echo_command(self, command: str):
        """以 [时间]指令 格式回显发送的指令"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        prompt = f"[{timestamp}] {command}"
        self.append_text(prompt)


class MainWindow(QMainWindow):
    def __init__(
            self, name: str, commands: List[str] = None, logger: logging.Logger = None,
            data_path: Union[PathLike[str], str, None] = None, *args, **kwargs
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
            self.logger = create_logger(name="terminal", level=logging.DEBUG, log_path=log_path)
        self.logger.info("terminal logging started")
        if args:
            self.logger.debug(f"外部额外args参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外args参数：{kwargs}")

        self.setWindowTitle("PyQTerm终端")
        self.setGeometry(100, 100, 800, 600)
        self.terminal = TerminalWidget(logger)
        self.setCentralWidget(self.terminal)
        self.terminal.send(f"cd {self.data_path.as_posix()}")
        if commands:
            for command in commands:
                self.terminal.send(command)

    def deleteLater(self, /):
        self.terminal.process.deleteLater()
        self.terminal.deleteLater()
        self.logger.info(f"{self.widget_name}窗口关闭")

    def closeEvent(self, event):
        self.terminal.process.deleteLater()
        self.terminal.deleteLater()
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()


    @staticmethod
    def _build_terminal_handler(commands: List[str]) -> Type:
        """根据命令列表动态生成一个终端窗口处理类"""

        class _TerminalHandler(QMainWindow):
            _commands = list(commands)

            def __init__(self, name: str, version: str = "0.0.0",
                         data_path=None, logger: logging.Logger = None,
                         *args, **kwargs):
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
                    self.logger = create_logger(
                        name=name, level=logging.DEBUG, log_path=log_path
                    )
                self.logger.info("terminal logging started")
                if args:
                    self.logger.debug(f"外部额外args参数：{args}")
                if kwargs:
                    self.logger.debug(f"外部额外args参数：{kwargs}")

                # 插件目录：由 PluginManager 在加载时写入类属性
                plugin_dir = getattr(self, "_plugin_dir", None)

                # 子进程 cwd 设为 data_path，脚本输出相对路径会落在这里
                env = {
                    "PLUGIN_DIR": str(plugin_dir) if plugin_dir else "",
                    "DATA_PATH": str(self.data_path),
                }

                # 命令补全：把命令里指向插件目录内文件的相对路径 token 自动替换为绝对路径
                # 用户写 "python main.py" 且插件目录有 main.py 时，自动补成绝对路径
                transformer = make_command_transformer(plugin_dir)

                self.setWindowTitle(name+" V"+version)
                self.setGeometry(100, 100, 800, 600)
                self.terminal = TerminalWidget(
                    self.logger,
                    working_directory=self.data_path,
                    environment=env,
                    command_transformer=transformer,
                )
                self.setCentralWidget(self.terminal)
                for command in self._commands:
                    self.terminal.send(command)

            def deleteLater(self, /):
                self.terminal.process.deleteLater()
                self.terminal.deleteLater()
                self.logger.info(f"{self.widget_name}窗口关闭")

            def closeEvent(self, event):
                self.terminal.process.deleteLater()
                self.terminal.deleteLater()
                self.logger.info(f"{self.widget_name}窗口关闭")
                event.accept()

        return _TerminalHandler


def build_terminal_handler(commands: List[str]) -> Type:
    """根据命令列表动态生成一个终端窗口处理类"""
    class _TerminalHandler(QMainWindow):
        _commands = list(commands)

        def __init__(self, name: str, version: str = "0.0.0",
                     data_path=None, logger: logging.Logger = None,
                     *args, **kwargs):
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
                self.logger = create_logger(
                    name=name, level=logging.DEBUG, log_path=log_path
                )
            self.logger.info("terminal logging started")
            if args:
                self.logger.debug(f"外部额外args参数：{args}")
            if kwargs:
                self.logger.debug(f"外部额外args参数：{kwargs}")

            # 插件目录：由 PluginManager 在加载时写入类属性
            plugin_dir = getattr(self, "_plugin_dir", None)

            # 子进程 cwd 设为 data_path，脚本输出相对路径会落在这里
            env = {
                "PLUGIN_DIR": str(plugin_dir) if plugin_dir else "",
                "DATA_PATH": str(self.data_path),
            }

            # 命令补全：把命令里指向插件目录内文件的相对路径 token 自动替换为绝对路径
            # 用户写 "python main.py" 且插件目录有 main.py 时，自动补成绝对路径
            transformer = make_command_transformer(plugin_dir)

            self.setWindowTitle(name+" V"+version)
            self.setGeometry(100, 100, 800, 600)
            self.terminal = TerminalWidget(
                self.logger,
                working_directory=self.data_path,
                environment=env,
                command_transformer=transformer,
            )
            self.setCentralWidget(self.terminal)
            for command in self._commands:
                self.terminal.send(command)

        def deleteLater(self, /):
            self.terminal.process.deleteLater()
            self.terminal.deleteLater()
            self.logger.info(f"{self.widget_name}窗口关闭")

        def closeEvent(self, event):
            self.terminal.process.deleteLater()
            self.terminal.deleteLater()
            self.logger.info(f"{self.widget_name}窗口关闭")
            event.accept()

    return _TerminalHandler


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow("terminal", ["which python", "echo 'hello the world'"])
    window.show()
    sys.exit(app.exec())
