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
    "SWCLK": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "SWDO": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
}
# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8
PLOT_TIMING_MARGIN = 2000
Register_Action = {
    "00": "IDCode",
    "10": "CRTL/STAT or WCR",
    "01": "Resend",
    "11": "RDBuff",
}
ACK_Action = {
    "100": "OK",
    "010": "WAIT",
    "001": "FAULT",
    "000": "NoACK",
}


class SWDAnalyzer(Analyzer):
    """
    Analyzes the SWD bus signals on both SWCLK and SWDO.
    """

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)
        self.test_mode = str(self.config.Analysis.Configuration["mode"])
        self.test_name = str(self.config.Analysis.Configuration["direction"])

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # crop the waveform to within the analyzed data range
        min_edge_index, max_edge_index = self.pad_window(waveforms["SWCLK"],
                                                         [edges_map["SWCLK"][0][0], edges_map["SWCLK"][-1][0]], CROP_MARGIN_SAMPLES)
        for signal, waveform in waveforms.items():
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]

        start_index, end_index, rnw = 0, 0, -1
        try:
            # decode the SWD waveform
            self.logger.info("Decoding traffic...")
            start_index, end_index, rnw = self.decode(waveforms, edges_map)
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"WARNING: Decode failed. Exception thrown during decode:\n{e}")

        # perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        results.update(self.analyze_data_clk(waveforms, edges_map))

        # crop the waveform to within the analyzed data range
        # print(start_index, end_index)
        # min_edge_index, max_edge_index = self.pad_window(waveforms["SWCLK"], [start_index, end_index], CROP_MARGIN_SAMPLES)
        # for signal, waveform in waveforms.items():
        #     waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
        #     waveforms[signal].reset_index(drop=True, inplace=True)
        #     edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]
        if rnw > -1:
            results.update(self.analyze_data_host(waveforms, edges_map))
        if rnw == 1:
            results.update(self.analyze_data_device(waveforms, edges_map))
        elif rnw == -1:
            results.update(self.analyze_data_default(waveforms, edges_map))

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
                    self.limits["SWCLK Low-Level Voltage"]["Upper Limit"], self.limits["SWCLK High-Level Voltage"]["Lower Limit"],
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
        # plotting signals specific to SWD
        ax = plt.subplot(gs[1])  # NOQA
        waveforms["SWCLK"].plot(kind="line", x="t", y="v", ax=ax, color=color_map["SWCLK"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SWCLK')
        SWDO_offset = waveforms["SWDO"].copy()
        SWDO_offset["v"] = waveforms["SWDO"]["v"] + self.voltage + .1
        SWDO_offset.plot(kind="line", x="t", y="v", ax=ax, color=color_map["SWDO"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SWDO')
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
        :param edges_map:
        :param waveforms: SWD波形数据
        :return:
        """
        start_index = 0
        end_index = len(edges_map["SWCLK"]) - 1
        rnw = -1
        bits = []

        # filter out edges due to ack turnaround time
        edges_map = self.get_ack_filtered_edges(waveforms, edges_map)

        # Check that the limits mode was entered correctly
        high_level_voltage = self.find_high_level_voltage(waveforms['SWDO'], (0, len(waveforms["SWDO"].index) - 1), "Host SWDO")
        if high_level_voltage < self.limits[f"Host SWDO High-Level Voltage"]["Lower Limit"] or high_level_voltage > self.limits[f"Host SWDO High-Level Voltage"]["Upper Limit"]:
            self.logger.error(["[SWDAnalyzer] The high level voltage of the signal does not match what is expected in"
                               " the limits mode. Make sure the configuration mode in the JSON is entered correctly."])
            return start_index, end_index, rnw

        # find all the rising edges of SWCLK and record the SWDO binary value
        filtered_edges = [e[0] for e in edges_map["SWCLK"] if e[1] == "VIH_FALL"]
        for i in filtered_edges:
            SWDO_v = waveforms["SWDO"]['v'].iloc[i]
            if SWDO_v > self.limits[f"Host SWDO High-Level Voltage"]["Lower Limit"]:
                bits.append("1")
            else:
                bits.append("0")
        # decoded output to report
        decoded_output = []

        # run SWD state machine
        index = 0
        while len(bits) > 0:
            # Start APnDP RnW A[2"3] Parity Stop Park Trn Target Trn DATA Parity
            elen = (1 + 1 + 1 + 2 + 1 + 1 + 1) + 1 + 3 + 1 + 32 + 1

            if len(bits) < elen:
                self.logger.warning("[SWDAnalyzer] There is a mismatch between the size of parsed data"
                                    " and the expected bit count from .json file.\nExpected bit count: " +
                                    str(elen) + "\nActual bit count: " + str(len(bits)))
                break
            apdp = bits[1]
            if apdp == "0":
                apORdp = "DPACC"
            else:
                apORdp = "APACC"

            rw = bits[2]
            if rw == "1" and end_index == len(edges_map["SWCLK"]) - 1:
                start_index = edges_map["SWCLK"][index][0]
                end_index = edges_map["SWCLK"][index + elen][0]
                rnw = 1
            elif rw == "0":
                start_index = edges_map["SWCLK"][index][0]
                end_index = edges_map["SWCLK"][index + elen][0]
                rnw = 0

            addr = bits[3:5]
            binary_str = ""
            for bit in addr:
                if int(bit) > 1:
                    bit = chr(bit)
                binary_str = binary_str + str(bit)
            if binary_str not in Register_Action:
                self.logger.error("[SWDAnalyzer] There is a mismatch the register address")
                break
            action = Register_Action[binary_str]

            ack = bits[9:12]
            ack_str = ""
            for bit in ack:
                if int(bit) > 1:
                    bit = chr(bit)
                ack_str = ack_str + str(bit)
            ack_info = ACK_Action[ack_str]

            decoded_output.append(f"Access: {apORdp}")
            decoded_output.append(f"RnW: {rnw}")
            decoded_output.append(f"Action: {action}")
            decoded_output.append(f"ACK: {ack_info}")

            data_str = "DATA:"
            if rw == "1":
                data_bits = bits[12:45]
            else:
                data_bits = bits[13:46]

            data_bytes = []
            for i in range(4):
                #   8-bits data initialization commands
                data_bytes += data_bits[:8]
                data = "".join(data_bytes)

                # record the transaction
                data_str += " " + hex(int(data, 2))

                # discard the decoded bits
                data_bytes = []
                data_bits = data_bits[8:]
            decoded_output.append(data_str)
            bits = bits[elen:]
            index += elen

        # report decoded output
        file_name = self.data_dir / "SWD Decode.txt"
        with open(file_name, "w") as f:
            f.write("\n".join(decoded_output))

        # append decoded output to logger
        for line in decoded_output:
            self.logger.info(f"{line}")
        return start_index, end_index, rnw

    def analyze_data_clk(self, waveforms, edges_map):

        results = OrderedDict()
        attempted_measurements = []

        window_full_range = (0, len(waveforms["SWCLK"].index) - 1)
        high_level = self.voltage
        low_level = 0

        signal = "SWCLK"
        item = "Frequency"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window_full_range, signal=signal)
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window_full_range, signal=signal)
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            low_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Period Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", low_level)
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "High-Period Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", high_level)
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal=signal)
            results[measurement] = self.process_results(signal, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal=signal)
            results[measurement] = self.process_results(signal, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_host(self, waveforms, edges_map):
        """Suite of calculations for device-side specifications."""
        results = OrderedDict()
        attempted_measurements = []

        window_addr_drive = self.get_byte_range_from_edges(edges_map, "addr_drive")
        edges_device_drive = self.get_edges_within_byte_range(edges_map, window_addr_drive)
        # window_full_range = (0, len(waveforms["SWDO"].index) - 1)

        signal = "SWDO"
        net = "Host " + signal
        high_level = self.voltage
        low_level = 0

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window_addr_drive, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_addr_drive, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window_addr_drive, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_addr_drive, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # item = "Low-Period Time"
        # measurement = f"{net} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_device_drive[signal], "low", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")
        #
        # item = "High-Period Time"
        # measurement = f"{net} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_device_drive[signal], "high", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_device_drive[signal], "min", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_device_drive[signal], "max", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_device_drive[signal], "rising")
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_device_drive[signal], "falling")
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:STA"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:STA", window_addr_drive)
            results[measurement] = self.process_results("Host SWDO", "tHD:STA", measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # item = "tSU:STO"
        # measurement = f"{net} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:STO", window_addr_drive)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", window_addr_drive)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", window_addr_drive)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_device(self, waveforms, edges_map):
        """Suite of calculations for device-side specifications."""
        results = OrderedDict()
        attempted_measurements = []

        window_addr_drive = self.get_byte_range_from_edges(edges_map, "data")
        edges_device_drive = self.get_edges_within_byte_range(edges_map, window_addr_drive)

        signal = "SWDO"
        net = "Slave " + signal
        high_level = self.voltage
        low_level = 0

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window_addr_drive, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_addr_drive, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window_addr_drive, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_addr_drive, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # item = "Low-Period Time"
        # measurement = f"{net} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_device_drive[signal], "low", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")
        #
        # item = "High-Period Time"
        # measurement = f"{net} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_device_drive[signal], "high", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_device_drive[signal], "min", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_device_drive[signal], "max", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_device_drive[signal], "rising")
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_device_drive[signal], "falling")
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", window_addr_drive)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", window_addr_drive)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_default(self, waveforms, edges_map):
        """Suite of calculations for device-side specifications."""
        results = OrderedDict()
        attempted_measurements = []

        window_full_range = (0, len(waveforms["SWDO"].index) - 1)

        signal = "SWDO"
        net = "Host " + signal
        high_level = self.voltage
        low_level = 0

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window_full_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window_full_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # item = "Low-Period Time"
        # measurement = f"{signal} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")
        #
        # item = "High-Period Time"
        # measurement = f"{signal} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", high_level)
        #     results[measurement] = self.process_results(net, item, measured_value, True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal=net)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", window_full_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", window_full_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["SWCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    def get_ack_filtered_edges(self, waveforms: dict[str: pd.DataFrame], edges_map: dict[str: list]):
        """For a list of edges, remove the edges that are caused by ACK pulses.
        """
        ack_blank_periods = self.get_ack_blank_periods(waveforms, edges_map)
        new_edges_map = {
            "SWCLK": edges_map["SWCLK"],
            "SWDO": [],
        }
        for e in edges_map["SWDO"]:
            if any([period[0] <= e[0] <= period[1] for period in ack_blank_periods]):
                self.logger.debug(f"Discarding edge (ACK turnaround: {e}")
                continue
            new_edges_map["SWDO"].append(e)
        return new_edges_map

    def get_ack_blank_periods(self, waveforms, edges_map):
        """Get the time index ranges in array with (start, stop) of ACK pulses.
        Used to ignore ACK turnaround windows that can be misinterpreted as data edges
        """
        SWCLK_counter = 0
        ack_blank_periods = []
        for i in range(len(edges_map["SWCLK"]) - 1):
            e = edges_map["SWCLK"][i]
            next_e = edges_map["SWCLK"][i + 1]
            if e[1] == "VIL_FALL":
                SWCLK_counter += 1
                blank = (e[0], next_e[0])
                # verify that SWDO is an inconsequential pulse in this window (starts and ends at low voltage)
                if (waveforms["SWDO"]['v'][blank[0]] < self.limits["Host SWDO High-Level Voltage"]["Upper Limit"] and
                        waveforms["SWDO"]['v'][blank[1]] < self.limits["Host SWDO High-Level Voltage"]["Lower Limit"]):
                    ack_blank_periods.append(blank)
        return ack_blank_periods

    def get_edges_within_byte_range(self, edges_map, byte_range_idx):  # NOQA
        """Filter edges from an edges map data structure within a time index range."""
        return {signal: [e for e in edges if byte_range_idx[0] <= e[0] <= byte_range_idx[1]] for signal, edges in edges_map.items()}

    @staticmethod
    def get_byte_range_from_edges(edges_map: dict, byte_select: str):
        """Get the time index range of a particular byte range of the SWD protocol
        Used as a time filter window to pull the relevant waveform of a specific SWD state (i.e. host driving the bus, device driving the bus)

        Arguments:
        edges_map -- Dictionary of edge data {"SWCLK": [edges], "SWDO": [edges]}
        byte_select -- String for SWD bus state to window

        Returns:
        [start time index, stop time index]
        Uses the array indices from original waveform dataframe.
        """

        # validate command
        if byte_select not in ["addr_drive", "data"]:
            raise Exception(f"[SWDAnalyzer]: Invalid byte selection range {byte_select}")

        # initialize return value
        byte_range_idx = [0, 0]
        if byte_select == "addr_drive":
            byte_range_idx[0] = edges_map["SWCLK"][0][0]
            counter = 0
            for e in edges_map["SWCLK"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == 1 + 1 + 1 + 2 + 1 + 1 + 1:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1
        elif byte_select == "data":
            counter = 1
            start_edge = 1 + 1 + 1 + 2 + 1 + 1 + 1 + 3 + 1
            stop_edge = start_edge + 31
            for e in edges_map["SWCLK"]:
                if e[1] != "VIH_FALL":
                    continue
                if counter == start_edge:
                    byte_range_idx[0] = e[0]
                elif counter == stop_edge:
                    byte_range_idx[1] = e[0]
                    break
                counter += 1

        # verify a window has been found
        if byte_range_idx[0] == 0 or byte_range_idx[1] == 0:
            raise Exception(f"[SWDAnalyzer]: Cannot find window for {byte_select}")

        return byte_range_idx

    def get_edges_within_byte_range(self, edges_map, byte_range_idx):  # NOQA
        """Filter edges from an edges map data structure within a time index range."""
        return {
            signal: [
                e for e in edges if byte_range_idx[0] <= e[0] <= byte_range_idx[1]
            ] for signal, edges in edges_map.items()
        }

    def find_delta_time(self, waveforms, edges_map, mode: Literal["tHD:STA", "tSU:STO", "tSU:DAT", "tHD:DAT"], input_window):
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
            e1_signal = "SWCLK"
            e2_signal = "SWDO"
            # first SWDO falling edge
            e1 = self.filter_edges(edges_map, input_window, e1_signal, "VIH_FALL")[0]
            # first SWCLK falling edge
            e2 = self.filter_edges(edges_map, input_window, e2_signal, "VIH_FALL")[0]
        elif mode == "tSU:DAT":
            e1_signal = "SWDO"
            e2_signal = "SWCLK"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e1_rise = self.filter_edges(edges_map, input_window, e1_signal, "VIH_RISE")
            e1_fall = self.filter_edges(edges_map, input_window, e1_signal, "VIL_FALL")
            e1s = e1_rise + e1_fall
            if len(e1s) == 0:
                raise Exception(f"[Analyzer]: Cannot find reference SWDO edge for tSU:DAT")
            # next SWCLK rising edge(s)
            e2s = [self.get_next_edge(e1[0], self.filter_edges(edges_map, input_window, e2_signal, "VIH_FALL")) for e1 in e1s]
            for i in range(len(e2s)):
                if e2s[i] is None:
                    e1s[i] = None

            for i in range(e2s.count(None)):
                e1s.remove(None)
                e2s.remove(None)

            edges_zip = list(zip(e1s, e2s))
            e1, e2 = min(edges_zip, key=lambda e: waveforms[e2_signal]["t"].iloc[e[1][0]] - waveforms[e1_signal]["t"].iloc[e[0][0]])
        elif mode == "tHD:DAT":
            e1_signal = "SWCLK"
            e2_signal = "SWDO"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e2_rise = self.filter_edges(edges_map, input_window, e2_signal, "VIL_RISE")
            e2_fall = self.filter_edges(edges_map, input_window, e2_signal, "VIH_FALL")
            e2s = e2_rise + e2_fall
            if len(e2s) == 0:
                raise Exception(f"[Analyzer]: Cannot find reference SWDO edge for tHD:DAT")
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

        window[0] = e1[0]
        x_markers.append(e1[0])
        e1_time = waveforms[e1_signal]['t'].iloc[e1[0]]

        window[1] = e2[0]
        x_markers.append(e2[0])
        e2_time = waveforms[e2_signal]['t'].iloc[e2[0]]

        result = e2_time - e1_time
        return self.pad_window(waveforms["SWCLK"], window, PLOT_TIMING_MARGIN), x_markers, result

    def filter_edges(self, edges_map, input_window, signal, edge_spec):
        """Create a list of edges in edges_map within the given window that match the given level (VIH/VIL) and direction (RISE/FALL)"""
        return [e for e in edges_map[signal] if e[1] == edge_spec and self.is_index_in_window(e[0], input_window)]
