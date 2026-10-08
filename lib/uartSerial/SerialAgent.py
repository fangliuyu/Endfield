
import re
import serial
import threading
import time
import logging
from pathlib import Path
from typing import Optional, Callable


class UARTSerial:
    def __init__(
            self,
            port: str, baud_rate: int, timeout: float = 1.0,
            bytesize: int = serial.EIGHTBITS, parity: str = serial.PARITY_NONE, stop_bits: int = serial.STOPBITS_ONE,
            rts_cts=False, xon_off=False, dsr_dtr=False,
    ):
        # 串口相关
        self.serial_port = None
        self.port = port
        self.baud = baud_rate
        self.timeout = timeout
        self.bytesize = bytesize
        self.parity = parity
        self.stop_bits = stop_bits
        self.rts_cts = rts_cts
        self.dsr_dtr = dsr_dtr
        self.xon_off = xon_off
        self.is_connected = False

        # 日志相关
        self.logger: Optional[logging.Logger] = None
        self.log_file_path: Optional[Path] = None

        # 线程控制
        self.receive_thread = None
        self.should_stop = False

        # 回调函数
        self.data_received_callback: Optional[Callable[[dict], None]] = None
        self.connection_status_callback: Optional[Callable[[bool, str], None]] = None

        # 响应数据
        self.response_event = threading.Event()
        self.response_data = ""

    def _build_serial_log(self):
        """设置logging配置"""
        if self.logger:
            # 如果已经有了logger不再建
            return

        name = f"serial_{self.port}"

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)

        self.logger.info(f"Serial connection started - Port: {self.port}, Baudrate: {self.baud}")

    def close_serial_log(self):
        if self.is_connected:
            # 确保logger没有在占用中
            self.disconnect()
        if self.logger:
            self.logger.info(f"serial[{self.port}] logger closed.")
            for handler in self.logger.handlers[:]:
                handler.close()
                self.logger.removeHandler(handler)
            self.logger.setLevel(logging.CRITICAL + 1)
            logging.Logger.manager.loggerDict.pop(self.logger.name, None)
            del self.logger

    def set_serial_log(self, logger: logging.Logger):
        """设置logging配置"""
        self.close_serial_log()
        self.logger = logger
        self.logger.info(f"serial[{self.port}] logger start")

    def connect(self) -> bool:
        """连接串口"""
        try:
            if self.is_connected:
                self.disconnect()

            self.serial_port = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=self.timeout,
                bytesize=self.bytesize,
                parity=self.parity,
                stopbits=self.serial_port,
                rtscts=self.rts_cts,
                xonxoff=self.xon_off,
                dsrdtr=self.dsr_dtr,
            )

            # 确保存在logger
            self._build_serial_log()

            if self.serial_port.is_open:
                self.is_connected = True
                self.should_stop = False

                # 启动接收线程
                self.receive_thread = threading.Thread(
                    target=self._receive_data_thread,
                    daemon=True
                )
                self.receive_thread.start()

                # 回调通知
                if self.connection_status_callback:
                    self.connection_status_callback(True, f"Connected to {self.port}")

                self.logger.info(f"Serial port {self.port} connected successfully")
                return True
            else:
                error_msg = f"Failed to open port {self.port}"
                if self.connection_status_callback:
                    self.connection_status_callback(False, error_msg)
                self.logger.error(error_msg)
                return False

        except serial.SerialException as e:
            error_msg = f"Serial connection error: {str(e)}"
            if self.connection_status_callback:
                self.connection_status_callback(False, error_msg)
            # self.logger.error(error_msg)
            return False
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            if self.connection_status_callback:
                self.connection_status_callback(False, error_msg)
            # self.logger.error(error_msg)
            return False

    def disconnect(self):
        """断开串口连接"""
        if self.serial_port and self.serial_port.is_open:
            self.should_stop = True

            if self.receive_thread and self.receive_thread.is_alive():
                self.receive_thread.join(timeout=2)

            self.serial_port.close()
            self.is_connected = False

            # 回调通知
            if self.connection_status_callback:
                self.connection_status_callback(False, "Disconnected")

            disconnect_msg = f"serial[{self.port}] connection closed"
            self.logger.info(disconnect_msg)

            # 清理logger handlers
            for handler in self.logger.handlers[:]:
                handler.close()
                self.logger.removeHandler(handler)

    def set_flow_control(self, rtc: bool, output: bool):
        self.serial_port.set_input_flow_control(rtc)
        self.serial_port.set_output_flow_control(output)

    def _receive_data_thread(self):
        """数据接收线程"""
        self.logger.info(f"serial[{self.port}] reader thread started")
        while not self.should_stop and self.serial_port and self.serial_port.is_open:
            try:
                # buffer = ""
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting).decode('utf-8', errors='replace')
                    # buffer += data

                    # 回调通知数据接收
                    if self.data_received_callback:
                        self.data_received_callback({
                            "port": self.port,
                            "msg": data,
                            "type": "serial_data",
                            "timestamp": time.time()
                        })

                    # 收集响应数据
                    if self.response_event.is_set():
                        self.response_data += data

                #     while '\n' in buffer:
                #         line, buffer = buffer.split('\n', 1)
                #         line = line.rstrip()
                #         if line:
                #             self.logger.info(line)
                #
                #             # 回调通知数据接收
                #             if self.data_received_callback:
                #                 self.data_received_callback({
                #                     "port": self.port,
                #                     "msg": line,
                #                     "type": "serial_data",
                #                     "timestamp": time.time()
                #                 })
                #
                #             # 收集响应数据
                #             if self.response_event.is_set():
                #                 self.response_data += line
                #
                # # 清空buffer中剩余的不完整数据，避免数据堆积
                # if buffer and self.response_event.is_set():
                #     # 如果有等待收集的响应，暂时保存到buffer供下一轮处理
                #     pass
                # elif buffer:
                #     # 没有在等待响应时，直接记录剩余数据
                #     if buffer.strip():
                #         self.logger.info(buffer.strip())
                #         if self.data_received_callback:
                #             self.data_received_callback({
                #                 "port": self.port,
                #                 "msg": buffer.strip(),
                #                 "type": "serial_data",
                #                 "timestamp": time.time()
                #             })

                time.sleep(0.01)  # 添加小延迟避免CPU过载，同时给数据到达时间

            except serial.SerialException as e:
                self.logger.error(f"Serial read error: {str(e)}")
                break
            except Exception as e:
                self.logger.error(f"Receive thread error: {str(e)}")
                break

        self.logger.info("Receive thread stopped")

    def send(self, command: str) -> bool:
        """发送数据"""
        if not self.is_connected or not self.serial_port:
            self.logger.error("Cannot send data: Not connected")
            return False

        try:
            self.serial_port.write(f"{command}\n\r".encode('utf-8'))
            self.serial_port.flush()
            self.logger.info(f"Send | {command}")
            return True
        except serial.SerialException as e:
            self.logger.error(f"Send data error: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected send error: {str(e)}")
            return False

    def send_with_response(self, command: str, timeout: float = 0.1, break_rule: str = None) -> str:
        """发送指令并等待响应"""
        if not self.is_connected or not self.serial_port:
            self.logger.error("Cannot send command: Not connected")
            return ""

        self.response_data = ""
        self.response_event.set()

        if not self.send(command):
            self.response_event.clear()
            return ""

        start_time = time.time()
        last_data_time = start_time
        has_break_rule = not (break_rule is None)

        while time.time() - start_time < timeout:
            current_time = time.time()

            # 如果有数据到达，更新最后数据时间
            if self.response_data:
                last_data_time = current_time

                # 检查是否满足break规则
                if has_break_rule:
                    match = re.search(break_rule, self.response_data)
                    if match and len(match.groups()) > 0:
                        self.logger.info(f"Break rule matched: {match.group()}")
                        break

            # 如果在0.02秒内没有新数据到达，且已经有一些数据，可以提前返回
            # 这样可以避免在数据完全接收时因数据慢到达而超时
            if self.response_data and (current_time - last_data_time > 0.05):
                # 给一个小缓冲时间，确保数据不再继续到达
                time.sleep(0.02)
                if self.response_data == self.response_data:  # 再次检查数据是否有更新
                    break

            time.sleep(0.01)

        self.response_event.clear()
        response = self.response_data
        self.response_data = ""

        self.logger.info(f"Command response received: {response}")
        return response

    def is_open(self) -> bool:
        """检查串口是否打开"""
        return self.is_connected and self.serial_port and self.serial_port.is_open

    def set_callbacks(self, data_received: Callable[[dict], None] = None,
                      connection_status: Callable[[bool, str], None] = None):
        """设置回调函数"""
        self.data_received_callback = data_received
        self.connection_status_callback = connection_status

    def __del__(self):
        """析构函数"""
        self.disconnect()
