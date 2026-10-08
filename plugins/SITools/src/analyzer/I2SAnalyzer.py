import traceback
from collections import OrderedDict
from typing import Literal

import numpy as np
import pandas as pd
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec  # NOQA

import logging
from pathlib import Path

from .Analyzer import Analyzer
from ..setting import SetupData

# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8
PLOT_EDGE_MARGIN = 200
PLOT_TIMING_MARGIN_LONG_MULTIPLIER = 3
ANALYSIS_WINDOW_SCALE = 2

# color map for plotting
color_map = {
    "BCLK": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "DIN": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
    "DOUT": (252.0 / 255.0, 130 / 255.0, 130.0 / 255.0),
    "LRCLK": (130.0 / 255.0, 130.0 / 255.0, 252.0 / 255.0),
}


class I2SAnalyzer(Analyzer):
    """
    Analyzes the SPI bus signals on LRCLK, BCLK, DOUT, and DIN.
    """
    plot_timing_margin = 400

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)
        self.test_mode = str(self.config.Analysis.Configuration["mode"])
        self.test_name = str(self.config.Analysis.Configuration["direction"])

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # Search each channel_map for the signal LRCLK; if any channel has the signal, use for analysis
        # Make sure that if LRCLK is present it has both a falling and rising edge (VIH_FALL, VIL_FALL, VIL_RISE, VIH_RISE)
        if "LRCLK" in edges_map.keys() and waveforms["LRCLK"]:
            lrclk_rise = self.substring_present(edges_map.get("LRCLK", []), "RISE", position=1)
            lrclk_fall = self.substring_present(edges_map.get("LRCLK", []), "FALL", position=1)

            if (lrclk_rise or lrclk_fall) and not (lrclk_rise and lrclk_fall):
                self.logger.warning("[I2SAnalyzer::analyze_data] WARNING LRCLK present but could not find both rising and "
                                    "falling edge. Check scope to confirm LRCLK is pulled low and then high."
                                    " Also check config to make sure VIL_CS < VIH_CS")

        # Check that we are only using waveforms with edges
        keys = [s for s, _ in waveforms.items() if edges_map.get(s, []) != []]
        if not keys:
            self.logger.critical(f"CRITICAL: No edges in {edges_map}. Check scope capture to make sure traffic is present")
            raise Exception("No edges found. Check scope screen to make sure traffic is present.")
        # Crop the waveform to the first and last edges across all signals
        first_edge = min([edges_map[k][0][0] for k in keys])
        last_edge = max([edges_map[k][-1][0] for k in keys])

        # Waveform argument is just to check if a window+padding exceeds bounds; can use any signal as they should be
        # all the same length. Using BCLK since it should always be present
        min_edge_index, max_edge_index = self.pad_window(waveforms["BCLK"],
                                                         (first_edge, last_edge), CROP_MARGIN_SAMPLES)

        for signal, waveform in waveforms.items():
            # Crop the waveform, shifting all indices such that the first sample in the cropped waveform is at index 0
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            # Shift the edge indices as well, cutting off edges that were cropped out
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal] if i <= max_edge_index]

        # Perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing I2S data...")
        results = OrderedDict()
        if "DIN" in edges_map.keys() and waveforms["DIN"]:
            if self.substring_present(edges_map.get("DIN", []), "RISE", position=1):
                try:
                    results.update(self.analyze_data_din_rise(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for DIN RISE failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(f"WARNING: DIN RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

            if self.substring_present(edges_map.get("DIN", []), "FALL", position=1):
                try:
                    results.update(self.analyze_data_din_fall(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for DIN FALL failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(f"WARNING: DIN FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if "DOUT" in edges_map.keys() and waveforms["DOUT"]:
            if self.substring_present(edges_map.get("DOUT", []), "FALL", position=1):
                try:
                    results.update(self.analyze_data_dout_fall(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for DOUT FALL failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(
                    f"WARNING: DOUT FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

            if self.substring_present(edges_map.get("DOUT", []), "RISE", position=1):
                try:
                    results.update(self.analyze_data_dout_rise(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for DOUT RISE failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(f"WARNING: DOUT RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if "BCLK" in edges_map.keys() and edges_map["BLCK"]:
            try:
                results.update(self.analyze_data_bclk(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for BCLK failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: BCLK edges not found. Check setup.")
            # clean this up by looping over a list of function objects and string tuples?
            # Maybe make a dictionary of functions

        if "LRCLK" in edges_map.keys() and edges_map["LRCLK"]:
            if self.substring_present(edges_map.get("LRCLK", []), "FALL", position=1):
                try:
                    results.update(self.analyze_data_lrclk_fall(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for LRCLK FALL failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(f"WARNING: LRCLK FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

            if self.substring_present(edges_map.get("LRCLK", []), "RISE", position=1):
                try:
                    results.update(self.analyze_data_lrclk_rise(waveforms, edges_map))
                except Exception as e:
                    self.logger.warning(f"WARNING: Plotting for LRCLK RISE failed.")
                    self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
            else:
                self.logger.warning(f"WARNING: LRCLK RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

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
                    self.limits["BCLK Low-Level Voltage"]["Upper Limit"], self.limits["BCLK High-Level Voltage"]["Lower Limit"],
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
        # plotting signals specific to SPI

        ax = plt.subplot(gs[1])  # NOQA
        # If a plotting window is not specified, use the entire waveform
        full_window = [0, len(waveforms["BCLK"].index)]

        waveforms["BCLK"][full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["BCLK"],
                                                              legend=True, linewidth=PLOT_LINE_WIDTH, label='BCLK')
        # If we're plotting LRCLK, don't show the other signals on the overview for a cleaner plot
        if "LRCLK" in signals:
            CS_offset = waveforms["LRCLK"].copy()
            CS_offset["v"] = waveforms["LRCLK"]["v"] + self.voltage + .1
            CS_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["LRCLK"],
                                                          legend=True, linewidth=PLOT_LINE_WIDTH, label='LRCLK')
        else:
            MOSI_offset = waveforms["DOUT"].copy()
            MOSI_offset["v"] = waveforms["DOUT"]["v"] + self.voltage + .1
            MOSI_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["DOUT"],
                                                            legend=True, linewidth=PLOT_LINE_WIDTH, label='DOUT')
            MISO_offset = waveforms["DIN"].copy()
            MISO_offset["v"] = waveforms["DIN"]["v"] + self.voltage + .1
            MISO_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["DIN"],
                                                            legend=True, linewidth=PLOT_LINE_WIDTH, label='DIN')
        start_t = waveforms[signals[0]]['t'].iloc[window[0]]
        end_t = waveforms[signals[0]]['t'].iloc[window[1]]
        color = ".8"
        # don't offset info from limits directly--calculate from waveform
        plt.plot([start_t, start_t], [-Y_AXIS_MARGIN * 2, 2 * self.voltage + Y_AXIS_MARGIN * 2],
                 color=color, linewidth=MARKER_LINE_WIDTH, linestyle="--")
        plt.plot([end_t, end_t], [-Y_AXIS_MARGIN * 2, 2 * self.voltage + Y_AXIS_MARGIN * 2],
                 color=color, linewidth=MARKER_LINE_WIDTH, linestyle="--")
        ax.xaxis.set_visible(False)
        ax.yaxis.set_visible(False)

        # write the plot to disk
        if not (self.data_dir / "picture").exists():
            (self.data_dir / "picture").mkdir()
        file_name = self.data_dir / ("picture/" + title.replace(":", "_") + ".png")
        plt.savefig(file_name, dpi=300)
        plt.close()

    def analyze_data_bclk(self, waveforms, edges_map):

        signal = "BCLK"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, "High-Level Voltage", measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal=signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal=signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Rise Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Frequency"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low Period"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            low_level = results[f'{signal} Low-Level Voltage']['Measured Value']
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", low_level)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "High Period"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            high_level = results[f'{signal} High-Level Voltage']['Measured Value']
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", high_level)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Duty Cycle"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_duty_cycle(waveforms, edges_map, full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_din_rise(self, waveforms, edges_map):

        signal = "DIN"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Rise Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tSU:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tHD:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_din_fall(self, waveforms, edges_map):

        signal = "DIN"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tSU:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tHD:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_dout_fall(self, waveforms, edges_map):

        signal = "DOUT"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # item = "Rise Time"
        # measurement = f"{signal} {item}"
        # attempted_measurements.append(measurement)
        # try:
        #     window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
        #     results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
        #     self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        # except Exception as e:
        #     self.logger.debug(traceback.format_exc())
        #     self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_dout_rise(self, waveforms, edges_map):

        signal = "DOUT"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_lrclk_fall(self, waveforms, edges_map):

        signal = "LRCLK"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "High-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # Setup time will be common for both master and slave
        item = "tSU:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(signal, attempted_measurements, results)

        return results

    def analyze_data_lrclk_rise(self, waveforms, edges_map):

        signal = "LRCLK"

        results = OrderedDict()
        attempted_measurements = []

        full_window = self.find_transaction(waveforms[signal], edges_map[signal], signal)

        item = "Overshoot"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # Setup time will be common for both master and slave
        item = "tHD:DAT0"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT0", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT1"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        # Slave
        if "slave" in self.test_name:
            LRCLKDAT0_measurement_name = "tH_BCLK-LRCLK;DAT0"
            LRCLKDAT1_measurement_name = "tH_BCLK-LRCLK;DAT1"
        # Master
        else:
            LRCLKDAT0_measurement_name = "tD_BCLK-LRCLK;DAT0"
            LRCLKDAT1_measurement_name = "tD_BCLK-LRCLK;DAT1"

        measurement = signal + " " + LRCLKDAT0_measurement_name
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        measurement = signal + " " + LRCLKDAT1_measurement_name
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Duty Cycle"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_duty_cycle(waveforms, edges_map, full_window, signal)
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["BCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Frequency"
        measurement = f"{signal} {item}"
        attempted_measurements.append(measurement)
        try:
            window, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
            results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        results = self.check_results(signal, attempted_measurements, results)

        return results

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    # All other non - analysis related code goes here:
    @staticmethod
    def substring_present(edges_list, substring, position=1):
        """Takes in a list of tuples and checks if any tuple in the list includes the provided substring in the
        given position"""
        present = False
        for edge in edges_list:
            if substring in edge[position]:
                present = True
                break

        return present

    def find_transaction(self, waveform, edges, signal):
        """Finds a transaction (period where clock is continuously driving) and returns a window containing it.
        For DIN, DOUT - we find the transaction with the most activity and analyzes it"""

        # windows_din = []
        transaction_length = []
        transaction_indices = []
        first_index = 0
        counter = 0
        # transaction_period = 0
        current_max = 0
        current_max_index = 0

        start_edge = "VIL_RISE"
        end_edge = "VIL_FALL"

        # rename this to start_indices / ALSO fix the self.transaction_DIN - it's supposed to be an number but it's showing as an array
        rise_indices = [e[0] for e in edges if e[1] == start_edge]
        rise_times = [waveform['t'].iloc[i] for i in rise_indices]
        fall_indices = [e[0] for e in edges if e[1] == end_edge]
        fall_times = [waveform['t'].iloc[i] for i in fall_indices]

        if len(rise_times) < 2:
            raise Exception("[I2SAnalyzer]: Edges not found for single transaction window!")
        if len(fall_times) < 2:
            raise Exception("[I2SAnalyzer]: Edges not found for single transaction window!")

        # Find the first edge where there is no matching edge within 2 clock periods (margin to be safe)
        # Use the first period as prototypical (using 200% margin so this is an ok assumption)
        rise_periods = np.subtract(rise_times[1:], rise_times[0:-1])
        # fall_periods = np.subtract(fall_times[1:], fall_times[0:-1])

        # Find the minimum period within the dataset and use that as a baseline to find "transactions"
        transaction = rise_periods.astype(np.float64)
        min_period = 10000
        current_min_index = 0
        for index, periods in enumerate(transaction):
            current_min = periods
            if current_min < min_period:
                min_period = current_min
                current_min_index = index

        # If we find a gap that is 2 * minimum period then we can consider it as one "data transaction"
        # However, if you feel like there is too much data within the window you can always change the gap multiplier!
        # gap_multiplier = 2
        # if signal == "DIN":
        #     gap_multiplier = 2

        # I guess change this accoding how the data is presented?
        # Sometimes the clk drives more DIN / DOUT signals within a short period of time for different commands
        # See documentation on what to do if you get an error
        # average_period = np.average(transaction[0:4])

        if signal != "LRCLK":
            # for everything else that isn't LRCLK:
            for idx, period in enumerate(transaction):
                if period > 2 * transaction[current_min_index]:
                    # the [0][0] is to access the element for np. where
                    # last_index = np.where(self.transaction == period)[0][0]
                    last_index = idx

                    # calculating the period length, and sorting it in a list via index that matches the windows_din
                    transaction_period = fall_times[last_index] - rise_times[first_index]
                    transaction_length.append(transaction_period)
                    transaction_indices.insert(counter, [rise_indices[first_index], fall_indices[last_index]])

                    # find the max # of transactions within a frame
                    period_number = self.count_periods([e for e in edges if transaction_indices[counter][0] <= e[0] <=
                                                        transaction_indices[counter][1]])
                    if period_number > current_max:
                        current_max = period_number
                        current_max_index = counter

                    # increment the counter
                    first_index = last_index + 1
                    counter = counter + 1

        if signal == "LRCLK":
            # Grab the first 3 LRCLKs - we don't need too many of them since they are repetitive
            if len(fall_indices) <= 2:
                transaction_indices.insert(0, [rise_indices[0], fall_indices[1]])
            else:
                transaction_indices.insert(0, [rise_indices[0], fall_indices[2]])

        if signal == "BCLK":
            # Grab the first 10 BCLKs - we don't need too many of them since they are repetitive
            transaction_indices.insert(0, [rise_indices[0], fall_indices[10]])
        window = []
        # [n][0] refers to rise index, [n][1] refers to fall index
        if signal != "LRCLK":
            self.set_timing_margin([e for e in edges if transaction_indices[current_max_index][0] <= e[0] <=
                                    transaction_indices[current_max_index][1]])
            window = self.pad_window(waveform,
                                     (transaction_indices[current_max_index][0], transaction_indices[current_max_index][1]),
                                     self.plot_timing_margin * PLOT_TIMING_MARGIN_LONG_MULTIPLIER)

        if (signal == "LRCLK") or (signal == "BCLK"):
            self.set_timing_margin([e for e in edges if transaction_indices[0][0] <= e[0] <=
                                    transaction_indices[0][1]])
            window = self.pad_window(waveform,
                                     (transaction_indices[0][0], transaction_indices[0][1]),
                                     self.plot_timing_margin * PLOT_TIMING_MARGIN_LONG_MULTIPLIER)
        # Add exception here!

        return window

    @staticmethod
    def count_periods(edges):
        number_of_periods = 0
        # use starting edge as the indicator
        for e in edges:
            if e[1] == "VIL_RISE":
                number_of_periods = number_of_periods + 1
        return number_of_periods

    def set_timing_margin(self, edges):
        """Set the timing margin class property as roughly the number of samples in one half clock period.
        Use the first valid period in the edges given, as this is not a precise measurement"""
        # Assume that edges follow a valid VIH VIL VIL VIH VIH VIL ... pattern
        # guarantee this invariant?
        measure_edges = [e for e in edges if e[1] == "VIL_RISE"]

        # This is a scenario in which we only have 1 period! => _|-|_
        if len(measure_edges) < 2:
            measure_edges = [e for e in edges if e[1] == "VIL_RISE"]
            measure_edges.append([e for e in edges if e[1] == "VIL_FALL"][0])
        period_samples = measure_edges[1][0] - measure_edges[0][0]

        # Floors the result but it's +- a single sample. Int needed for indexing
        self.plot_timing_margin = int(period_samples / 2)

    def find_mid_edges(self, waveforms, edges_map, input_window, data_signal):
        # CODE FOR: Use 50% level of waveform

        filtered_edges_signal_vil_vih = []
        filtered_edges_bclk_vil_vih = []
        for e in edges_map[data_signal]:
            if input_window[0] <= e[0] <= input_window[1]:
                filtered_edges_signal_vil_vih.append(e)
        for e in edges_map["BCLK"]:
            if input_window[0] <= e[0] <= input_window[1]:
                filtered_edges_bclk_vil_vih.append(e)

        filtered_edges_signal = []
        filtered_edges_bclk = []
        signal_mid_edges = []
        clock_mid_edges = []
        mid_edges = []

        # Obtain mid level voltage
        signal_high_level_v = self.find_high_level_voltage(waveforms[data_signal], input_window, data_signal)
        signal_low_level_v = self.find_low_level_voltage(waveforms[data_signal], input_window, data_signal)
        signal_mid_level_v = (signal_high_level_v + signal_low_level_v) / 2

        clock_high_level_v = self.find_high_level_voltage(waveforms["BCLK"], input_window, "BCLK")
        clock_low_level_v = self.find_low_level_voltage(waveforms["BCLK"], input_window, "BCLK")
        clock_mid_level_v = (clock_high_level_v + clock_low_level_v) / 2

        mid_levels = [signal_mid_level_v, clock_mid_level_v]

        # Algorithm to detect mid-edges
        for signal_level in mid_levels:
            # create a bool dataframe for all entries above and below the threshold
            if signal_level == signal_mid_level_v:
                above = waveforms[data_signal]['v'] > signal_level
            else:
                above = waveforms["BCLK"]['v'] > signal_level
            below = ~above

            # offset the bool dataframe and use the logical AND to pick out the threshold crossings
            left_shift_above = above.shift(-1)[:-1]
            left_shift_below = below.shift(-1)[:-1]

            for i in (left_shift_above & below[:-1]).nonzero()[0]:
                mid_edges.append((i, "MID_RISE"))
            for i in (left_shift_below & above[:-1]).nonzero()[0]:
                mid_edges.append((i, "MID_FALL"))

            if signal_level == signal_mid_level_v:
                signal_mid_edges = sorted(mid_edges, key=self.edge_priority)
                mid_edges.clear()
            else:
                clock_mid_edges = sorted(mid_edges, key=self.edge_priority)
                mid_edges.clear()

        # Filter the edges to limit the view window
        for e in signal_mid_edges:
            if input_window[0] <= e[0] <= input_window[1]:
                filtered_edges_signal.append(e)

        for e in clock_mid_edges:
            if input_window[0] <= e[0] <= input_window[1]:
                filtered_edges_bclk.append(e)

        # Hystersis filtering format: [(1, MID_RISE),(2, MID_FALL) ... ]
        valid_edges_signal = []
        for e1, e2 in zip(filtered_edges_signal_vil_vih[:-1], filtered_edges_signal_vil_vih[1:]):
            for edge_mid in filtered_edges_signal:
                # If first edge_mid rise or fall falls within the VIL and VIH index
                if (e1[0] <= edge_mid[0] <= e2[0]) and (e1[1] == "VIL_RISE" and e2[1] == "VIH_RISE"):
                    valid_edges_signal.append(edge_mid)
                    break
                if (e1[0] <= edge_mid[0] <= e2[0]) and (e1[1] == "VIH_FALL" and e2[1] == "VIL_FALL"):
                    valid_edges_signal.append(edge_mid)
                    break
                # else:
                #     self.logger.debug(f"Discarding edge: {edge_mid}")

        valid_edges_signal_clk = []
        for e1, e2 in zip(filtered_edges_bclk_vil_vih[:-1], filtered_edges_bclk_vil_vih[1:]):
            for edge_mid in filtered_edges_bclk:
                # If first edge_mid rise or fall falls within the VIL and VIH index
                if (e1[0] <= edge_mid[0] <= e2[0]) and (e1[1] == "VIL_RISE" and e2[1] == "VIH_RISE"):
                    valid_edges_signal_clk.append(edge_mid)
                    break
                if (e1[0] <= edge_mid[0] <= e2[0]) and (e1[1] == "VIH_FALL" and e2[1] == "VIL_FALL"):
                    valid_edges_signal_clk.append(edge_mid)
                    break
                # else:
                #     self.logger.debug(f"Discarding edge: {edge_mid}")
        # END OF CODE FOR: Use 50% level of waveform

        return valid_edges_signal, valid_edges_signal_clk

    @staticmethod
    def edge_priority(edge):
        """Takes in an edge tuple with (int index, 'VI*_RISE'/'VI*_FALL') and returns a float "adjusted index" allowing
        edges with the same index but different voltage level to be sorted properly. This is only necessary when
        sampling rate is low enough for an edge to be nearly vertical"""
        priority = edge[0]
        adjustment = 0
        if edge[1].endswith("FALL"):
            # Falling edges should have VIH < VIL
            adjustment = 0.1 if edge[1].startswith("VIL") else -0.1
        elif edge[1].endswith("RISE"):
            adjustment = 0.1 if edge[1].startswith("VIH") else -0.1
        return priority + adjustment

    def find_delta_time(self, waveforms, edges_map, mode: Literal[
        "tSU:DAT0", "tHD:DAT0", "tSU:DAT1", "tHD:DAT1",
        "tSU:LRCLK", "tHD:LRCLK", "tH_BCLK-LRCLK", "tD_BCLK-LRCLK"
    ], input_window, data_signal):
        """Calculate delta time between specific edges, based on SPI spec definition."""

        if not (mode.startswith("tSU:DAT") or mode.startswith("tHD:DAT") or mode.startswith("tSU:LRCLK") or
                mode.startswith("tHD:LRCLK") or mode.startswith("tH_BCLK-LRCLK") or mode.startswith("tD_BCLK-LRCLK")):
            raise Exception(f"[I2SAnalyzer]: Delta time mode not found: {mode}")

        valid_edges_signal, valid_edges_signal_clk = self.find_mid_edges(waveforms, edges_map, input_window, data_signal)
        window = [0, 0]
        x_markers = [0, 0]

        # CODE FOR: obtaining VIL and VIH
        rise_edge = 'MID_RISE'
        fall_edge = 'MID_FALL'

        if mode.endswith("DAT0"):
            # tSU;DAT0
            data_edge = "MID_FALL"
        elif mode.endswith("DAT1"):
            # tSU;DAT1
            data_edge = "MID_RISE"
        else:
            raise Exception(f"I2SAnalyzer: Invalid timing measurement bit value ({mode})")

        min_window = [0, 0]
        current_min = 1000000

        # finds the shortest setup time.
        if mode.startswith("tSU;"):
            # Different cases.
            if self.test_mode == "I2S2":
                bclk_edge = rise_edge
            elif data_signal == "LRCLK":
                bclk_edge = rise_edge
            else:
                bclk_edge = fall_edge

            for e in valid_edges_signal:
                if e[1] == data_edge and self.is_index_in_window(e[0], input_window):
                    e1 = e

                    if not e1:
                        raise Exception(f"[I2SAnalyzer]: Cannot find reference data edge for {mode}")

                    e2 = self.get_next_edge(e1[0], [e for e in valid_edges_signal_clk if e[1] == bclk_edge and self.is_index_in_window(e[0], input_window)])
                    if not e2:
                        # this typically means we run out of clock edges
                        continue

                    window[0] = e1[0]
                    # x_markers.append(e1[0])
                    data_transition = waveforms[data_signal]['t'].iloc[e1[0]]

                    window[1] = e2[0]
                    # x_markers.append(e2[0])
                    bclk_transition = waveforms["BCLK"]['t'].iloc[e2[0]]

                    result = bclk_transition - data_transition

                    if result < current_min:
                        current_min = result
                        x_markers[0] = e1[0]
                        x_markers[1] = e2[0]
                        min_window[0] = window[0]
                        min_window[1] = window[1]

        # finds the shortest hold time.
        # Master:
        # Slave: AOP Driving
        elif mode.startswith("tHD;") or mode.startswith("tD_") or mode.startswith("tH_"):

            # Conditions - for LRCLK there are 3 kinds of hold time measurements.
            if mode.startswith("tHD;") and data_signal == "LRCLK":
                bclk_edge = rise_edge
            elif mode.startswith("tH_BCLK-LRCLK;") and data_signal == "LRCLK":
                bclk_edge = fall_edge
            elif mode.startswith("tD_BCLK-LRCLK;") and data_signal == "LRCLK":
                bclk_edge = fall_edge
            else:
                bclk_edge = fall_edge

            for e in valid_edges_signal:
                if e[1] == data_edge and self.is_index_in_window(e[0], input_window):
                    e2_search = e

                    if len(e2_search) == 0:
                        raise Exception(f"[I2SAnalyzer]: Cannot find reference data edge for {mode}")
                    # Here we collect VIL_RISE of the DIN signal, and then take the first one (e1) - then e2 we get the BLCK edge.
                    e2 = e2_search
                    e1 = self.get_previous_edge(e2[0], [e for e in valid_edges_signal_clk if e[1] == bclk_edge and self.is_index_in_window(e[0], input_window)])
                    if not e1:
                        continue

                    window[0] = e1[0]
                    data_transition = waveforms[data_signal]['t'].iloc[e1[0]]
                    window[1] = e2[0]
                    bclk_transition = waveforms["BCLK"]['t'].iloc[e2[0]]

                    result = bclk_transition - data_transition

                    if result < current_min:
                        current_min = result
                        x_markers[0] = e1[0]
                        x_markers[1] = e2[0]
                        min_window[0] = window[0]
                        min_window[1] = window[1]

        if data_signal == "LRCLK":
            plot_window = self.pad_window(waveforms["BCLK"], min_window, 2000)
        else:
            plot_window = self.pad_window(waveforms["BCLK"], min_window, self.plot_timing_margin)
        return plot_window, x_markers, current_min

    def find_duty_cycle(self, waveforms, edges_map, input_window, signal):

        # We use 50% signal level for duty cycle measurements
        average_duty_cycle = 0
        start_edge = 'MID_RISE'
        end_edge = 'MID_FALL'

        waveform = waveforms[signal]
        valid_edges_signal, valid_edges_signal_clk = self.find_mid_edges(waveforms, edges_map, input_window, signal)

        # BCLK / LRCLK - to make sure we start with MID RISE, and end with MID FALL
        while valid_edges_signal[0][1] != start_edge:
            if valid_edges_signal[0][1] == start_edge:
                break
            valid_edges_signal.pop(0)

        while valid_edges_signal[-1][1] != end_edge:
            if valid_edges_signal[-1][1] == end_edge:
                break
            end_index = len(valid_edges_signal) - 1
            valid_edges_signal.pop(end_index)

        if len(valid_edges_signal) == 0:
            raise Exception("[I2SAnalyzer]: No rising / falling edges in window!")

        rise_indices = [e[0] for e in valid_edges_signal if e[1] == start_edge]
        rise_times = [waveform['t'].iloc[i] for i in rise_indices]
        fall_indices = [e[0] for e in valid_edges_signal if e[1] == end_edge]
        fall_times = [waveform['t'].iloc[i] for i in fall_indices]

        if len(rise_times) < 2:
            raise Exception("[I2SAnalyzer]: Edges not found for single transaction window to analyze Duty Cycle!")
        if len(fall_times) < 2:
            raise Exception("[I2SAnalyzer]: Edges not found for single transaction window to analyze Duty Cycle!")

        # rise_index = np.vstack((rise_indices[:-1], rise_indices[1:])).T
        # half_period_index = np.vstack((rise_indices[:-1], fall_indices[:-1])).T

        rise_periods = np.subtract(rise_times[1:], rise_times[:-1])
        half_periods = np.subtract(fall_times[:-1], rise_times[:-1])

        duty_cycle = (np.divide(half_periods, rise_periods)).astype(np.float64)

        for value in duty_cycle:
            average_duty_cycle = average_duty_cycle + value
        average_duty_cycle = average_duty_cycle / (len(duty_cycle))

        # FOR FUTURE USE: get min or max duty cycle!
        # min_duty_cycle = duty_cycle.min()
        # min_duty_cycle_index = np.where(duty_cycle == duty_cycle.min())

        if signal == "LRCLK":
            window = self.pad_window(waveform, (rise_indices[0], fall_indices[(len(fall_indices) - 1)]), 6000)
        else:
            window = self.pad_window(waveform, (rise_indices[0], fall_indices[(len(fall_indices) - 1)]), PLOT_EDGE_MARGIN)
        x_markers = [rise_indices[0], fall_indices[(len(fall_indices) - 1)]]

        return window, x_markers, average_duty_cycle
