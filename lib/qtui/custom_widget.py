import logging
from pathlib import Path
from typing import Union, Literal

from PySide6.QtWidgets import (
    QWidget, QGroupBox, QHBoxLayout, QVBoxLayout,
    QGridLayout, QScrollArea, QPushButton, QLabel,
    QSizePolicy, QTextEdit, QDialog, QProgressBar
)
from PySide6.QtCore import (
    Qt, QPoint, QEasingCurve, QVariantAnimation,
    Signal, QObject, Slot, QTimer, QRect
)
from PySide6.QtGui import (
    QPainter, QColor, QLinearGradient, QFont,
    QPen, QPixmap, QEnterEvent, QBrush
)

CHANNEL_COLORS = [
    "#323232",  # Black
    "#f6d44f",  # yellow
    "#26bb34",  # green
    "#245d9e",  # blue
    "#a30a72"  # purple
]

GroupboxStyle = """
    QGroupBox {
        font-Size: %dpx;
        font-weight: bold;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: %d %dpx;
        background-color: transparent;
    }
"""


class SignalWrapper(QObject):
    Signal: Signal = None

    def __init__(self, /, *signal_type: type):
        super().__init__()
        # PySide6 要求 Signal 是类属性（描述符协议）。
        # 动态创建一个唯一子类，使 Signal 成为合法的类属性。
        suffix = '_'.join(t.__name__ for t in signal_type) if signal_type else 'void'
        wrapper_cls = type(f'SignalWrapper{suffix}', (QObject,), {'Signal': Signal(*signal_type)})
        self.__class__ = wrapper_cls


def build_group_box(
        name: str, layout_type: Union[QHBoxLayout, QVBoxLayout, QGridLayout],
        font_size=15, title_y=7, title_x=5
):
    new_group_box = QGroupBox(name)
    new_group_box.setStyleSheet(GroupboxStyle % (font_size, title_y, title_x))
    group_box_layout = layout_type
    group_box_layout.setContentsMargins(5, 5, 5, 5)
    group_box_layout.setSpacing(5)
    new_group_box.setLayout(group_box_layout)
    return new_group_box, group_box_layout


class ImageLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setMinimumSize(534, 400)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def setPixmap(self, pixmap):
        self._pixmap = pixmap
        self.update_scaled_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_scaled_pixmap()

    def setPixmapFromData(self, data):
        if self._pixmap.loadFromData(data):
            self.setPixmap(self._pixmap)

    def update_scaled_pixmap(self):
        if self._pixmap and not self._pixmap.isNull():
            # 获取label的当前大小
            label_size = self.size()

            # 等比例缩放图片
            scaled_pixmap = self._pixmap.scaled(
                label_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            )

            # 调用父类的setPixmap显示缩放后的图片
            super().setPixmap(scaled_pixmap)


class SwitchButton(QWidget):
    clicked = Signal(bool)  # 发送开关状态信息

    def __init__(self, parent=None, on_label: str = "ON", off_label: str = "OFF"):
        super().__init__(parent)
        self.labels = [off_label, on_label]
        self._is_on = False

        # 颜色配置
        self._bg_colors = {False: QColor(120, 120, 120), True: QColor(30, 150, 50)}
        self._btn_colors = {False: QColor(200, 200, 200), True: QColor(250, 255, 250)}

        # 样式配置
        self.margin = 5
        self._text_color = {False: QColor(200, 200, 200), True: QColor(255, 255, 255)}
        self._font = QFont("Arial", 12, QFont.Weight.Bold)
        # self.setMinimumSize(70, 20)
        # self.setMaximumSize(70, 20)
        self.setFixedSize(70, 20)

        # 动画系统
        self._animation_progress = 0.0
        self.animation = QVariantAnimation()
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.animation.valueChanged.connect(self._update_animation_progress)

    def setState(self, state: bool):
        self._is_on = state
        self._change_state()

    def getState(self):
        return self._is_on

    def _update_animation_progress(self, value):
        self._animation_progress = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        painter.setPen(Qt.PenStyle.NoPen)

        # 背景绘制
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, self._bg_colors[self._is_on].lighter(120))
        gradient.setColorAt(1, self._bg_colors[self._is_on].darker(120))
        painter.setBrush(gradient)
        painter.drawRoundedRect(self.rect(), self.height() / 2, self.height() / 2)

        # 滑块绘制
        start_x = self.height() / 2
        end_x = self.width() - self.height() / 2
        current_x = start_x + (end_x - start_x) * self._animation_progress
        btn_center = QPoint(int(current_x), int(self.height() / 2))
        painter.setPen(QPen(Qt.GlobalColor.gray, 0.5))
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, self._btn_colors[self._is_on].lighter(110))
        gradient.setColorAt(1, self._btn_colors[self._is_on].darker(180))
        painter.setBrush(gradient)
        painter.drawEllipse(btn_center, self.height() / 2 - self.margin, self.height() / 2 - self.margin)

        # 文字绘制
        painter.setFont(self._font)
        painter.setPen(self._text_color[self._is_on])
        text = self.labels[1 if self._is_on else 0]
        text_rect = self.rect().adjusted(int(self.width() / 3), 0, -int(self.width() / 3), 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_on = not self._is_on
            self._change_state()

    def _change_state(self):
        # 发射开关状态信息
        self.clicked.emit(self._is_on)
        target = 1.0 if self._is_on else 0.0
        self.animation.stop()
        self.animation.setStartValue(self._animation_progress)
        self.animation.setEndValue(target)
        self.animation.start()


class LineWidget(QWidget):
    def __init__(self, color: QColor, direction: Literal['H', 'V'] = "H", margin: int = 30, width: int = 5,
                 line_width_factor: float = 0.008, length: int = None, parent=None):
        super().__init__(parent)
        self.line_color = color
        self.margin = margin
        self.line_width_factor = line_width_factor  # 线宽系数
        self.direction = direction  # 保存方向

        if direction == "H":
            self.setFixedHeight(width)
            self.setMaximumHeight(width)
            if length:
                self.setMinimumWidth(length)
        else:
            self.setFixedWidth(width)
            self.setMaximumWidth(width)
            if length:
                self.setMinimumHeight(length)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base_size = min(self.width(), self.height())
        dynamic_width = max(1, int(base_size * self.line_width_factor))

        pen = QPen(self.line_color, dynamic_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)

        if self.direction == "H":
            # 水平线：从左到右画线
            painter.drawLine(
                self.margin,
                int(self.height() / 2),
                self.width() - self.margin,
                int(self.height() / 2)
            )
        else:
            # 垂直线：从上到下画线
            painter.drawLine(
                int(self.width() / 2),
                self.margin,
                int(self.width() / 2),
                self.height() - self.margin
            )

    def resizeEvent(self, event):
        """当widget大小改变时触发重绘"""
        self.update()
        super().resizeEvent(event)

    def set_line_color(self, color: QColor):
        """动态设置线条颜色"""
        self.line_color = color
        self.update()

    def set_margin(self, margin: int):
        """动态设置边距"""
        self.margin = margin
        self.update()

    def set_line_width_factor(self, factor: float):
        """动态设置线宽系数"""
        self.line_width_factor = factor
        self.update()

    def set_direction(self, direction: Literal["H", "V"]):
        """动态设置方向"""
        self.direction = direction
        self.update()


class HorizontalWheelScrollArea(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def wheelEvent(self, event):
        # 重写滚轮事件，将垂直滚轮转换为水平滚动
        if event.angleDelta().y() != 0:
            # 获取水平滚动条
            h_scrollbar = self.horizontalScrollBar()
            # 根据滚轮方向计算水平滚动量
            delta = event.angleDelta().y()
            # 设置滚动步长（可根据需要调整）
            scroll_amount = delta // 4
            # 执行水平滚动
            h_scrollbar.setValue(h_scrollbar.value() - scroll_amount)
            event.accept()
        else:
            super().wheelEvent(event)


class ImageTextButton(QPushButton):
    def __init__(self, text: str, logo_image: str = None, icon_text: str = None, tip_text: str = None, parent=None):
        super().__init__(parent)

        self.btn_name = text
        self._hovered = False

        self.setFixedSize(100, 100)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)

        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        icon_label = QLabel()
        icon_label.setObjectName("icon_label")
        icon_label.setStyleSheet("font-size: 32px; background: transparent; border: none;")
        icon_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if logo_image and Path(logo_image).exists():
            pixmap = QPixmap(logo_image)
            pixmap = pixmap.scaled(
                64, 64,
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setText(icon_text or "\U0001f527")
            icon_label.setFont(QFont("", 64))

        text_label = QLabel(text)
        text_label.setObjectName("text_label")
        text_label.setStyleSheet(
            "font-size: 11px; font-weight: 500; color: #333; "
            "margin-top: 2px; background: transparent; border: none;"
        )
        text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(icon_label, 3)
        layout.addWidget(text_label, 1)

        self.setLayout(layout)

        self.setStyleSheet("QSlider {background-color:transparent;} QToolTip {background-color:white}")
        self.setToolTip(tip_text or text)

    def enterEvent(self, event: QEnterEvent):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        checked = self.isChecked()
        down = self.isDown()

        if checked:
            bg = QColor(0, 122, 204, 38)
            border = QColor(0, 122, 204)
            border_width = 2
        elif down:
            bg = QColor(0, 123, 255, 51)
            border = QColor(0, 123, 255, 128)
            border_width = 1
        elif self._hovered:
            bg = QColor(0, 123, 255, 25)
            border = QColor(0, 123, 255, 76)
            border_width = 1
        else:
            bg = QColor(0, 0, 0, 0)
            border = QColor(0, 0, 0, 0)
            border_width = 1

        painter.setBrush(bg)
        pen = QPen(border, border_width)
        painter.setPen(pen)
        painter.drawRoundedRect(QRect(1, 1, rect.width() - 2, rect.height() - 2), 8, 8)


class _log_signal(QObject):
    """日志信号类"""
    log_message = Signal(str)


class _textEdit_logger_handler(logging.Handler):
    """自定义日志处理器"""
    color_map = {
        "DEBUG": "green",
        "INFO": "black",
        "WARNING": "orange",
        "ERROR": "red",
        "CRITICAL": "red"
    }

    def __init__(self, log_signal: _log_signal, level=logging.INFO, level_show: bool = False, color_show: bool = False):
        super().__init__()
        self.log_signal = log_signal
        self.level = level
        self.color_enable = color_show
        self.show_level(level_show)

    def show_level(self, state: bool):
        if state:
            formatter = logging.Formatter('[%(levelname)-8s] %(message)s')
        else:
            formatter = logging.Formatter('%(message)s')
        self.setFormatter(formatter)

    def emit(self, record):
        msg = self.format(record)
        color = self.color_map[record.levelname]
        if self.color_enable:
            msg = f'<font style="color: {color};">{msg}</font>'
        self.log_signal.log_message.emit(msg)


class LogTextEdit(QTextEdit):
    def __init__(self, parent=None, logger: logging.Logger = None,
                 level=logging.INFO, show_level: bool = True, show_color: bool = True
                 ):
        super().__init__(parent)
        self.setReadOnly(True)

        self.logger = None
        self.log_signal = _log_signal()
        self.log_signal.log_message.connect(self.append_log)
        self.log_handler = _textEdit_logger_handler(
            self.log_signal, level, level_show=show_level, color_show=show_color
        )
        if logger:
            self.logger = logger
            self.set_logger(self.logger, level)

    def set_show_level(self, state: bool):
        self.log_handler.show_level(state)

    def set_show_color(self, state: bool):
        self.log_handler.color_enable = state

    def set_logger(self, logger: logging.Logger = None, level=logging.INFO, clr_old_logger: bool = False):
        if self.logger and clr_old_logger:
            self.logger.removeHandler(self.log_handler)
        self.logger = logger
        self.log_handler.setLevel(level)
        self.logger.addHandler(self.log_handler)

    @Slot(str)
    def append_log(self, message):
        """添加日志消息到文本框"""
        self.append(message)
        # 自动滚动到底部
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)


class LogWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window | Qt.WindowType.Tool)
        if parent:
            self.setGeometry(100, 100, 500, parent.height())
        layout = QVBoxLayout(self)
        self.log_box = LogTextEdit()
        layout.addWidget(self.log_box)


def show_toast(parent, message, duration=1000, color: str = "white"):
    toast = QLabel(message, parent)
    toast.setStyleSheet("""                                                                                                             
          QLabel {                                                                                                                        
              background-color: rgba(0, 0, 0, 255);                                                                                       
              color: %s;                                                                                                               
              padding: 12px 24px;                                                                                                         
              border-radius: 6px;                                                                                                         
              font-size: 26px;                                                                                                            
          }                                                                                                                               
      """ % color)
    toast.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
    toast.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    toast.adjustSize()

    # 居中显示在 parent 窗口
    parent_rect = parent.rect()
    toast.move(parent.mapToGlobal(
        parent_rect.center() - toast.rect().center()
    ))
    toast.show()
    QTimer.singleShot(duration, toast.close)


class LoadingDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("加载中...")
        self.setModal(True)
        self.setFixedSize(300, 100)

        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.CustomizeWindowHint)

        layout = QVBoxLayout(self)
        self.label = QLabel("正在加载插件，请稍候...")
        layout.addWidget(self.label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        layout.addWidget(self.progress_bar)
