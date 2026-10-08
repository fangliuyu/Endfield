import sys
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from src.base import version, root_path, main_path, root_log, builtin_plugins_path
from ui.configuration import ConfigurationDialog
from ui.panel import FloatingPanel


class TrayApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setStyle("Fusion")
        self.app.setQuitOnLastWindowClosed(False)  # 防止关闭托盘时退出

        icon_path = Path(builtin_plugins_path / ".add_logo.png")
        if not icon_path.exists():
            # fallback：程序化生成的图标
            pixmap = QPixmap(16, 16)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setBrush(Qt.GlobalColor.darkCyan)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(0, 0, 16, 16, 3, 3)
            painter.end()
            icon = QIcon(pixmap)
        else:
            icon = QIcon(icon_path.as_posix())

        self.app.setWindowIcon(icon)
        self.tray_icon = QSystemTrayIcon(icon, self.app)
        self.tray_icon.setIcon(icon)
        self.tray_icon.setToolTip(f"Endfield {version}")

        self.floating_panel: Optional[FloatingPanel] = None

    def run(self):
        self.floating_panel = FloatingPanel(logger=root_log, data_path=main_path)

        tray_menu = QMenu()
        show_action = tray_menu.addAction("显示/隐藏面板")
        show_action.triggered.connect(self.toggle_panel_visibility)
        tray_menu.addSeparator()
        refresh_action = tray_menu.addAction("刷新插件列表")
        refresh_action.triggered.connect(self.floating_panel.init_gui)
        config_action = tray_menu.addAction("插件配置")
        config_action.triggered.connect(self.show_config_dialog)
        add_action = tray_menu.addAction("添加新插件")
        add_action.triggered.connect(self.floating_panel.add_new_plugin)
        tray_menu.addSeparator()
        quit_action = tray_menu.addAction("退出")
        quit_action.triggered.connect(self.quit_app)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

        sys.exit(self.app.exec())

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_panel_visibility()

    def toggle_panel_visibility(self):
        self.floating_panel.raise_()
        self.floating_panel.change_state()

    def show_config_dialog(self):
        config_dialog = ConfigurationDialog(self.floating_panel)
        config_dialog.exec()

    def quit_app(self):
        for window in list(self.floating_panel.plugin_windows.values()):
            window.close()
        self.floating_panel.plugin_windows.clear()
        self.tray_icon.hide()
        QApplication.quit()


if __name__ == "__main__":
    app = TrayApp()
    app.run()
