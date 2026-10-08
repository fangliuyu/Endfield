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
PLOT_TIMING_MARGIN_LONG_MULTIPLIER = 2

# color map for plotting
color_map = {
    "SCLK": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "MOSI": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
    "MISO": (252.0 / 255.0, 130 / 255.0, 130.0 / 255.0),
    "CS": (130.0 / 255.0, 130.0 / 255.0, 252.0 / 255.0),
}


class SPIAnalyzer(Analyzer):
    """
    Analyzes the SPI bus signals on CS, SCLK, MOSI, and MISO.
    """

    spi_mode = 0
    plot_timing_margin = 400

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # Search each channel in channel_map for the signal CS; if any channel has the signal, use for analysis
        # Make sure that if CS is present it has both a falling and rising edge (VIH_FALL, VIL_FALL, VIL_RISE, VIH_RISE)
        cs_rise = self.substring_present(edges_map.get("CS", []), "RISE", position=1)
        cs_fall = self.substring_present(edges_map.get("CS", []), "FALL", position=1)

        if (cs_rise or cs_fall) and not (cs_rise and cs_fall):
            self.logger.warning("[SPIAnalyzer::analyze_data] WARNING CS present but could not find both rising and "
                                "falling edge. Check scope to confirm CS is pulled low and then high."
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
        # all the same length. Using SCLK since it should always be present
        min_edge_index, max_edge_index = self.pad_window(waveforms["SCLK"], (first_edge, last_edge), CROP_MARGIN_SAMPLES)

        for signal, waveform in waveforms.items():
            # Crop the waveform, shifting all indices such that the first sample in the cropped waveform is at index 0
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            # Shift the edge indices as well, cutting off edges that were cropped out
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal] if i <= max_edge_index]

        try:
            # Decode the SPI waveform
            self.logger.info("Decoding traffic...")
            self.decode(waveforms, edges_map)
        except Exception as e:
            self.logger.warning("WARNING: Decode failed. Full transaction likely not in scope capture")
            self.logger.warning(f"WARNING: Exception thrown during decode: {e}")

        # Perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        if "SCLK" in edges_map:
            try:
                results.update(self.analyze_data_clk(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for SCLK failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: SCLK edges not found. Check setup.")

        if self.substring_present(edges_map.get("MISO", []), "FALL", position=1):
            try:
                results.update(self.analyze_data_miso_fall(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for MISO FALL failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: MISO FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if self.substring_present(edges_map.get("MISO", []), "RISE", position=1):
            try:
                results.update(self.analyze_data_miso_rise(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for MISO RISE failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: MISO RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if self.substring_present(edges_map.get("MOSI", []), "FALL", position=1):
            try:
                results.update(self.analyze_data_mosi_fall(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for MOSI FALL failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: MOSI FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if self.substring_present(edges_map.get("MOSI", []), "RISE", position=1):
            try:
                results.update(self.analyze_data_mosi_rise(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for MOSI RISE failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: MOSI RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if self.substring_present(edges_map.get("CS", []), "FALL", position=1):
            try:
                results.update(self.analyze_data_cs_fall(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for CS FALL failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: CS FALL edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

        if self.substring_present(edges_map.get("CS", []), "RISE", position=1):
            try:
                results.update(self.analyze_data_cs_rise(waveforms, edges_map))
            except Exception as e:
                self.logger.warning(f"WARNING: Plotting for CS RISE failed.")
                self.logger.warning(f"WARNING: Exception thrown during analysis: {e}")
        else:
            self.logger.warning(f"WARNING: CS RISE edge not found. If this edge is not captured with alternate triggers, check setup and commands to produce traffic")

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
                    self.limits["Host SCLK Low-Level Voltage"]["Upper Limit"], self.limits["Host SCLK High-Level Voltage"]["Lower Limit"],
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
        full_window = [0, len(waveforms["SCLK"].index)]

        waveforms["SCLK"][full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["SCLK"],
                                                              legend=True, linewidth=PLOT_LINE_WIDTH, label='SCLK')
        # If we're plotting CS, don't show the other signals on the overview for a cleaner plot
        if "CS" in signals:
            CS_offset = waveforms["CS"].copy()
            CS_offset["v"] = waveforms["CS"]["v"] + self.voltage + .1
            CS_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["CS"],
                                                          legend=True, linewidth=PLOT_LINE_WIDTH, label='CS')
        else:
            MOSI_offset = waveforms["MOSI"].copy()
            MOSI_offset["v"] = waveforms["MOSI"]["v"] + self.voltage + .1
            MOSI_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["MOSI"],
                                                            legend=True, linewidth=PLOT_LINE_WIDTH, label='MOSI')
            MISO_offset = waveforms["MISO"].copy()
            MISO_offset["v"] = waveforms["MISO"]["v"] + self.voltage + .1
            MISO_offset[full_window[0]:full_window[1]].plot(kind="line", x="t", y="v", ax=ax, color=color_map["MISO"],
                                                            legend=True, linewidth=PLOT_LINE_WIDTH, label='MISO')
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

    def decode(self, waveforms: dict, edges_map: dict):
        """Decode the SPI traffic and run a sanity check."""

        # array to store the bits
        miso_bits = []
        mosi_bits = []

        # Choose whether to read on a rising or falling clock edge based on SPI Mode
        read_edge = ""
        if self.spi_mode == 0 or self.spi_mode == 3:
            read_edge = "VIH_RISE"
        elif self.spi_mode == 1 or self.spi_mode == 2:
            read_edge = "VIL_FALL"
        # Find all the data read edges of SCLK and record the MISO and MOSI binary value
        filtered_edges = [e[0] for e in edges_map["SCLK"] if e[1] == read_edge]
        # Truncate extra bits on the end if needed
        filtered_edges = filtered_edges[0:(len(filtered_edges) // 8) * 8]

        high_Voltage = self.voltage * 0.7

        for i in filtered_edges:
            MISO_v = waveforms["MISO"]['v'].iloc[i]
            MOSI_v = waveforms["MOSI"]['v'].iloc[i]
            miso_bits.append("1") if MISO_v > high_Voltage else miso_bits.append("0")
            mosi_bits.append("1") if MOSI_v > high_Voltage else mosi_bits.append("0")

        # Split into bytes and also print in hex
        miso_bytes = ["".join(miso_bits[i:i + 8]) for i in range(0, len(miso_bits), 8)]
        mosi_bytes = ["".join(mosi_bits[i:i + 8]) for i in range(0, len(mosi_bits), 8)]
        decoded_output = [
            "MOSI: " + " ".join(mosi_bytes),
            "hex: " + " ".join([hex(int(byte, 2)) for byte in mosi_bytes]),
            "MISO: " + " ".join(miso_bytes),
            "hex: " + " ".join([hex(int(byte, 2)) for byte in miso_bytes]),
        ]

        # report decoded output
        file_name = self.data_dir / "SPI Decode.txt"
        with open(file_name, "w") as f:
            f.write("\n".join(decoded_output))

        # append decoded output to logger
        for line in decoded_output:
            self.logger.info(f"{line}")

    def analyze_data_clk(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        # Find a valid transaction (clock continuously driving) for analysis and set timing margin for plots
        window = self.find_transaction(waveforms, edges_map, "SCLK")
        # self.logger.info(window)

        signal = "SCLK"
        net = f"Host {signal}"

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], window, net)
            results[measurement] = self.process_results(net, "High-Level Voltage", measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", signal=net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", signal=net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low Period"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        low_period = 0.0
        try:
            low_level = results[f'{net} Low-Level Voltage']['Measured Value']
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "low", low_level)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            low_period = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "High Period"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        high_period = 0.0
        try:
            high_level = results[f'{net} High-Level Voltage']['Measured Value']
            window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges_map[signal], "high", high_level)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            high_period = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Frequency"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        frequency = 0.0
        try:
            window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
            frequency = measured_value
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Edges"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            x_markers = [e[0] for e in edges_map[signal]]
            measured_value = (1/frequency - low_period - high_period)/2
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_miso_fall(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        # Find a valid transaction (clock continuously driving) for analysis and set timing margin for plots
        full_window = self.find_transaction(waveforms, edges_map, "MISO")
        # self.logger.info(window)

        signal = "MISO"
        net = f"Slave {signal}"

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tSU:DAT0"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT0", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tHD:DAT1"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_miso_rise(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        # Find a valid transaction (clock continuously driving) for analysis and set timing margin for plots
        full_window = self.find_transaction(waveforms, edges_map, "MISO")

        signal = "MISO"
        net = f"Slave {signal}"

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tSU:DAT1"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT1", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        item = "tHD:DAT0"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT0", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(e)

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_mosi_fall(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        # Find a valid transaction (clock continuously driving) for analysis and set timing margin for plots
        full_window = self.find_transaction(waveforms, edges_map, "MOSI")

        signal = "MOSI"
        net = f"Host {signal}"

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT0"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT0", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT1"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT1", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_mosi_rise(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        # Find a valid transaction (clock continuously driving) for analysis and set timing margin for plots
        full_window = self.find_transaction(waveforms, edges_map, "MOSI")

        signal = "MOSI"
        net = f"Host {signal}"

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:DAT1"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:DAT1", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:DAT0"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:DAT0", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_cs_fall(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        full_window = (0, len(waveforms["CS"].index) - 1)

        signal = "CS"
        net = f"Host {signal}"

        item = "High-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_high_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Low-Level Voltage"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            measured_value = self.find_low_level_voltage(waveforms[signal], full_window, net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], full_window, y_markers=[measured_value], result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Undershoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "min", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Fall Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "falling")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tSU:CS"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tSU:CS", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", "CS"], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        results = self.check_results(net, attempted_measurements, results)

        return results

    def analyze_data_cs_rise(self, waveforms, edges_map):
        results = OrderedDict()
        attempted_measurements = []
        full_window = (0, len(waveforms["CS"].index) - 1)

        signal = "CS"
        net = f"Host {signal}"

        item = "Overshoot"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges_map[signal], "max", net)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "Rise Time"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges_map[signal], "rising")
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        item = "tHD:CS"
        measurement = f"{net} {item}"
        attempted_measurements.append(measurement)
        try:
            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, "tHD:CS", full_window, signal)
            results[measurement] = self.process_results(net, item, measured_value, limit_round=True)
            self.plot_scope_shot(measurement, waveforms, ["SCLK", "CS"], window, x_markers=x_markers, result=results[measurement])
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
        It is not guaranteed that CS will be falling/rising in this window, nor is it guaranteed that a 'transaction'
        contains integer multiples of bytes (clock can be stopped by host in the middle of sending data)"""

        # Chose which edges to measure the period from. Shouldn't actually depend on SPI mode in a well-formed
        # transaction, as all edges/levels will be present in equal numbers.

        SCLK_waveform = waveform["SCLK"]
        SCLK_edges = edges["SCLK"]

        transaction_length = []
        transaction_indices = []
        first_index = 0

        # To determine SCLK edge start,
        if self.spi_mode == 0 or self.spi_mode == 3:
            start_edge = "VIH_RISE"
            end_edge = "VIL_FALL"
        else:
            start_edge = "VIL_FALL"
            end_edge = "VIL_RISE"

        rise_indices = [e[0] for e in SCLK_edges if e[1] == start_edge]
        rise_times = [SCLK_waveform['t'].iloc[i] for i in rise_indices]
        fall_indices = [e[0] for e in SCLK_edges if e[1] == end_edge]
        fall_times = [SCLK_waveform['t'].iloc[i] for i in fall_indices]

        if len(fall_times) < 2:
            raise Exception("[SPIAnalyzer]: Edges not found for single transaction window!")

        # Find the first edge where there is no matching edge within 2 clock periods (margin to be safe)
        # Use the first period as prototypical (using 200% margin so this is an ok assumption)
        rise_periods = np.subtract(rise_times[1:], rise_times[0:-1])

        # Find the minimum period within the dataset and use that as a baseline to find "transactions"
        transaction = rise_periods.astype(np.float64)
        min_period = 10000
        current_min_index = 0
        for index, periods in enumerate(transaction):
            current_min = periods
            if current_min < min_period:
                min_period = current_min
                current_min_index = index

        data_start_edge = "VIL_RISE"
        data_edges = []
        if signal == "MOSI":
            data_edges = edges["MOSI"]
        elif signal == "MISO":
            data_edges = edges["MISO"]

        rise_indices_data = [e[0] for e in data_edges if e[1] == data_start_edge]
        # rise_periods_data = np.subtract(rise_times_data[1:], rise_times_data[0:-1])
        transaction_window_found = False
        transaction_window_found_SCLK = False
        data_counter = 0

        # If this condition is not satisfied, we already have a single valid transaction--no pauses
        for idx, period in enumerate(transaction):
            if transaction_window_found is True:
                break
            if transaction_window_found_SCLK is True:
                break
            if (period > 2 * transaction[current_min_index]) or idx == (len(transaction) - 1):
                last_index = idx

                # calculating the period length, and sorting it in a list via index that matches the windows_din
                transaction_period = fall_times[last_index] - rise_times[first_index]
                transaction_length.append(transaction_period)
                transaction_indices.insert(data_counter, [rise_indices[first_index], fall_indices[last_index]])

                # Cycle through a transaction window at a time, find if there are > 1 MISO/MOSI/CS pulse.
                if signal != "SCLK" and transaction_window_found is False:
                    rise_index_temp = []

                    for index, data in enumerate(rise_indices_data):
                        if (data > rise_indices[first_index]) and (data < fall_indices[last_index]):
                            rise_index_temp.append(rise_indices_data[index])
                            # if len(rise_index_temp) > 1:
                            # this statement above will require at least two rising edges for the transaction window to be valid
                            # we made the change below to only require one rising edge
                            # if this causes issues then we can revert the change by using the line above and removing the if statement below
                            if len(rise_index_temp) >= 1:
                                transaction_window_found = True
                                break
                    if transaction_window_found is False:
                        first_index = last_index + 1
                        data_counter = data_counter + 1

                # use the first SCLK transaction window
                if signal == "SCLK":
                    transaction_window_found_SCLK = True

        if transaction_window_found is False and transaction_window_found_SCLK is False:
            self.logger.warn(f"WARNING: No valid transaction window found for {signal}, no scope shots will be plotted and the analyzer will now exit.")
            self.logger.warn(f"WARNING: Not enough edges found for {signal} in transaction windows, consider sending more traffic on the line.")

        if signal != "SCLK":
            # issue here we cannot use the same current_max_index for SCLK and data
            self.plot_timing_margin = self.set_timing_margin(
                [
                    e for e in data_edges
                    if transaction_indices[data_counter][0] <= e[0] <= transaction_indices[data_counter][1]
                ]
            )
            window = self.pad_window(SCLK_waveform,
                                     (transaction_indices[data_counter][0], transaction_indices[data_counter][1]),
                                     self.plot_timing_margin * PLOT_TIMING_MARGIN_LONG_MULTIPLIER)
        else:
            self.plot_timing_margin = self.set_timing_margin(
                [
                    e for e in SCLK_edges
                    if transaction_indices[0][0] <= e[0] <= transaction_indices[0][1]
                ]
            )
            window = self.pad_window(SCLK_waveform,
                                     (transaction_indices[0][0],
                                      transaction_indices[0][1]),
                                     self.plot_timing_margin * PLOT_TIMING_MARGIN_LONG_MULTIPLIER)

        return window

    @staticmethod
    def set_timing_margin(edges):
        """Set the timing margin class property as roughly the number of samples in one half clock period.
        Use the first valid period in the edges given, as this is not a precise measurement"""
        # Assume that edges follow a valid VIH VIL VIL VIH VIH VIL ... pattern
        measure_edges = [e for e in edges if e[1] == "VIH_FALL"]
        if len(measure_edges) < 2:
            measure_edges_rise = [e for e in edges if e[1] == "VIL_RISE"]
            period_samples = measure_edges[0][0] - measure_edges_rise[0][0]
        else:
            period_samples = measure_edges[1][0] - measure_edges[0][0]
        # Floors the result, but it's +- a single sample. Int needed for indexing
        return int(period_samples / 2)

    def find_delta_time(self, waveforms, edges_map, mode: Literal["tSU:DAT0", "tHD:DAT0", "tSU:DAT1", "tHD:DAT1", "tSU:CS", "tHD:CS"], input_window, data_signal):
        """Calculate delta time between specific edges, based on SPI spec definition."""

        # Maybe relax this check a bit to make code cleaner
        if not (mode.startswith("tSU:DAT") or mode.startswith("tHD:DAT") or mode.startswith("tSU:CS") or
                mode.startswith("tHD:CS")):
            raise Exception(f"[SPIAnalyzer]: Delta time mode not found: {mode}")

        window = [0, 0]
        x_markers = []

        if mode.endswith("DAT0"):
            data_bit = 0
        elif mode.endswith("DAT1"):
            data_bit = 1
        elif mode.endswith("CS"):
            data_bit = 2
        else:
            raise Exception(f"SPIAnalyzer: Invalid timing measurement bit value ({mode})")

        e1, e2 = [], []
        if mode.startswith("tSU:"):
            data_edge, sclk_edge = self.calculate_setup_time_edges(self.spi_mode, data_bit)
            e1 = [e for e in edges_map[data_signal] if
                  e[1] == data_edge and self.is_index_in_window(e[0], input_window)][0]
            if not e1:
                raise Exception(f"[SPIAnalyzer]: Cannot find reference data edge for {mode}")
            e2 = self.get_next_edge(e1[0], [e for e in edges_map["SCLK"] if
                                            e[1] == sclk_edge and self.is_index_in_window(e[0], input_window)])
            if not e2:
                raise Exception(f"[SPIAnalyzer]: Cannot find reference clock edge for {mode}")

        elif mode.startswith("tHD:"):
            # Make sure we only look for data edges with a previous clock edge; shrink the search window to start at the
            # second SCLK edge, since MOSI can sometimes change *before* SCLK when CPHA == 1

            data_edge, sclk_edge = self.calculate_hold_time_edges(self.spi_mode, data_bit)
            e2_search = [e for e in edges_map[data_signal] if
                         e[1] == data_edge and self.is_index_in_window(e[0], input_window)]
            if len(e2_search) == 0:
                raise Exception(f"[SPIAnalyzer]: Cannot find reference data edge for {mode}")

            # Obtain the first edge that lies within SCLK transaction window. Because sometimes the MISO/MOSI rising pulse can happen before a rise of SCLK.
            for index, value in enumerate(e2_search):
                e1 = self.get_previous_edge(e2_search[index][0], [e for e in edges_map["SCLK"] if
                                                                  e[1] == sclk_edge and self.is_index_in_window(e[0], input_window)])
                if not e1:
                    continue
                else:
                    e2 = e2_search[index]
                    break
            if not e1:
                raise Exception(f"[SPIAnalyzer]: Cannot find reference clock edge for {mode}")

        window[0] = e1[0]
        x_markers.append(e1[0])
        data_transition = waveforms[data_signal]['t'].iloc[e1[0]]

        window[1] = e2[0]
        x_markers.append(e2[0])
        sclk_transition = waveforms["SCLK"]['t'].iloc[e2[0]]

        result = sclk_transition - data_transition
        if data_bit == 2:
            plot_window = self.pad_window(waveforms["SCLK"], window, self.plot_timing_margin * PLOT_TIMING_MARGIN_LONG_MULTIPLIER)
        else:
            plot_window = self.pad_window(waveforms["SCLK"], window, self.plot_timing_margin)
        return plot_window, x_markers, result

    def calculate_hold_time_edges(self, spi_mode, data_bit):
        """Decide for hold time measurements whether to use rising/falling edges and where on those edges to measure
        (high e.g. 70% or low e.g. 30%)"""
        # redo this function in the same style as the setup time one for clarity
        # Get setup levels/directions and then simply flip only data direction, clock only flip the level
        # Can verify this by writing out a table of all possible SPI mode/data bit combinations
        data_edge, sclk_edge = self.calculate_setup_time_edges(spi_mode, data_bit)
        sclk_flip_dict = {"VIH_FALL": "VIL_FALL", "VIL_RISE": "VIH_RISE"}
        data_flip_dict = {"VIH_RISE": "VIH_FALL", "VIL_FALL": "VIL_RISE"}
        # CS (data_bit == 2) is the exception; need to flip clock direction but not level
        if data_bit == 2:
            sclk_flip_dict = {"VIH_FALL": "VIH_RISE", "VIL_RISE": "VIL_FALL"}
        return data_flip_dict[data_edge], sclk_flip_dict[sclk_edge]

    @staticmethod
    def calculate_setup_time_edges(spi_mode, data_bit):
        """Decide for setup time measurements whether to use rising/falling edges and where on those edges to measure
        (high e.g. 70% or low e.g. 30%)"""
        # Use data_bit = 2 to represent CS
        # Based on SPI mode, find where data is latched and which part of the edge to use for worst-case measurement
        # CS is a special case that depends only on clock polarity
        data_edge = ""
        sclk_edge = ""

        CPOL = spi_mode == 2 or spi_mode == 3
        if (spi_mode == 0 or spi_mode == 3 and data_bit != 2) or (data_bit == 2 and CPOL == 0):
            sclk_edge = "VIL_RISE"
        elif (spi_mode == 1 or spi_mode == 2 and data_bit != 2) or (data_bit == 2 and CPOL == 1):
            sclk_edge = "VIH_FALL"

        # Based on bit we're reading, find whether we need a data falling or rising edge
        if data_bit == 0 or data_bit == 2:
            data_edge = "VIL_FALL"
        elif data_bit == 1:
            data_edge = "VIH_RISE"

        return data_edge, sclk_edge
