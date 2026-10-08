import sys

from PySide6.QtWidgets import QApplication

from .src.gui import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow("SItools")
    window.show()
    sys.exit(app.exec())
