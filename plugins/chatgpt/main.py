
import logging
import sys
from os import PathLike
from pathlib import Path
from typing import Optional, Union

import requests
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QEvent
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
    QTextEdit, QVBoxLayout, QWidget, QMessageBox, QSizePolicy
)

from lib.customlog import create_logger
from lib.filetools import read_data_from_yaml, save_data_to_yaml

CONFIG_FILE = "chatgpt_config.yaml"


class MessageBubble(QFrame):
    """消息气泡"""

    def __init__(self, content: str, is_user: bool = False, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 5, 10, 5)

        self.label = QLabel(content)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        if is_user:
            self.setStyleSheet("""
                MessageBubble {
                    background-color: #dcf8c6;
                    border-radius: 10px;
                    margin: 5px;
                }
                QLabel {
                    padding: 8px;
                    color: #000;
                }
            """)
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            layout.addStretch()
            layout.addWidget(self.label)
        else:
            self.setStyleSheet("""
                MessageBubble {
                    background-color: #f0f0f0;
                    border-radius: 10px;
                    margin: 5px;
                }
                QLabel {
                    padding: 8px;
                    color: #000;
                }
            """)
            self.label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            layout.addWidget(self.label)
            layout.addStretch()


class ChatWorker(QThread):
    """聊天请求工作线程"""
    responseReady = Signal(str)
    streamChunk = Signal(str)
    streamFinished = Signal()
    error = Signal(str)

    def __init__(self, api_url: str, api_key: str, model: str, messages: list, stream: bool = False, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.stream = stream

    def run(self):
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": self.messages,
                "stream": self.stream
            }

            if self.stream:
                # 流式输出
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=60,
                    stream=True
                )
                response.raise_for_status()
                full_content = ""
                for line in response.iter_lines():
                    if line:
                        line = line.decode("utf-8")
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            import json
                            try:
                                chunk = json.loads(data)
                                # 检查是否有错误
                                if "error" in chunk:
                                    error_msg = chunk["error"].get("message", "未知错误")
                                    self.error.emit(f"API 错误：{error_msg}")
                                    return
                                choices = chunk.get("choices", [])
                                if not choices:
                                    # choices 为空时跳过（通常是最后一个只包含 usage 的 chunk）
                                    continue
                                delta = choices[0].get("delta", {}).get("content", "")
                                if delta:
                                    full_content += delta
                                    self.streamChunk.emit(delta)
                            except json.JSONDecodeError as e:
                                self.error.emit(f"JSON 解析失败：{str(e)} - 原始数据：{data}")
                                return
                self.streamFinished.emit()
                # 流式输出时不触发 responseReady，避免重复显示
            else:
                # 非流式输出
                response = requests.post(
                    self.api_url,
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()
                # 检查是否有错误
                if "error" in data:
                    error_msg = data["error"].get("message", "未知错误")
                    self.error.emit(f"API 错误：{error_msg}")
                    return
                choices = data.get("choices", [])
                if not choices:
                    self.error.emit(f"API 返回空响应：{data}")
                    return
                content = choices[0].get("message", {}).get("content", "无响应")
                self.responseReady.emit(content)
        except requests.exceptions.Timeout:
            self.error.emit("请求超时，请检查网络连接")
        except requests.exceptions.ConnectionError:
            self.error.emit("连接失败，请检查 API 地址")
        except requests.exceptions.HTTPError as e:
            self.error.emit(f"HTTP 错误：{e.response.status_code} - {e.response.text}")
        except Exception as e:
            self.error.emit(f"请求失败：{str(e)} - {type(e).__name__}")


class ChatMessageArea(QScrollArea):
    """聊天消息显示区域"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.messages: list[MessageBubble] = []
        self.messages_layout: list[dict] = []  # 存储上下文消息

        # 创建容器 widget
        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.container_layout.setSpacing(5)
        self.container_layout.setContentsMargins(5, 5, 5, 5)
        self.setWidget(self.container)

        # 设置样式
        self.setStyleSheet("""
            QScrollArea {
                border: 1px solid #ccc;
                border-radius: 5px;
                background-color: #fff;
            }
        """)

        # 监听内容变化自动滚动
        self.container.installEventFilter(self)

    def eventFilter(self, obj, event):
        """监听容器大小变化，自动滚动到底部"""
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.Resize:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
        return super().eventFilter(obj, event)

    def add_message(self, content: str, is_user: bool = False):
        """添加消息到聊天区域"""
        bubble = MessageBubble(content, is_user)
        # bubble.setMaximumWidth(600)
        self.messages.append(bubble)
        self.container_layout.addWidget(bubble)

        # 存储上下文消息
        role = "user" if is_user else "assistant"
        self.messages_layout.append({"role": role, "content": content})

        # 滚动到底部
        QTimer.singleShot(50, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        """延迟滚动到底部"""
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def add_system_message(self, content: str):
        """添加系统消息（不加入上下文）"""
        label = QLabel(content)
        label.setWordWrap(True)
        label.setStyleSheet("""
            color: #888;
            font-style: italic;
            padding: 5px;
        """)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.container_layout.addWidget(label)

    def clear_messages(self):
        """清空所有消息"""
        for bubble in self.messages:
            bubble.deleteLater()
        self.messages.clear()
        self.messages_layout.clear()

    def get_context_messages(self) -> list[dict]:
        """获取上下文消息列表"""
        return self.messages_layout.copy()


class SettingsPanel(QFrame):
    """设置面板"""

    def __init__(self, data_path: Path, parent=None):
        super().__init__(parent)
        self.logger: logging.Logger = getattr(parent, "logger")
        self.data_path = data_path
        self.config_file = self.data_path / CONFIG_FILE

        self.setFrameStyle(QFrame.Shape.Box)
        self.setLineWidth(1)

        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # API 地址
        layout.addWidget(QLabel("API 地址:"), 0, 0)
        self.api_url_input = QLineEdit("https://api.openai.com")
        self.api_url_input.setPlaceholderText("输入 API 地址")
        layout.addWidget(self.api_url_input, 0, 1, 1, 2)

        # API 密钥
        layout.addWidget(QLabel("API 密钥:"), 1, 0)
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入 API 密钥")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addWidget(self.api_key_input, 1, 1, 1, 2)

        # 模型选择
        layout.addWidget(QLabel("模型:"), 2, 0)
        self.model_input = QComboBox()
        self.model_input.setEditable(True)
        self.model_input.addItems([
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo"
        ])
        self.model_input.setCurrentText("gpt-4o")
        layout.addWidget(self.model_input, 2, 1, 1, 2)

        # 上下文开关
        layout.addWidget(QLabel("上下文:"), 3, 0)
        self.context_enabled = True
        self.context_btn = QPushButton("已开启")
        self.context_btn.setCheckable(True)
        self.context_btn.setChecked(True)
        self.context_btn.clicked.connect(self.toggle_context)
        self.context_btn.setStyleSheet("""
            QPushButton:checked {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px 10px;
            }
        """)
        layout.addWidget(self.context_btn, 3, 1)

        # 发送快捷键设置
        layout.addWidget(QLabel("发送键:"), 3, 2)
        self.send_key_combo = QComboBox()
        self.send_key_combo.addItems(["Enter 发送", "Ctrl+Enter 发送"])
        self.send_key_combo.setCurrentIndex(0)
        layout.addWidget(self.send_key_combo, 3, 3)

        # 流式输出开关
        layout.addWidget(QLabel("流式输出:"), 4, 0)
        self.stream_enabled = True
        self.stream_btn = QPushButton("已开启")
        self.stream_btn.setCheckable(True)
        self.stream_btn.setChecked(True)
        self.stream_btn.clicked.connect(self.toggle_stream)
        self.stream_btn.setStyleSheet("""
            QPushButton:checked {
                background-color: #4CAF50;
                color: white;
            }
            QPushButton {
                background-color: #f5f5f5;
                border: 1px solid #ccc;
                border-radius: 4px;
                padding: 5px 10px;
            }
        """)
        layout.addWidget(self.stream_btn, 4, 1)

        # 清空历史按钮
        self.clear_btn = QPushButton("清空历史")
        self.clear_btn.clicked.connect(self.clear_history)
        layout.addWidget(self.clear_btn, 4, 2, 1, 2)

        self.setStyleSheet("""
            SettingsPanel {
                background-color: #fafafa;
                border: 1px solid #ddd;
                border-radius: 5px;
            }
            QLabel {
                font-weight: bold;
            }
            QLineEdit, QComboBox {
                padding: 5px;
                border: 1px solid #ccc;
                border-radius: 4px;
            }
        """)

        self.load_settings()

    def toggle_context(self):
        self.context_enabled = self.context_btn.isChecked()
        if self.context_enabled:
            self.context_btn.setText("已开启")
        else:
            self.context_btn.setText("已关闭")

    def toggle_stream(self):
        self.stream_enabled = self.stream_btn.isChecked()
        if self.stream_enabled:
            self.stream_btn.setText("已开启")
        else:
            self.stream_btn.setText("已关闭")

    def clear_history(self):
        self.context_btn.setChecked(True)
        self.toggle_context()

    def load_settings(self):
        """从文件加载设置"""
        if self.config_file.exists():
            try:
                config = read_data_from_yaml(self.config_file)
                self.api_url_input.setText(config.get("api_url", "https://api.openai.com"))
                self.api_key_input.setText(config.get("api_key", ""))
                self.model_input.setCurrentText(config.get("model", "gpt-4o"))
                self.send_key_combo.setCurrentIndex(config.get("send_key_mode", 0))
                if not config.get("context_enabled", True):
                    self.context_btn.click()
                if not config.get("stream_enabled", True):
                    self.stream_btn.click()
            except Exception as e:
                self.logger.error(f"保存配置失败：{e}")

    def save_settings(self):
        """保存设置到文件"""
        config = {
            "api_url": self.api_url_input.text(),
            "api_key": self.api_key_input.text(),
            "model": self.model_input.currentText(),
            "context_enabled": self.context_enabled,
            "stream_enabled": self.stream_enabled,
            "send_key_mode": self.send_key_combo.currentIndex()
        }
        try:
            save_data_to_yaml(config, self.config_file)
        except Exception as e:
            self.logger.error(f"保存配置失败：{e}")

    def get_settings(self) -> dict:
        return {
            "api_url": self.api_url_input.text(),
            "api_key": self.api_key_input.text(),
            "model": self.model_input.currentText(),
            "context_enabled": self.context_enabled,
            "stream_enabled": self.stream_enabled
        }


class ChatWidget(QWidget):
    """聊天主控件"""

    def __init__(self, logger: logging.Logger, data_path: Path, parent=None):
        super().__init__(parent)
        self.logger = logger
        self.data_path = data_path
        self.worker: Optional[ChatWorker] = None
        self.current_ai_bubble: Optional[MessageBubble] = None  # 当前 AI 消息气泡

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        # 设置面板
        self.settings_panel = SettingsPanel(self.data_path, self)
        layout.addWidget(self.settings_panel)

        # 聊天消息区域
        self.chat_area = ChatMessageArea()
        self.chat_area.setMinimumHeight(400)
        layout.addWidget(self.chat_area, 1)

        # 输入区域
        input_frame = QFrame()
        input_layout = QHBoxLayout(input_frame)
        input_layout.setContentsMargins(0, 5, 0, 0)
        input_layout.setSpacing(5)

        self.input_text = QTextEdit()
        self.input_text.setPlaceholderText("输入消息... (Enter 发送，Shift+Enter 换行)")
        self.input_text.setMaximumHeight(100)
        self.input_text.setMinimumHeight(60)
        self.input_text.installEventFilter(self)
        input_layout.addWidget(self.input_text, 1)

        self.send_btn = QPushButton("发送")
        self.send_btn.setMinimumWidth(80)
        self.send_btn.setStyleSheet("""
            QPushButton {
                background-color: #007bff;
                color: white;
                border: none;
                border-radius: 5px;
                padding: 10px 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0056b3;
            }
            QPushButton:disabled {
                background-color: #ccc;
            }
        """)
        self.send_btn.clicked.connect(self.send_message)
        input_layout.addWidget(self.send_btn)

        layout.addWidget(input_frame)

    def eventFilter(self, obj, event):
        """拦截输入框的键盘事件"""

        if event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event  # NOQA
            if key_event.key() == Qt.Key.Key_Return or key_event.key() == Qt.Key.Key_Enter:
                # 检查当前设置
                send_mode = self.settings_panel.send_key_combo.currentIndex()

                if send_mode == 0:  # Enter 发送
                    if not key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self.send_message()
                        return True
                else:  # Ctrl+Enter 发送
                    if key_event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                        self.send_message()
                        return True
                    elif not key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        # 普通 Enter 换行
                        return False
        return super().eventFilter(obj, event)

    def send_message(self):
        content = self.input_text.toPlainText().strip()
        if not content:
            return

        settings = self.settings_panel.get_settings()
        if not settings["api_key"]:
            QMessageBox.warning(self, "警告", "请先输入 API 密钥")
            return

        # 显示用户消息
        self.chat_area.add_message(content, is_user=True)
        self.input_text.clear()

        # 构建消息列表
        if settings["context_enabled"]:
            messages = self.chat_area.get_context_messages()
        else:
            # 只发送当前消息
            messages = [{"role": "user", "content": content}]

        # 发送请求
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")

        # 流式输出时先创建空白的 AI 气泡
        self.current_ai_bubble = None
        if settings["stream_enabled"]:
            self.current_ai_bubble = MessageBubble("", is_user=False)
            self.current_ai_bubble.setMaximumWidth(600)
            self.chat_area.messages.append(self.current_ai_bubble)
            self.chat_area.container_layout.addWidget(self.current_ai_bubble)

        self.worker = ChatWorker(
            api_url=settings["api_url"]+"/v1/chat/completions",
            api_key=settings["api_key"],
            model=settings["model"],
            messages=messages,
            stream=settings["stream_enabled"],
            parent=self
        )
        self.worker.responseReady.connect(self.on_response)
        self.worker.streamChunk.connect(self.on_stream_chunk)
        self.worker.streamFinished.connect(self.on_stream_finished)
        self.worker.error.connect(self.on_error)
        self.worker.start()

    @Slot(str)
    def on_stream_chunk(self, chunk: str):
        """流式输出时更新 AI 消息"""
        if self.current_ai_bubble:
            current_text = self.current_ai_bubble.label.text()
            self.current_ai_bubble.label.setText(current_text + chunk)
            # 滚动到底部
            QTimer.singleShot(50, self.chat_area.scroll_to_bottom)

    @Slot()
    def on_stream_finished(self):
        """流式输出完成"""
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        # 将完整内容添加到上下文
        if self.current_ai_bubble:
            full_content = self.current_ai_bubble.label.text()
            self.chat_area.messages_layout.append({"role": "assistant", "content": full_content})
            self.current_ai_bubble = None
        self.logger.info("流式输出完成")

    @Slot(str)
    def on_response(self, content: str):
        """非流式输出的响应（流式输出时不会触发）"""
        # 只在非流式输出时添加消息
        self.chat_area.add_message(content, is_user=False)
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.logger.info(f"收到 AI 回复：{content[:50]}...")

    @Slot(str)
    def on_error(self, error_msg: str):
        self.chat_area.add_system_message(f"错误：{error_msg}")
        self.send_btn.setEnabled(True)
        self.send_btn.setText("发送")
        self.logger.error(f"API 请求错误：{error_msg}")


class MainWindow(QMainWindow):
    def __init__(
            self,
            name: str,
            version: str = "1.0.0",
            logger: Optional[logging.Logger] = None,
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
            self.logger.debug(f"外部额外 args 参数：{args}")
        if kwargs:
            self.logger.debug(f"外部额外 kwargs 参数：{kwargs}")

        self.setWindowTitle(f"{name} V{version}")
        self.resize(900, 700)

        # 创建中心 widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 标题
        title_label = QLabel("ChatGPT 聊天")
        title_label.setFont(QFont("Arial", 18, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title_label)

        # 聊天 widget
        self.chat_widget = ChatWidget(self.logger, self.data_path)
        main_layout.addWidget(self.chat_widget, 1)

    def closeEvent(self, event):
        # 窗口关闭时保存设置
        self.chat_widget.settings_panel.save_settings()
        self.logger.info(f"{self.widget_name} 设置已保存")
        self.logger.info(f"{self.widget_name}窗口关闭")
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow(name="ChatGPT", version="1.0.0")
    window.show()
    sys.exit(app.exec())
