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
    "CLK": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "DATA": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
}
# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8
PLOT_EDGE_MARGIN = 50
PLOT_TIMING_MARGIN = 200


class PDMAnalyzer(Analyzer):
    """
    Analyzes the PDM bus signals on both CLK and DATA.
    """
    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)
        data_side = self.config.Analysis.Configuration["Data Side"]
        self.data_num = 2 if data_side == "LR" else 1
        self.data_edge = "rising" if "L" in data_side else "falling"

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # crop the waveform to within the analyzed data range
        min_edge_index, max_edge_index = self.pad_window(waveforms["CLK"],
                                                         [edges_map["CLK"][0][0], edges_map["CLK"][-1][0]], CROP_MARGIN_SAMPLES)
        for signal, waveform in waveforms.items():
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]

        # perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        results.update(self.analyze_data_clk(waveforms, edges_map))
        if self.data_num == 2 or self.data_edge == "rising":
            results.update(self.analyze_data_rising_edge(waveforms, edges_map))
        if self.data_num == 2 or self.data_edge == "falling":
            results.update(self.analyze_data_falling_edge(waveforms, edges_map))

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

        time_gap = max_t - min_t
        plt.xlabel('Time')
        plt.ylabel('Voltage')
        # Place horizontal gridlines / ticks at important voltages according to signal being processed
        plt.yticks([-Y_AXIS_MARGIN, 0,
                    self.limits["CLK Low-Level Voltage"]["Upper Limit"], self.limits["CLK High-Level Voltage"]["Lower Limit"],
                    self.voltage, self.voltage + Y_AXIS_MARGIN])
        plt.axis((min_t, max_t, -Y_AXIS_MARGIN * 2, self.voltage + Y_AXIS_MARGIN * 2))
        # Restrict axis scale to seconds, milliseconds, data roseconds, nanoseconds where applicable
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
        waveforms["CLK"].plot(kind="line", x="t", y="v", ax=ax, color=color_map["CLK"], legend=True, linewidth=PLOT_LINE_WIDTH, label='CLK')
        data_offset = waveforms["DATA"].copy()
        data_offset["v"] = waveforms["DATA"]["v"] + self.voltage + .1
        data_offset.plot(kind="line", x="t", y="v", ax=ax, color=color_map["DATA"], legend=True, linewidth=PLOT_LINE_WIDTH, label='DATA')
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

    def analyze_data_clk(self, waveforms, edges_map):

        results = OrderedDict()
        attempted_measurements = []

        window_full_range = (0, len(waveforms["CLK"].index) - 1)
        high_level = self.voltage
        low_level = 0

        signal = "CLK"
        item = "Frequency"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        freq = 0
        try:
            window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
            freq = measured_value
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

        item = "Low-Duty Cycle"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", low_level)
            results[measurement] = self.process_results(signal, item, measured_value/(1/freq), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "High-Duty Cycle"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", high_level)
            results[measurement] = self.process_results(signal, item, measured_value/(1/freq), True)
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

        signal = "DATA"
        item = "Transaction Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_transaction_delta_time(waveforms, edges_map)
            results[measurement] = self.process_results(signal, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal, "CLK"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_rising_edge(self, waveforms, edges_map):

        if not self.substring_present(edges_map.get("CLK", []), "RISE", position=1):
            raise Exception(f"Error: CLK RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        results = OrderedDict()
        attempted_measurements = []

        signal = "DATA"
        net = "Left DATA"

        high_level = self.voltage * 0.7
        low_level = self.voltage * 0.3
        edges_range = self.find_transaction(waveforms, edges_map, "rising")
        window_full_range = (0, len(waveforms["DATA"].index) - 1)

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_data_high_level_voltage(waveforms[signal], edges_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_data_low_level_voltage(waveforms[signal], edges_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            low_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "High-Period Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_period(waveforms[signal], edges_map[signal], "high", high_level, edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Period Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_period(waveforms[signal], edges_map[signal], "low", high_level, edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_data_edge_overshoot(waveforms[signal], edges_map[signal], "min", net, edges_range)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_data_edge_overshoot(waveforms[signal], edges_map[signal], "max", net, edges_range)
            results[measurement] = self.process_results(net, item, abs(measured_value) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_edge_rate(waveforms[signal], edges_map[signal], "rising", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_edge_rate(waveforms[signal], edges_map[signal], "falling", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", "rising", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["CLK", "DATA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", "rising", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["CLK", "DATA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_falling_edge(self, waveforms, edges_map):

        if not self.substring_present(edges_map.get("CLK", []), "FALL", position=1):
            raise Exception(f"Error: CLK RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        results = OrderedDict()
        attempted_measurements = []

        signal = "DATA"
        net = "Right DATA"

        high_level = self.voltage * 0.7
        low_level = self.voltage * 0.3
        edges_range = self.find_transaction(waveforms, edges_map, "falling")
        window_full_range = (0, len(waveforms["DATA"].index) - 1)

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_data_high_level_voltage(waveforms[signal], edges_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_data_low_level_voltage(waveforms[signal], edges_range, signal=net)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            low_level = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "High-Period Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_period(waveforms[signal], edges_map[signal], "high", high_level, edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Period Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_period(waveforms[signal], edges_map[signal], "low", high_level, edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_data_edge_overshoot(waveforms[signal], edges_map[signal], "min", net, edges_range)
            results[measurement] = self.process_results(net, item, abs(measured_value - low_level) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_data_edge_overshoot(waveforms[signal], edges_map[signal], "max", net, edges_range)
            results[measurement] = self.process_results(net, item, abs(measured_value - high_level) / (high_level - low_level), True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_edge_rate(waveforms[signal], edges_map[signal], "rising", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_data_edge_rate(waveforms[signal], edges_map[signal], "falling", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT", "falling", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["CLK", "DATA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT", "falling", edges_range)
            results[measurement] = self.process_results(net, item, measured_value, True)
            self.plot_scope_shot(measurement, waveforms, ["CLK", "DATA"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    @staticmethod
    def substring_present(edges_list, substring, position=1):
        """Takes in a list of tuples and checks if any tuple in the list includes the provided substring in the given position"""
        present = False
        for edge in edges_list:
            if substring in edge[position]:
                present = True
                break

        return present

    @staticmethod
    def find_transaction(waveforms, edges_map, edge: Literal["rising", "falling"]):
        if edge not in ["rising", "falling"]:
            raise Exception(f"[PDMAnalyzer]: transaction edge not found: {edge}")

        start_edge = "VIL_RISE"
        end_edge = "VIH_RISE"
        if edge == "falling":
            start_edge = "VIH_FALL"
            end_edge = "VIL_FALL"

        # 获取CLK的所有位置
        clk_start_indices = [e[0] for e in edges_map['CLK'] if e[1] == start_edge]
        clk_start_times = [waveforms['CLK']['t'].iloc[i] for i in clk_start_indices]
        clk_end_indices = [e[0] for e in edges_map['CLK'] if e[1] == end_edge]
        clk_end_times = [waveforms['CLK']['t'].iloc[i] for i in clk_end_indices]
        if len(clk_start_times) < 1 or len(clk_end_times) < 1:
            raise Exception("[PDMAnalyzer]: Edges not found for CLK single transaction window!")
        clk_start_times = sorted(clk_start_times, key=lambda x: x)
        clk_end_times = sorted(clk_end_times, key=lambda x: x)

        # 获取DATA的所有变化位置
        data_start_indices = [e[0] for e in edges_map['DATA'] if e[1] == "VIL_RISE"]
        data_start_times = [waveforms['DATA']['t'].iloc[i] for i in data_start_indices]
        data_end_indices = [e[0] for e in edges_map['DATA'] if e[1] == "VIL_FALL"]
        data_end_times = [waveforms['DATA']['t'].iloc[i] for i in data_end_indices]
        if len(data_start_times) < 1 or len(data_end_times) < 1:
            raise Exception("[PDMAnalyzer]: Edges not found for single transaction window!")
        data_start_times = sorted(data_start_times, key=lambda x: x)
        data_end_times = sorted(data_end_times, key=lambda x: x)
        # 获取单个DATA的最小时间（1 bit的时间）
        min_deta_time = 100000000
        for index, start_time in enumerate(data_start_times[1:-1]):
            end_last_time = data_end_times[index - 1]
            deta = abs(end_last_time - start_time)
            if min_deta_time > deta:
                min_deta_time = deta
            end_next_time = data_end_times[index + 1]
            deta = abs(end_next_time - start_time)
            if min_deta_time > deta:
                min_deta_time = deta

        transaction_indices = []

        # 获取CLK对应下面的DATA的所有位置
        offset_time = min_deta_time / 2 * 1.3
        for index, start_time in enumerate(clk_start_times):
            end_time = clk_end_times[index]
            data_start_time = start_time - offset_time
            data_end_time = end_time + offset_time
            transaction_indices.append((data_start_time, data_end_time))

        return transaction_indices

    def find_data_high_level_voltage(self, waveform: pd.DataFrame, window, signal: str):
        filtered_v = pd.DataFrame()
        for start, end in window:
            data = waveform[
                (waveform["t"] >= start) & (waveform["t"] <= end) &
                (waveform["v"] > self.limits[f"{signal} Low-Level Voltage"]["Upper Limit"])
                ]
            filtered_v = pd.concat([filtered_v, data], ignore_index=True)
        # take the mean in case more than one value occurs the most
        mode = filtered_v[["v"]].mode().v.mean()
        return mode

    def find_data_low_level_voltage(self, waveform: pd.DataFrame, window, signal: str):
        filtered_v = pd.DataFrame()
        for start, end in window:
            data = waveform[
                (waveform["t"] >= start) & (waveform["t"] <= end) &
                (waveform["v"] < self.limits[f"{signal} Low-Level Voltage"]["Upper Limit"])
                ]
            filtered_v = pd.concat([filtered_v, data], ignore_index=True)
        # take the mean in case more than one value occurs the most
        mode = filtered_v[["v"]].mode().v.mean()
        return mode

    def find_data_period(self, waveform, edges, mode: Literal["low", "high"], high_level, in_window):
        """Calculate waveform period from found edges, assuming the edges are periodic."""
        if mode not in ["low", "high"]:
            raise Exception(f"[PDMAnalyzer]: Period mode not found: {mode}")

        low = mode == "low"
        period = None
        min_period = None
        min_index = 0
        for i, edge in enumerate(edges[5:-4]):
            if low:
                if not ("VIL_FALL" in edge[1] and "VIL_RISE" in edges[i + 6][1]):
                    continue
                if max(waveform['v'].loc[edges[i + 3][0]:edges[i + 5][0]]) < high_level or max(
                        waveform['v'].loc[edges[i + 6][0]:edges[i + 8][0]]) < high_level:
                    continue
            else:
                if not ("VIH_RISE" in edge[1] and "VIH_FALL" in edges[i + 6][1]):
                    continue
                if max(waveform['v'].loc[edge[0]:edges[i + 6][0]]) < high_level:
                    continue
            t2 = waveform['t'].iloc[edges[i + 6][0]]
            t1 = waveform['t'].iloc[edge[0]]
            in_edge_range = False
            for start, end in in_window:
                if not (start <= (t2 + t1) / 2 <= end):
                    continue
                in_edge_range = True
            if not in_edge_range:
                continue
            period = t2 - t1
            if min_period is None:
                min_period = period
            else:
                if period < min_period:
                    min_period = period
                    min_index = i
        if min_period is None:
            raise Exception("[PDMAnalyzer]: No low period found!")
        else:
            x_markers = [edges[min_index + 5][0], edges[min_index + 6][0]]
            window = self.pad_window(waveform, (edges[min_index + 5][0], edges[min_index + 6][0]), PLOT_EDGE_MARGIN)
        return window, x_markers, period

    def find_data_edge_overshoot(self, waveform, edges, mode: Literal["min", "max"], signal: str, in_window):
        """Calculate overshoot / undershoot for an edge."""
        if mode not in ["min", "max"]:
            raise Exception(f"[PDMAnalyzer]: Peak mode not found: {mode}")
        min_mode = mode == "min"
        peak_val = None
        peak_window = None
        if min_mode:
            filtered_edges = [e[0] for e in edges if e[1] == "VIL_FALL"]
        else:
            filtered_edges = [e[0] for e in edges if e[1] == "VIH_RISE"]

        filtered_times = []
        for filtered_time in [waveform['t'].iloc[i] for i in filtered_edges]:
            for start, end in in_window:
                if not (start <= filtered_time <= end):
                    continue
                filtered_times.append(filtered_time)

        # Loop over all falling/rising edges to find the worst under/overshoot
        for i in filtered_edges:
            window = self.pad_window(waveform, [i, i], PLOT_EDGE_MARGIN * 5)
            idx, val = self.find_peak_voltage(waveform, window, mode)
            if peak_val is None or (mode == "min" and val < peak_val) or (mode == "max" and val > peak_val):
                peak_val = val
                peak_window = window
        if peak_val is None:
            window = self.pad_window(waveform, [0, len(waveform["v"])], PLOT_EDGE_MARGIN * 5)
            peak_val = self.find_high_level_voltage(waveform, window, signal)
            for val in waveform["v"]:
                if (mode == "min" and val < peak_val) or (mode == "max" and val > peak_val):
                    peak_val = val
                    peak_window = window
        if peak_val is None:
            raise Exception(f"[PDMAnalyzer]: Edge peak mode not found: {mode}")
        if min_mode:
            final = self.find_low_level_voltage(waveform, peak_window, signal)
        else:
            final = self.find_high_level_voltage(waveform, peak_window, signal)
        return peak_window, (peak_val, final), peak_val - final

    def find_data_edge_rate(self, waveform, edges, mode: Literal["falling", "rising"], in_window):
        """Calculate edge rate."""
        if mode not in ["falling", "rising"]:
            raise Exception(f"[PDMAnalyzer]: Edge rate mode not found: {mode}")
        falling = mode == "falling"
        t_delta = None
        index = None
        x_markers = None
        margin = PLOT_EDGE_MARGIN
        for i, edge in enumerate(edges[5:-4]):
            if falling:
                if not ("VIH_FALL" in edge[1] and "VIL_FALL" in edges[i + 6][1]):
                    continue
            else:
                if not ("VIL_RISE" in edge[1] and "VIH_RISE" in edges[i + 6][1]):
                    continue
            t2 = waveform['t'].iloc[edges[i + 6][0]]
            t1 = waveform['t'].iloc[edge[0]]
            in_edge_range = False
            for start, end in in_window:
                if t1 < start or t2 > end or t1 > end or t2 < start:
                    continue
                in_edge_range = True
            if not in_edge_range:
                raise Exception("[PDMAnalyzer]: No low period found!")
            x_markers = [edge[0], edges[i + 6][0]]
            t_delta = t2 - t1
            # get padding margin value
            margin = PLOT_EDGE_MARGIN
            x_delta = abs(x_markers[1] - x_markers[0])
            if x_delta != 0:
                # scale  margin by an integer. The rise/fall time * this integer is the padding value
                margin = x_delta * 4
            index = edge[0]
            break
        if index is None:
            raise Exception(f"[PDMAnalyzer]: No {mode} edge found!")
        return self.pad_window(waveform, [x_markers[0], x_markers[1]], margin), x_markers, t_delta

    def find_delta_time(self, waveforms, edges_map, mode: Literal["tSU:DAT", "tHD:DAT"], clk_mode: Literal["falling", "rising"], input_window):
        """Calculate delta time between specific edges, based on  spec definition."""

        if mode not in ["tSU:DAT", "tHD:DAT"]:
            raise Exception(f"[PDMAnalyzer]: Delta time mode not found: {mode}")

        window = [0, 0]
        x_markers = []

        e1_signal = ""
        e2_signal = ""
        e1 = None
        e2 = None
        if mode == "tSU:DAT":
            e1_signal = "DATA"
            e2_signal = "CLK"
            clk_edge = "VIL_RISE" if clk_mode == "rising" else "VIH_FALL"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e1_rise = self.filter_edges(waveforms, edges_map, input_window, e1_signal, "VIH_RISE")
            e1_fall = self.filter_edges(waveforms, edges_map, input_window, e1_signal, "VIL_FALL")
            e1s = e1_rise + e1_fall
            if len(e1s) == 0:
                raise Exception(f"[PDMAnalyzer]: Cannot find reference DATA edge for tSU:DAT")
            # next CLK rising edge(s)
            e2s = [self.get_next_edge(e1[0], self.filter_edges(waveforms, edges_map, input_window, e2_signal, clk_edge)) for e1 in e1s]
            for i in range(len(e2s)):
                if e2s[i] is None:
                    e1s[i] = None

            for i in range(e2s.count(None)):
                e1s.remove(None)
                e2s.remove(None)

            edges_zip = list(zip(e1s, e2s))
            e1, e2 = min(edges_zip, key=lambda e: waveforms[e2_signal]["t"].iloc[e[1][0]] - waveforms[e1_signal]["t"].iloc[e[0][0]])
        elif mode == "tHD:DAT":
            e1_signal = "CLK"
            e2_signal = "DATA"
            clk_edge = "VIH_RISE" if clk_mode == "rising" else "VIL_FALL"
            # Use all rising and falling edges, and take the worst (shorter time) measurement of them all
            e2_rise = self.filter_edges(waveforms, edges_map, input_window, e2_signal, "VIL_RISE")
            e2_fall = self.filter_edges(waveforms, edges_map, input_window, e2_signal, "VIH_FALL")
            e2s = e2_rise + e2_fall
            if len(e2s) == 0:
                raise Exception(f"[PDMAnalyzer]: Cannot find reference DATA edge for tHD:DAT")
            # previous CLK rising edge(s)
            e1s = [self.get_previous_edge(e2[0], self.filter_edges(waveforms, edges_map, input_window, e1_signal, clk_edge)) for e2 in e2s]
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
        return self.pad_window(waveforms["CLK"], window, PLOT_TIMING_MARGIN), x_markers, result

    @staticmethod
    def filter_edges(waveforms, edges_map, in_window, signal, edge_spec):
        """Create a list of edges in edges_map within the given window that match the given level (VIH/VIL) and direction (RISE/FALL)"""
        edges = []
        for e in edges_map[signal]:
            if e[1] == edge_spec:
                filtered_time = waveforms[signal]['t'].iloc[e[0]]
                in_edge_range = False
                for start, end in in_window:
                    if filtered_time < start or filtered_time > end:
                        continue
                    in_edge_range = True
                if not in_edge_range:
                    continue
                edges.append(e)
        return edges

    def find_transaction_delta_time(self, waveforms, edges_map):

        window = [0, 0]
        x_markers = []

        # 先获取区间
        rising_full_range = self.find_transaction(waveforms, edges_map, "rising")
        rising_range = []  # 只要右边的区间
        for start, end in rising_full_range:
            rising_range.append(((start + end) / 2, end))
        falling_full_range = self.find_transaction(waveforms, edges_map, "falling")
        falling_range = []  # 只要右边的区间
        for start, end in falling_full_range:
            falling_range.append(((start + end) / 2, end))
        clk_range = (0, len(waveforms["CLK"].index) - 1)

        # 获取left data 到clk falling的最大time
        clk_edge = "VIH_FALL"
        e1_rise = self.filter_edges(waveforms, edges_map, rising_range, "DATA", "VIH_RISE")
        e1_fall = self.filter_edges(waveforms, edges_map, rising_range, "DATA", "VIH_FALL")
        e1s = e1_rise + e1_fall
        if len(e1s) == 0:
            raise Exception(f"[PDMAnalyzer]: Cannot find reference DATA edge for rising clk")
        e2s = [self.get_next_edge(e1[0], self.filter_full_edges(edges_map, clk_range, "CLK", clk_edge)) for e1 in e1s]
        for i in range(len(e2s)):
            if e2s[i] is None:
                e1s[i] = None

        for i in range(e2s.count(None)):
            e1s.remove(None)
            e2s.remove(None)

        edges_zip = list(zip(e1s, e2s))
        e1, e2 = max(edges_zip, key=lambda e: abs(waveforms["CLK"]["t"].iloc[e[1][0]] - waveforms["DATA"]["t"].iloc[e[0][0]]))

        window[0] = e1[0]
        x_markers.append(e1[0])
        e1_time = waveforms["DATA"]['t'].iloc[e1[0]]

        window[1] = e2[0]
        x_markers.append(e2[0])
        e2_time = waveforms["CLK"]['t'].iloc[e2[0]]

        left_data_delta_time = e2_time - e1_time

        # 获取right data 到clk rising的最大time
        clk_edge = "VIH_RISE"
        e1_rise = self.filter_edges(waveforms, edges_map, falling_range, "DATA", "VIH_RISE")
        e1_fall = self.filter_edges(waveforms, edges_map, falling_range, "DATA", "VIH_FALL")
        e1s = e1_rise + e1_fall
        if len(e1s) == 0:
            raise Exception(f"[PDMAnalyzer]: Cannot find reference DATA edge for falling clk")
        e2s = [self.get_next_edge(e1[0], self.filter_full_edges(edges_map, clk_range, "CLK", clk_edge)) for e1 in e1s]
        for i in range(len(e2s)):
            if e2s[i] is None:
                e1s[i] = None

        for i in range(e2s.count(None)):
            e1s.remove(None)
            e2s.remove(None)

        edges_zip = list(zip(e1s, e2s))
        e1, e2 = max(edges_zip,
                     key=lambda e: abs(waveforms["CLK"]["t"].iloc[e[1][0]] - waveforms["DATA"]["t"].iloc[e[0][0]]))
        if window[0] > e1[0]:
            window[0] = e1[0]
        x_markers.append(e1[0])
        e1_time = waveforms["DATA"]['t'].iloc[e1[0]]

        if window[1] < e2[0]:
            window[1] = e2[0]
        x_markers.append(e2[0])
        e2_time = waveforms["CLK"]['t'].iloc[e2[0]]

        right_data_delta_time = e2_time - e1_time

        result = abs(right_data_delta_time - left_data_delta_time)
        return self.pad_window(waveforms["CLK"], window, PLOT_TIMING_MARGIN + 100), x_markers, result

    def filter_full_edges(self, edges_map, input_window, signal, edge_spec):
        """Create a list of edges in edges_map within the given window that match the given level (VIH/VIL) and direction (RISE/FALL)"""
        return [e for e in edges_map[signal] if e[1] == edge_spec and self.is_index_in_window(e[0], input_window)]
