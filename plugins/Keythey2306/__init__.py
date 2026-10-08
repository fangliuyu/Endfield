
from .main import MainWindow
from src.plugin_manager import register

register(
    name="Keithley2306",
    author="Liuyu.fang",
    version="0.0.1",
    category="Instrument",
    introduction="Keithley2306直流电源测量控制"
).handler(MainWindow)

