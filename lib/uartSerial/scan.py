
from serial.serialutil import SerialBase
from serial.tools import list_ports


def get_serial_bauds():
    return SerialBase.BAUDRATES


def get_serial_bauds_str():
    for baud in SerialBase.BAUDRATES:
        yield str(baud)


def get_serial_ports(include_links: bool = None):
    return list_ports.comports(include_links)
