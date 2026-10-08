#!/usr/bin/env python
# -*- coding: utf-8 -*-

import logging
import traceback
from collections import OrderedDict
from pathlib import Path

import matplotlib
import pandas as pd
from matplotlib import pyplot as plt, gridspec

from .Analyzer import Analyzer
from ..setting import SetupData

# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8

# color map for plotting
color_map = (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0)


class OneWireAnalyzer(Analyzer):

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)
        self.test_mode = str(self.config.Analysis.Configuration["mode"])
        self.test_name = str(self.config.Analysis.Configuration["direction"])

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # crop the waveform to within the analyzed data range
        signal = list(waveforms.keys())[0]
        min_edge_index, max_edge_index = self.pad_window(waveforms[signal],
                                                         (edges_map[signal][0][0], edges_map[signal][-1][0]),
                                                         CROP_MARGIN_SAMPLES)
        for signal, waveform in waveforms.items():
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]

        # perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        results.update(self.analyze_signals(waveforms, edges_map))

        file_name = self.data_dir / "Measurement Data.xlsx"
        results_df = pd.DataFrame(results).T.apply(self.safe_to_numeric)
        results_df = results_df.round(3)[["Net", "Measurement", "Lower Limit", "Lower Warning", "Measured Value", "Upper Warning", "Upper Limit", "Unit", "Result", "Link"]].sort_index()
        results_df.to_excel(file_name, index=False)

        self.convertToWorkbook()
        return results_df

    def analyze_signals(self, waveforms: dict, edges_map: dict):
        """Suite of calculations for host-side specifications.
        Waived calculations due to challenges in acquiring proper scope capture: tSU:STA, tVD:ACK, bus free time.
        """
        results = OrderedDict()
        attempted_measurements = []

        high_level_voltage = self.voltage
        low_level_voltage = 0.0

        signal = "OneWire"
        window_full_range = (0, len(waveforms[signal].index) - 1)

        measurement = "High-Level Voltage"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window_full_range, signal)
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            high_level_voltage = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Low-Level Voltage"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window_full_range, signal)
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
            low_level_voltage = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Absolute Max Voltage"
        attempted_measurements.append(measurement)
        try:
            idx, measured_value = self.find_peak_voltage(waveforms[signal], window_full_range, 'max')
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Absolute Min Voltage"
        attempted_measurements.append(measurement)
        try:
            idx, measured_value = self.find_peak_voltage(waveforms[signal], window_full_range, 'min')
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window_full_range, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Overshoot"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal)
            results[measurement] = self.process_results("OneWire", measurement, abs(measured_value) / (high_level_voltage - low_level_voltage), limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Undershoot"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal)
            results[measurement] = self.process_results("OneWire", measurement, abs(measured_value) / (high_level_voltage - low_level_voltage), limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Rise Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        measurement = "Fall Time"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results("OneWire", measurement, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        results = self.check_results(signal, attempted_measurements, results)

        frequency = 0
        if self.config.Analysis.Configuration["frequency"]:
            measurement = "Frequency"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
                results[measurement] = self.process_results("OneWire", measurement, measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        if self.config.Analysis.Configuration["width"]:
            measurement = "Width-"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", (high_level_voltage + low_level_voltage) / 2)
                results[measurement] = self.process_results("OneWire", measurement, measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = "Width+"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", (high_level_voltage + low_level_voltage) / 2)
                results[measurement] = self.process_results("OneWire", measurement, measured_value, True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        if self.config.Analysis.Configuration["duty"]:
            measurement = "Duty-"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", (high_level_voltage + low_level_voltage) / 2)
                results[measurement] = self.process_results("OneWire", measurement, measured_value / (1 / frequency), True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            measurement = "Duty+"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", (high_level_voltage + low_level_voltage) / 2)
                results[measurement] = self.process_results("OneWire", measurement, measured_value / (1 / frequency), True)
                self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        return results

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
        voltage = float(str(self.config.Analysis.Configuration["voltage"]).lower().replace("v", ""))
        plt.yticks([-Y_AXIS_MARGIN, 0,
                    self.limits[f"OneWire Low-Level Voltage"]["Upper Limit"], self.limits[f"OneWire High-Level Voltage"]["Lower Limit"],
                    voltage, voltage + Y_AXIS_MARGIN])
        plt.axis((min_t, max_t, -Y_AXIS_MARGIN * 2, voltage + Y_AXIS_MARGIN * 2))
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
        waveforms[signals[0]].plot(kind="line", x="t", y="v", ax=ax, color=color_map, legend=False, grid=True, linewidth=PLOT_LINE_WIDTH)
        ax.set_xlabel(f"Time ({time_scale})")

        # plot the measurement markers
        color = (233.0 / 255.0, 135.0 / 255.0, 121.0 / 255.0)
        if x_markers:
            for i in x_markers:
                marker = waveforms[signals[0]]['t'].iloc[i]
                plt.plot([marker, marker], [-Y_AXIS_MARGIN * 2, voltage + Y_AXIS_MARGIN * 2], color=color, linestyle="--", linewidth=MARKER_LINE_WIDTH)
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
        ax = plt.subplot(gs[1])  # NOQA
        waveforms[signals[0]].plot(kind="line", x="t", y="v", ax=ax, color=color_map, legend=True, linewidth=PLOT_LINE_WIDTH, label=signals[0])
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
