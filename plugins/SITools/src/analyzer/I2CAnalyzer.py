import traceback
from collections import OrderedDict
from typing import Literal

import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec  # NOQA

import logging
from pathlib import Path

from .Analyzer import Analyzer
from ..setting import SetupData

# color map for plotting
color_map = {
    "SCL": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "SDA": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
}
# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8
PLOT_TIMING_MARGIN = 2000


class I2CAnalyzer(Analyzer):
    """
    Analyzes the I2C bus signals on both SCL and SDA.
    """

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # crop the waveform to within the analyzed data range
        min_edge_index, max_edge_index = self.pad_window(
            waveforms["SCL"],
            [
                edges_map["SCL"][0][0], 
                edges_map["SCL"][-1][0]
            ], 
            CROP_MARGIN_SAMPLES
        )
        for signal, waveform in waveforms.items():
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]
            
        try:
            # decode the i2c waveform
            self.logger.info("Decoding traffic...")
            self.decode(waveforms, edges_map)
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"WARNING: Decode failed. Exception thrown during decode:\n{e}")

        # perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        results.update(self.analyze_data_host(waveforms, edges_map))
        results.update(self.analyze_data_device(waveforms, edges_map))

        file_name = self.data_dir / "Measurement Data.xlsx"
        results_df = pd.DataFrame(results).T.apply(self.safe_to_numeric)
        results_df = results_df.round(3)[["Net", "Measurement", "Lower Limit", "Lower Warning", "Measured Value", "Upper Warning", "Upper Limit", "Unit", "Result", "Link"]].sort_index()
        results_df.to_excel(file_name, index=False)

        self.convertToWorkbook()
        return results_df

    def plot_scope_shot(self, title: str, waveforms: dict, signals: list, window, x_markers=None, y_markers=None, result=None):
        """Plot a measurement using matplotlib and save the image to disk."""

        self.logger.info(f"Plotting {title}")

        # set up the plot
        plt.style.use('dark_background')
        plt.figure()
        matplotlib.rcParams.update({'font.size': 6})
        gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1])
        ax = plt.subplot(gs[0])  # NOQA
        plt.title(title)
        plt.tight_layout(h_pad=4.0)
        plt.grid(True, color='0.2')

        # set up the axes
        min_t = waveforms[signals[0]]['t'].iloc[window[0]]
        max_t = waveforms[signals[0]]['t'].iloc[window[1]]
        # modify if slck points is too much

        time_gap = max_t - min_t
        plt.xlabel('Time')
        plt.ylabel('Voltage')
        # Place horizontal gridlines / ticks at important voltages according to signal being processed
        plt.yticks([-Y_AXIS_MARGIN, 0,
                    self.limits["Host SCL Low-Level Voltage"]["Upper Limit"], self.limits["Host SCL High-Level Voltage"]["Lower Limit"],
                    self.voltage, self.voltage + Y_AXIS_MARGIN])
        plt.axis((min_t, max_t, -Y_AXIS_MARGIN * 2, self.voltage + Y_AXIS_MARGIN * 2))
        # Restrict axis scale to seconds, milliseconds, microseconds, nanoseconds where applicable
        # Remove scientific notation offset labeling
        ax.xaxis.get_offset_text().set_visible(False)
        time_scale = 's'
        if time_gap < .000001:
            time_scale = 'ns'
            plt.ticklabel_format(style='sci', axis='x', scilimits=(-9, -9))
        elif time_gap < .001:
            time_scale = '\u03BCs'
            plt.ticklabel_format(style='sci', axis='x', scilimits=(-6, -6))
        elif time_gap < 1:
            time_scale = 'ms'
            plt.ticklabel_format(style='sci', axis='x', scilimits=(-3, -3))
        else:
            plt.ticklabel_format(style='sci', axis='x', scilimits=(0, 0))
            ax.xaxis.get_offset_text().set_visible(True)

        # plot the signals in the main graph
        # signal needs to be extracted from waveforms in the case of control signals
        for i, signal in enumerate(sorted(signals)):
            waveforms[signal].plot(kind="line", x="t", y="v", ax=ax, color=color_map[signal], legend=False, grid=True, linewidth=PLOT_LINE_WIDTH)
        ax.set_xlabel(f"Time ({time_scale})")

        # plot the measurement markers
        color = (233.0 / 255.0, 135.0 / 255.0, 121.0 / 255.0)
        if x_markers:
            for i in x_markers:
                marker = waveforms[signals[0]]['t'].iloc[i]
                plt.plot([marker, marker], [-Y_AXIS_MARGIN * 2, self.voltage + Y_AXIS_MARGIN * 2], color=color, linestyle="--", linewidth=MARKER_LINE_WIDTH)
        if y_markers:
            for i in y_markers:
                plt.plot([min_t, max_t], [i, i], color=color, linestyle="--", linewidth=MARKER_LINE_WIDTH)

        # draw the measurement text
        if result:
            unit = result["Unit"]
            scaled_measurement = result["Measured Value"]
            text = f"Measured: {scaled_measurement:0.2f}{unit}\n"
            if result["Lower Limit"] != "-":
                text += f"Lower Limit: {float(result['Lower Limit']):0.2f}{unit}\n"
            else:
                text += f"Lower Limit: -\n"  # Would set the default lower limit as 0 here if no limit is set
            if result["Upper Limit"] != "-":
                text += f"Upper Limit: {float(result['Upper Limit']):0.2f}{unit}\n"
            else:
                text += f"Upper Limit: -\n"
            props = {"boxstyle": "round", "edgecolor": "none", "facecolor": "black", "alpha": 1.0, "pad": 0.5}  # NOQA
            ax.text(0.02, 0.97, text, fontsize=5, transform=ax.transAxes, verticalalignment="top", bbox=props)
            if result["Result"] == "Pass":
                color = (188.0 / 255.0, 221.0 / 255.0, 120.0 / 255.0)
            else:
                color = (233.0 / 255.0, 135.0 / 255.0, 121.0 / 255.0)
            ax.text(0.02, 0.88, result["Result"], fontsize=6, transform=ax.transAxes, verticalalignment="top", bbox=props, color=color)

        # plot all signals in the zoomed-out graph
        # plotting signals specific to I2C
        ax = plt.subplot(gs[1])  # NOQA
        waveforms["SCL"].plot(kind="line", x="t", y="v", ax=ax, color=color_map["SCL"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SCL')
        SDA_offset = waveforms["SDA"].copy()
        SDA_offset["v"] = waveforms["SDA"]["v"] + self.voltage + .1
        SDA_offset.plot(kind="line", x="t", y="v", ax=ax, color=color_map["SDA"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SDA')
        start_t = waveforms[signals[0]]['t'].iloc[window[0]]
        end_t = waveforms[signals[0]]['t'].iloc[window[1]]
        color = ".8"
        plt.plot([start_t, start_t], [-Y_AXIS_MARGIN * 2, 2 * self.voltage + Y_AXIS_MARGIN * 2], color=color, linewidth=MARKER_LINE_WIDTH, linestyle="--")
        plt.plot([end_t, end_t], [-Y_AXIS_MARGIN * 2, 2 * self.voltage + Y_AXIS_MARGIN * 2], color=color, linewidth=MARKER_LINE_WIDTH, linestyle="--")
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        # write the plot to disk
        if not (self.data_dir / "picture").exists():
            (self.data_dir / "picture").mkdir()
        file_name = self.data_dir / ("picture/" + title.replace(":", "_") + ".png")
        plt.savefig(file_name, dpi=300)
        plt.close()

    def decode(self, waveforms: dict, edges_map: dict):
        """
        将波形转成数据
        """

        bits = []

        # filter out edges due to ack turnaround time
        edges_map = self.get_ack_filtered_edges(waveforms, edges_map)

        # Check that the limits mode was entered correctly
        high_level_voltage = self.find_high_level_voltage(waveforms['SDA'], (0, len(waveforms["SDA"].index) - 1), "Host SDA")
        if (
            high_level_voltage < self.limits[f"Host SDA High-Level Voltage"]["Lower Limit"] 
            or 
            high_level_voltage > self.limits[f"Host SDA High-Level Voltage"]["Upper Limit"]
        ):
            raise Exception(["[I2CAnalyzer] The high level voltage of the signal does not match what is expected in"
                             " the limits mode. Make sure the configuration mode in the JSON is entered correctly."])

        # find all the rising edges of SCL and record the SDA binary value
        filtered_edges = [e[0] for e in edges_map["SCL"] if e[1] == "VIH_RISE"]
        for i in filtered_edges:
            SDA_v = waveforms["SDA"]['v'].iloc[i]
            if SDA_v > self.limits[f"Host SDA High-Level Voltage"]["Lower Limit"]:
                bits.append("1")
            else:
                bits.append("0")

        # decoded output to report
        decoded_output = []

        # run I2C state machine
        chip_info = self.config.Analysis.Configuration["slave address"]
        reg_info = self.config.Analysis.Configuration["reg address"].replace("0x", "")
        num_reg_bytes = int(len(reg_info) * 4 / 8)
        data_length: int = self.config.Analysis.Configuration["data length"]
        state = "host_addr"
        try:
            while len(bits) > 0:
                # if number of bits falls short of address+data pair, record the remainder and end the state machine
                if state == "host_addr":
                    data_byte_count = num_reg_bytes
                else:
                    data_byte_count = data_length
                if state == "host_addr":
                    elen = 8 + 1 + (data_byte_count * 9)
                else:
                    elen = 8 + 1 + data_byte_count * 9
                # if len(bits) < 8 + 1 + (data_byte_count * 9):
                if len(bits) < elen:
                    # Throw critical error here because script can technically continue and possibly give more information
                    # about why the there was a bit mismatch error.
                    self.logger.critical("CRITICAL ERROR: [I2CAnalyzer] There is a mismatch between the size of parsed data"
                                         " and the expected bit count from .json file.\nExpected bit count: " +
                                         str(elen) + "\nActual bit count: " + str(len(bits)))
                #   7-bits host address drive
                #   1-bit R/W
                addr = bits[:7]
                rw = bits[7]
                binary_str = ""
                for bit in addr:
                    if int(bit) > 1:
                        bit = chr(bit)
                    binary_str = binary_str + str(bit)
                device_address = int(binary_str, 2)
                #   1-bit ACK
                ack1 = bits[8]
                #   Abort test if ACK bit is high (NACK)
                # We throw an exception for NACK because if there is a NACK, the data is completely corrupted
                # and useless. Might as well end the script now.
                if ack1 == 1:
                    raise Exception("[I2CAnalyzer] A NACK was recorded after attempt to communicate "
                                    "to device with address " + str(addr) + ". Aborting test...")
                decoded_output.append(f"ADDR: {''.join(addr)} ({hex(device_address)})")
                decoded_output.append("RW: " + rw)
                decoded_output.append("ACK: " + ack1)
                # discard the decoded bits
                bits = bits[9:]

                data_bytes = []
                data_acks = []
                for i in range(data_byte_count):
                    #   8-bits data initialization commands
                    data_bytes.append(bits[:8])
                    data = "".join(data_bytes[-1])
                    #   1-bit ACK
                    data_acks.append(bits[8])

                    # record the transaction
                    decoded_output.append(f"DATA: {data} ({hex(int(data, 2))})")
                    decoded_output.append("ACK: " + data_acks[-1])

                    # discard the decoded bits
                    bits = bits[9:]

                # discard bus stop
                bits = bits[1:]
                # sanity check recorded traffic
                # device_address = int(''.join(addr), 2)
                if device_address != int(chip_info, 16):
                    raise Exception(f"[I2CAnalyzer] Recorded waveform device address does not match. Read: {hex(device_address)} Expected: {chip_info}")
                else:
                    self.logger.info(f"read device address is {hex(device_address)}")
                # update protocol state
                if state == "host_addr":
                    # assume it's supposed to be a register read
                    if rw != "0":
                        raise Exception("[I2CAnalyzer] Recorded waveform is not a register write operation.")
                # device ack data
                state = "data_read"
        finally:
            # report decoded output
            file_name = self.data_dir / "I2C Decode.txt"
            with open(file_name, "w") as f:
                f.write("\n".join(decoded_output))

            # append decoded output to logger
            for line in decoded_output:
                self.logger.info(f"{line}")

    def analyze_data_host(self, waveforms: dict, edges_map: dict):
        """Suite of calculations for host-side specifications.
        Waived calculations due to challenges in acquiring proper scope capture: tSU:STA, tVD:ACK, bus free time.
        """
        results = OrderedDict()
        attempted_measurements = []

        window_host_addr_drive = self.get_byte_range_from_edges(edges_map, "host_addr_drive")
        window_host_addr_drive_no_start = self.get_byte_range_from_edges(edges_map, "host_addr_drive_no_start")
        edges_host_addr_drive = self.get_edges_within_byte_range(edges_map, window_host_addr_drive)
        # window_host_ack = self.get_byte_range_from_edges(edges_map, "host_ack")
        window_full_range = (0, len(waveforms["SDA"].index) - 1)

        high_level = self.voltage
        low_level = 0

        for signal in waveforms.keys():
            signal_side = f"Host {signal}"
            measurement = f"{signal_side} High-Level Voltage"
            attempted_measurements.append(measurement)
            try:
                window = window_full_range
                measured_value = self.find_high_level_voltage(waveforms[signal], window, signal_side)
                results[measurement] = self.process_results(signal_side, "High-Level Voltage", measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=[measured_value], result=results[measurement])
                high_level = measured_value
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = f"{signal_side} Low-Level Voltage"
            attempted_measurements.append(measurement)
            try:
                window = window_host_addr_drive
                measured_value = self.find_low_level_voltage(waveforms[signal], window, signal_side)
                results[measurement] = self.process_results(signal_side, "Low-Level Voltage", measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=[measured_value], result=results[measurement])
                low_level = measured_value
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = f"{signal_side} Undershoot"
            attempted_measurements.append(measurement)
            try:
                window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_host_addr_drive[signal], "min", signal_side)
                results[measurement] = self.process_results(signal_side, "Undershoot", abs(measured_value) / (high_level - low_level), True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = f"{signal_side} Overshoot"
            attempted_measurements.append(measurement)
            try:
                window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal_side)
                results[measurement] = self.process_results(signal_side, "Overshoot", abs(measured_value) / (high_level - low_level), True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = f"{signal_side} Rise Time"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
                results[measurement] = self.process_results(signal_side, "Rise Time", measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = f"{signal_side} Fall Time"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_host_addr_drive[signal][2:], "falling")
                results[measurement] = self.process_results(signal_side, "Fall Time", measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SCL Frequency"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_frequency(waveforms["SCL"], edges_map["SCL"])
            results[measurement] = self.process_results("Host SCL", "Frequency", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SCL Low-Period Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms["SCL"], edges_map["SCL"], "low", results['Host SCL High-Level Voltage']['Measured Value'])
            results[measurement] = self.process_results("Host SCL", "Low-Period Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SCL High-Period Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms["SCL"], edges_map["SCL"], "high", results['Host SCL High-Level Voltage']['Measured Value'])
            results[measurement] = self.process_results("Host SCL", "High-Period Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA Low-Period Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms["SDA"], edges_map["SDA"], "low", results['Host SDA High-Level Voltage']['Measured Value'])
            results[measurement] = self.process_results("Host SDA", "Low-Period Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA High-Period Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms["SDA"], edges_map["SDA"], "high", results['Host SDA High-Level Voltage']['Measured Value'])
            results[measurement] = self.process_results("Host SDA", "High-Period Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA tHD:STA"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:STA", window_host_addr_drive)
            results[measurement] = self.process_results("Host SDA", "tHD:STA", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA tSU:STO"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:STO", window_full_range)
            results[measurement] = self.process_results("Host SDA", "tSU:STO", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA tSU:DAT"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", window_host_addr_drive)
            results[measurement] = self.process_results("Host SDA", "tSU:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA tHD:DAT"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", window_host_addr_drive_no_start)
            results[measurement] = self.process_results("Host SDA", "tHD:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Host SDA tVD:DAT"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tVD:DAT", window_host_addr_drive_no_start)
            results[measurement] = self.process_results("Host SDA", "tVD:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # measurement = f"Host SDA tVD:ACK"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "Host tVD:ACK", window_host_ack)
        #     if window[0] is not -1:
        #         results[measurement] = self.process_results(measured_value, self.limits["tVD:DAT"])
        #         self.plot_scope_shot(measurement, waveform_path, waveforms, ["SCL", "SDA"], window, color_map, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results("Host SCL", attempted_measurements, results)
        results = self.check_results("Host SDA", attempted_measurements, results)

        return results

    def analyze_data_device(self, waveforms: dict, edges_map: dict):
        """Suite of calculations for device-side specifications."""
        results = OrderedDict()
        attempted_measurements = []

        window_device_data_drive = self.get_byte_range_from_edges(edges_map, "device_data_drive")
        edges_device_drive = self.get_edges_within_byte_range(edges_map, window_device_data_drive)
        window_device_ack = self.get_byte_range_from_edges(edges_map, "device_ack")
        # window_full_range = (0, len(waveforms["SDA"].index) - 1)
        window = window_device_data_drive

        high_level = self.voltage
        low_level = 0

        measurement = "Slave SDA High-Level Voltage"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms["SDA"], window, signal="Slave SDA")
            results[measurement] = self.process_results("Slave SDA", "High-Level Voltage", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA Low-Level Voltage"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms["SDA"], window, signal="Slave SDA")
            results[measurement] = self.process_results("Slave SDA", "Low-Level Voltage", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window, y_markers=[measured_value], result=results[measurement])
            low_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA Undershoot"
        attempted_measurements.append(measurement)
        try:
            window_Undershoot, y_markers, measured_value = self.find_edge_overshoot(waveforms["SDA"], edges_device_drive["SDA"], "min", signal="Slave SDA")
            results[measurement] = self.process_results("Slave SDA", "Undershoot", abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window_Undershoot, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA Overshoot"
        attempted_measurements.append(measurement)
        try:
            window_Overshoot, y_markers, measured_value = self.find_edge_overshoot(waveforms["SDA"], edges_device_drive["SDA"], "max", signal="Slave SDA")
            results[measurement] = self.process_results("Slave SDA", "Overshoot", abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window_Overshoot, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA Fall Time"
        attempted_measurements.append(measurement)
        try:
            window_Fall, x_markers, measured_value = self.find_edge_rate(waveforms["SDA"], edges_device_drive["SDA"], "falling")
            results[measurement] = self.process_results("Slave SDA", "Fall Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window_Fall, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA Rise Time"
        attempted_measurements.append(measurement)
        try:
            window_Rise, x_markers, measured_value = self.find_edge_rate(waveforms["SDA"], edges_device_drive["SDA"], "rising")
            results[measurement] = self.process_results("Slave SDA", "Rise Time", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SDA"], window_Rise, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA tSU:DAT"
        attempted_measurements.append(measurement)
        try:
            window_SUDAT, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", window_device_data_drive)
            results[measurement] = self.process_results("Slave SDA", "tSU:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window_SUDAT, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA tHD:DAT"
        attempted_measurements.append(measurement)
        try:
            window_HDDAT, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", window_device_data_drive)
            results[measurement] = self.process_results("Slave SDA", "tHD:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window_HDDAT, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA tVD:DAT"
        attempted_measurements.append(measurement)
        try:
            window_VDDAT, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tVD:DAT", window_device_data_drive)
            results[measurement] = self.process_results("Slave SDA", "tVD:DAT", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window_VDDAT, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = "Slave SDA tVD:ACK"
        attempted_measurements.append(measurement)
        try:
            window_VDACK, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "device tVD:ACK", window_device_ack)
            results[measurement] = self.process_results("Slave SDA", "tVD:ACK", measured_value)
            self.plot_scope_shot(measurement, waveforms, ["SCL", "SDA"], window_VDACK, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results("Slave SDA", attempted_measurements, results)

        return results

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    def get_ack_filtered_edges(self, waveforms: dict[str: pd.DataFrame], edges_map: dict[str: list]):
        """For a list of edges, remove the edges that are caused by ACK pulses.
        """
        ack_blank_periods = self.get_ack_blank_periods(waveforms, edges_map)
        new_edges_map = {
            "SCL": edges_map["SCL"],
            "SDA": [],
        }
        for e in edges_map["SDA"]:
            if any([period[0] <= e[0] <= period[1] for period in ack_blank_periods]):
                self.logger.debug(f"Discarding edge (ACK turnaround: {e}")
                continue
            new_edges_map["SDA"].append(e)
        return new_edges_map

    def get_ack_blank_periods(self, waveforms, edges_map):
        """Get the time index ranges in array with (start, stop) of ACK pulses.
        Used to ignore ACK turnaround windows that can be misinterpreted as data edges
        """
        scl_counter = 0
        ack_blank_periods = []
        for i in range(len(edges_map["SCL"]) - 1):
            e = edges_map["SCL"][i]
            next_e = edges_map["SCL"][i + 1]
            if e[1] == "VIL_FALL":
                scl_counter += 1
                # ACK is every 9 clocks
                if (scl_counter - 1) % 9 == 0:
                    blank = (e[0], next_e[0])
                    # verify that SDA is an inconsequential pulse in this window (starts and ends at low voltage)
                    if (waveforms["SDA"]['v'][blank[0]] < self.limits["Host SDA High-Level Voltage"]["Upper Limit"] and
                            waveforms["SDA"]['v'][blank[1]] < self.limits["Host SDA High-Level Voltage"]["Lower Limit"]):
                        ack_blank_periods.append(blank)
        return ack_blank_periods

    def get_edges_within_byte_range(self, edges_map, byte_range_idx):  # NOQA
        """Filter edges from an edges map data structure within a time index range."""
        return {signal: [e for e in edges if byte_range_idx[0] <= e[0] <= byte_range_idx[1]] for signal, edges in edges_map.items()}

    def get_byte_range_from_edges(self, edges_map: dict, byte_select: str):
        """Get the time index range of a particular byte range of the I2C protocol
        Used as a time filter window to pull the relevant waveform of a specific I2C state (i.e. host driving the bus, device driving the bus)

        Arguments:
        edges_map -- Dictionary of edge data {"SCL": [edges], "SDA": [edges]}
        byte_select -- String for I2C bus state to window

        Returns:
        [start time index, stop time index]
        Uses the array indices from original waveform dataframe.
        """

        # i2c traffic hints from config file
        reg_info = self.config.Analysis.Configuration["reg address"].replace("0x", "")
        num_reg_bytes = int(len(reg_info) * 4 / 8)
        num_data_bytes = self.config.Analysis.Configuration["data length"]

        # validate command
        if byte_select not in ["host_addr_drive", "host_addr_drive_no_start", "device_data_drive", "host_ack", "device_ack"]:
            raise Exception(f"[I2CAnalyzer]: Invalid byte selection range {byte_select}")

        # initialize return value
        byte_range_idx = [0, 0]
        # get the indices where the host is driving the address to the bus
        if byte_select == "host_addr_drive":
            byte_range_idx[0] = edges_map["SDA"][0][0]
            counter = 0
            for e in edges_map["SCL"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == 8:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1
        elif byte_select == "host_addr_drive_no_start":
            # start with the first rising edge on SCL
            for e in edges_map["SCL"]:
                if e[1] == "VIL_RISE":
                    byte_range_idx[0] = e[0]
                    break
            counter = 0
            for e in edges_map["SCL"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == 8:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1
        # get the indices where the device is driving data to the bus
        elif byte_select == "device_data_drive":
            counter = 1
            # device data drive starts after start 1x, addr drive + r/w + ack 9x, reg drive + ack 9x * num_reg_bytes, start 1x, addr drive + r/w + ack 9x
            start_edge = 1 + 9 + (9 * num_reg_bytes) + 1 + 9
            stop_edge = start_edge + 9 * num_data_bytes
            for e in edges_map["SCL"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == start_edge:
                    byte_range_idx[0] = e[0]
                elif counter == stop_edge:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1
        elif byte_select == "host_ack":
            counter = 1
            start_edge = 1 + 9 + (9 * num_reg_bytes) + 1 + 9 + 9 * num_data_bytes - 1
            stop_edge = start_edge + 1
            for e in edges_map["SCL"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == start_edge:
                    byte_range_idx[0] = e[0]
                elif counter == stop_edge:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1
        # get start index of device ack. Best device ack to use it the one right after the "read" bit because the transition will always be high to low
        elif byte_select == "device_ack":
            counter = 1
            start_edge = 1 + 9 + (9 * num_reg_bytes) + 1 + 8
            stop_edge = start_edge + 1
            for e in edges_map["SCL"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == start_edge:
                    byte_range_idx[0] = e[0]
                elif counter == stop_edge:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1

        # verify a window has been found
        # if byte_range_idx[0] == 0 or byte_range_idx[1] == 0:
        #     raise Exception(f"[I2CAnalyzer]: Cannot find window for {byte_select}")

        return byte_range_idx

    def get_edges_within_byte_range(self, edges_map, byte_range_idx):  # NOQA
        """Filter edges from an edges map data structure within a time index range."""
        return {
            signal: [
                e for e in edges if byte_range_idx[0] <= e[0] <= byte_range_idx[1]
            ] for signal, edges in edges_map.items()
        }

    def find_delta_time(self, waveforms, edges_map, mode: Literal["tHD:STA", "tSU:STO", "tSU:DAT", "tHD:DAT", "tVD:DAT", "host tVD:ACK", "device tVD:ACK"], input_window):
        """Calculate delta time between specific edges, based on  spec definition."""

        if mode not in ["tHD:STA", "tSU:STO", "tSU:DAT", "tHD:DAT", "tVD:DAT", "host tVD:ACK", "device tVD:ACK"]:
            raise Exception(f"[Analyzer]: Delta time mode not found: {mode}")

        window = [0, 0]
        x_markers = []

        e1_signal = ""
        e2_signal = ""
        e1 = None
        e2 = None
        if mode == "tHD:STA":
            e1_signal = "SDA"
            e2_signal = "SCL"
            # first SDA falling edge
            e1 = self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL")[0]
            # first SCL falling edge
            e2 = self.filter_edges(edges_map, input_window, e2_signal, "VIH_FALL")[0]
        elif mode == "tSU:STO":
            e1_signal = "SCL"
            e2_signal = "SDA"
            # last SCL rising edge
            e1 = self.filter_edges(edges_map, input_window, e1_signal, "VIH_RISE")[-1]
            # last SDA rising edge
            e2 = self.filter_edges(edges_map, input_window, e2_signal, "VIL_RISE")[-1]
        elif mode == "tSU:DAT":
            e1_signal = "SDA"
            e2_signal = "SCL"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e1_rise = self.filter_edges(edges_map, input_window, e1_signal, "VIH_RISE")
            e1_fall = self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL")
            e1s = e1_rise + e1_fall
            if len(e1s) == 0:
                raise Exception(f"[Analyzer]: Cannot find reference SDA edge for tSU:DAT")
            # next SCL rising edge(s)
            e2s = [self.get_next_edge(e1[0], self.filter_edges(edges_map, input_window, e2_signal, "VIL_RISE")) for e1 in e1s]
            for i in range(len(e2s)):
                if e2s[i] is None:
                    e1s[i] = None

            for i in range(e2s.count(None)):
                e1s.remove(None)
                e2s.remove(None)

            edges_zip = list(zip(e1s, e2s))
            e1, e2 = min(edges_zip, key=lambda e: waveforms[e2_signal]["t"].iloc[e[1][0]] - waveforms[e1_signal]["t"].iloc[e[0][0]])
        elif mode == "tHD:DAT":
            e1_signal = "SCL"
            e2_signal = "SDA"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e2_rise = self.filter_edges(edges_map, input_window, e2_signal, "VIL_RISE")
            e2_fall = self.filter_edges(edges_map, input_window, e2_signal, "VIH_FALL")
            e2s = e2_rise + e2_fall
            if len(e2s) == 0:
                raise Exception(f"[Analyzer]: Cannot find reference SDA edge for tHD:DAT")
            # previous SCL rising edge(s)
            e1s = [self.get_previous_edge(e2[0], self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL")) for e2 in e2s]
            for i in range(len(e1s)):
                if e1s[i] is None:
                    e2s[i] = None
            for i in range(e1s.count(None)):
                e1s.remove(None)
                e2s.remove(None)
            edges_zip = list(zip(e1s, e2s))
            e1, e2 = min(edges_zip, key=lambda e: waveforms[e2_signal]["t"].iloc[e[1][0]] - waveforms[e1_signal]["t"].iloc[e[0][0]])
        elif mode == "tVD:DAT":
            # "Time from SCL to rising or falling edge of SDA, whichever is slower" -- NXP Spec
            e1_signal = "SCL"
            e2_signal = "SDA"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e2_rise = self.filter_edges(edges_map, input_window, e2_signal, "VIH_RISE")
            e2_fall = self.filter_edges(edges_map, input_window, e2_signal, "VIL_FALL")
            e2s = e2_rise + e2_fall
            if len(e2s) == 0:
                raise Exception(f"[Analyzer]: Cannot find reference SDA edge for tVD:DAT")
            # previous SCL rising edge(s)
            e1s = [self.get_previous_edge(e2[0], self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL")) for e2 in e2s]
            for i in range(len(e1s)):
                if e1s[i] is None:
                    e2s[i] = None
            for i in range(e1s.count(None)):
                e1s.remove(None)
                e2s.remove(None)
            edges_zip = list(zip(e1s, e2s))
            e1, e2 = max(edges_zip, key=lambda e: waveforms[e2_signal]["t"].iloc[e[1][0]] - waveforms[e1_signal]["t"].iloc[e[0][0]])
        elif mode == "host tVD:ACK" or mode == "device tVD:ACK":
            # Time from falling edge of SCL to rising edge of SDA data read NACK bit
            e1_signal = "SCL"
            e2_signal = "SDA"
            # Next SDA Rising edge
            e2ind = int(input_window[0])
            if mode == "host tVD:ACK":
                # Next SDA rising edge for host tVD:ACK
                e2s = self.get_next_edge(e2ind, self.filter_edges(edges_map, input_window, e2_signal, "VIH_RISE"))
                if e2s is None:
                    self.logger.critical(f"CRITICAL: [Analyzer]: Cannot find reference SDA edge for {mode}. Make "
                                         f"sure there is a read bit followed by rising edge for the host NACK bit "
                                         f"somewhere in the signal. Continuing with other measurements.")
                    return [-1, -1], [-1, -1], -1
            else:
                # Next SDA falling edge for device tVD:ACK
                e2s = self.get_next_edge(e2ind, self.filter_edges(edges_map, input_window, e2_signal, "VIL_FALL"))
                if e2s is None:
                    self.logger.critical(f"[Analyzer]: Cannot find reference SDA edge for {mode}. Make "
                                         f"sure there is a read bit followed by rising edge for the host NACK bit "
                                         f"somewhere in the signal. Continuing with other measurements.")
                    return [-1, -1], [-1, -1], -1
            # Next SCL VIL falling edge
            e1s = self.get_next_edge(e2ind, self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL"))
            e1 = e1s
            e2 = e2s

        window[0] = e1[0]
        x_markers.append(e1[0])
        e1_time = waveforms[e1_signal]['t'].iloc[e1[0]]

        window[1] = e2[0]
        x_markers.append(e2[0])
        e2_time = waveforms[e2_signal]['t'].iloc[e2[0]]

        result = e2_time - e1_time
        return self.pad_window(waveforms["SCL"], window, PLOT_TIMING_MARGIN), x_markers, result

    def filter_edges(self, edges_map, input_window, signal, edge_spec):
        """Create a list of edges in edges_map within the given window that match the given level (VIH/VIL) and direction (RISE/FALL)"""
        return [e for e in edges_map[signal] if e[1] == edge_spec and self.is_index_in_window(e[0], input_window)]
