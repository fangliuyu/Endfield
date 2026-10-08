import traceback
from collections import OrderedDict

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
    "SCLK": (252.0 / 255.0, 237.0 / 255.0, 130.0 / 255.0),
    "SDATA": (140.0 / 255.0, 176 / 255.0, 207.0 / 255.0),
}
# constants
Y_AXIS_MARGIN = 0.3
CROP_MARGIN_SAMPLES = 10000
PLOT_LINE_WIDTH = 0.5
MARKER_LINE_WIDTH = 0.8
PLOT_EDGE_MARGIN = 200
PLOT_TIMING_MARGIN = 2000


class I2CAnalyzer(Analyzer):
    """
    Analyzes the SPMI bus signals on both SCLK and SDATA.
    """

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        super().__init__(config=config, limits=limits, data_dir=data_dir, logger=logger)
        self.test_mode = str(self.config.Analysis.Configuration["mode"])
        self.test_name = str(self.config.Analysis.Configuration["direction"])

    def analyze_data(self):
        waveforms, edges_map = self.load_waveforms()

        # crop the waveform to within the analyzed data range
        min_edge_index, max_edge_index = self.pad_window(waveforms["SCLK"],
                                                         [edges_map["SCLK"][0][0], edges_map["SCLK"][-1][0]], CROP_MARGIN_SAMPLES)
        for signal, waveform in waveforms.items():
            waveforms[signal] = waveforms[signal].iloc[min_edge_index:max_edge_index]
            waveforms[signal].reset_index(drop=True, inplace=True)
            edges_map[signal] = [(i - min_edge_index, v) for i, v in edges_map[signal]]

        try:
            # decode the i2c waveform
            self.logger.info("Decoding traffic...")
            all_windows, all_decoded_cmds = self.decode(waveforms, edges_map)
        except Exception as e:
            self.logger.debug(traceback.format_exc())
            raise Exception(f"WARNING: Decode failed. Exception thrown during decode:\n{e}")

        # perform the appropriate analysis based on configuration
        self.logger.debug("Analyzing data...")
        results = OrderedDict()
        windows = all_windows[-1]
        decoded_cmd = all_decoded_cmds[-1]
        if decoded_cmd == "Unknown":
            raise Exception("Error: Analyzing data failed if trying to decode unknown command")
        results.update(self.take_measurements(waveforms, edges_map, windows))

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
        # plotting signals specific to SPMI
        ax = plt.subplot(gs[1])  # NOQA
        waveforms["SCLK"].plot(kind="line", x="t", y="v", ax=ax, color=color_map["SCLK"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SCLK')
        SDA_offset = waveforms["SDATA"].copy()
        SDA_offset["v"] = waveforms["SDATA"]["v"] + self.voltage + .1
        SDA_offset.plot(kind="line", x="t", y="v", ax=ax, color=color_map["SDATA"], legend=True, linewidth=PLOT_LINE_WIDTH, label='SDATA')
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
        Input:target_path: the path to write the decoded output to
        waveforms: A dataframe of 2 waveforms: SDATA and SCLK with time and voltage data labeled 't' and 'v'
        edges_map: List of indices where waveforms cross a voltage threshold

        Output: Decoded output is saved to target_path
                windows: list of windows for each comamand found in the scope shot
        """

        # List of supported commands and their ranges
        command_list = {"Extended Register Write Long": [0x30, 0x37],
                        "Extended Register Read Long": [0x38, 0x3F],
                        "Extended Register Read": [0x20, 0x2F],
                        "Extended Register Write": [0x00, 0x0F],
                        "Register Write": [0x40, 0x5F],
                        "Register Read": [0x60, 0x7F],
                        "Master Write": [0x16, 0x16],
                        "Master Read": [0x15, 0x15]}

        all_windows = []
        all_decoded_cmds = []

        start_ind = 0

        while True:
            windows = {}
            # Find SSC
            SSC = self.find_SSC(edges_map, start_ind)
            # Arbitration not currently supported
            # Array to store the bits
            bits = []
            decoded_output = []
            # find all the falling edges of SCLK and record the SDATA binary value (Skips arbitration for now)
            filtered_edges = [e[0] for e in edges_map["SCLK"] if e[1] == "VIH_FALL" and e[0] > SSC]
            for i in filtered_edges:
                SDATA_v = waveforms["SDATA"]['v'].iloc[i]
                if SDATA_v > self.limits[f"Host SDATA High-Level Voltage"]["Lower Limit"]:
                    bits.append(1)
                else:
                    bits.append(0)

            # Get slave addr
            next_bit = 0
            self.check_parity(bits[next_bit:next_bit + 12], bits[next_bit + 12])  # Parity for both slave addr and command

            windows["Master"] = [filtered_edges[next_bit]]
            slave_addr = str(hex(self.bits2num(bits[next_bit:next_bit + 4])))
            next_bit = next_bit + 4
            # Get command frame
            command = self.bits2num(bits[next_bit:next_bit + 8])
            next_bit = next_bit + 9
            decoded_cmd = self.find_command(command, command_list)
            # Array for bytes written or read
            data = []
            if decoded_cmd != 'unknown':

                # Get Register address depending on the command type
                if decoded_cmd == "Register Write" or decoded_cmd == "Register Read":
                    register_addr = command - command_list[decoded_cmd][0]
                    num_bytes = 1
                else:
                    num_bytes = command - command_list[decoded_cmd][0] + 1
                    reg_upper_byte, next_bit = self.next_byte(bits, next_bit)
                    if "Long" in decoded_cmd:
                        reg_lower_byte, next_bit = self.next_byte(bits, next_bit)
                        register_addr = (reg_upper_byte << 8) + reg_lower_byte
                    else:
                        register_addr = reg_upper_byte
                # If the command is a read, end the master frame, get the bus park cycle and start the slave frame
                # at the rising edge after the bus park cycle
                if "Read" in decoded_cmd:
                    windows["Master"].append(filtered_edges[next_bit - 1])
                    windows["Master Park"] = [filtered_edges[next_bit - 1], filtered_edges[next_bit + 1]]
                    # Skip a clock cycle before Slave starts outputting
                    next_bit = next_bit + 1
                    # Get the index for the previous rising edge since filtered edges only contine falling edges
                    windows["Slave"] = [
                        self.get_previous_edge(
                            filtered_edges[next_bit], [e for e in edges_map["SCLK"] if e[1] == "VIL_RISE"]
                        )[0]
                    ]

                # Get data written or read in SPMI data frames
                for i in range(num_bytes):
                    data_byte, next_bit = self.next_byte(bits, next_bit)
                    data.append(data_byte)

                # If it's a read command, final bit should be a bus park by the slave.
                if "Read" in decoded_cmd:
                    windows["Slave"].append(filtered_edges[next_bit - 1])
                    if bits[next_bit] != 0:
                        self.logger.debug(f"Bus not parked! Bit: {bits}")
                    windows["Slave Park"] = [filtered_edges[next_bit]]
                    next_bit = next_bit + 1

                # If it's a White command, master should park bus,
                # slave should acknowledge and then slave should park bus
                elif "Write" in decoded_cmd:
                    windows["Master"].append(filtered_edges[next_bit - 1])
                    if bits[next_bit:next_bit + 3] != [0, 1, 0]:
                        self.logger.debug(f"Unexpected end of command frame sequence: {bits}")
                    else:
                        windows["Master Park"] = [filtered_edges[next_bit - 1], filtered_edges[next_bit + 1]]
                        windows["Slave Park"] = [filtered_edges[next_bit + 2]]
                    next_bit = next_bit + 3

                slave_info = self.config.Analysis.Configuration["slave address"]
                if int(slave_addr, 16) != int(slave_info, 16):
                    self.logger.critical(
                        f"[SPMIAnalyzer] Recorded waveform device address does not match. " + slave_addr + " to " +
                        slave_info)
                    self.logger.info("Omitting this command for analysis...")
                else:
                    all_windows.append(windows)
                    all_decoded_cmds.append(decoded_cmd)
            else:
                # If command is unknown, put that into the decoded output and continue to next command
                all_windows.append([0, 0])
                all_decoded_cmds.append("Unknown")
                register_addr = 0x0

            # record decoded output
            decoded_output.append("Slave Addr: " + slave_addr)
            decoded_output.append("Command: " + decoded_cmd)
            decoded_output.append("Register Addr: " + str(hex(register_addr)))
            data_str = "Data: "
            for byte in data:
                data_str = data_str + ' ' + str(hex(byte))
            decoded_output.append(data_str)
            # If there are more bits, continue decoding the next command. Otherwise, end the loop.
            if next_bit < len(filtered_edges):
                start_ind = filtered_edges[next_bit]
            else:
                break

        # report decoded output
        file_name = self.data_dir / "SPMI Decode.txt"
        with open(file_name, "w") as f:
            f.write("\n".join(decoded_output))

        # append decoded output to logger
        for line in decoded_output:
            self.logger.info(f"{line}")

        return all_windows, all_decoded_cmds

    def take_measurements(self, waveforms, edges_map, windows):
        """Suite of calculations for host-side specifications.
        Waived calculations due to challenges in acquiring proper scope capture: tSU;STA, tVD;ACK, bus free time.
        """

        results = OrderedDict()
        attempted_measurements = []

        # Take a measurement of every possible threshold permutation for hold time, setup time, and data output valid time.
        thresholds_text = {'(50% - 50%)': 'VIM VIM', '(30% - 30%)': 'VIL VIL', '(70% - 70%)': 'VIH VIH',
                           '(70% - 30%)': 'VIH VIL', '(30% - 70%)': 'VIL VIH'}

        for frame in ["Master", "Slave"]:
            if frame not in windows:
                continue
            clk_low_period = 0
            for signal in ["SCLK", "SDATA"]:
                # full_window = (0, len(waveforms[signal].index) - 1)
                # If there isn't a slave frame. i.e. command is a write, skip.
                edges = self.get_edges_within_byte_range(edges_map, windows[frame])
                if frame == "Slave" and signal == "SCLK":
                    continue

                item = "High-Level Voltage"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    measured_value = self.find_high_level_voltage(waveforms[signal], windows[frame], f"{frame} {signal}")
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], windows[frame], y_markers=[measured_value], result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Low-Level Voltage"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    measured_value = self.find_low_level_voltage(waveforms[signal], windows[frame], f"{frame} {signal}")
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], windows[frame], y_markers=[measured_value], result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                if signal != "SDATA":
                    item = "Frequency"
                    measurement = f"{frame} {signal} {item}"
                    attempted_measurements.append(measurement)
                    try:
                        window, x_markers, measured_value = self.find_clock_frequency(waveforms[signal], edges_map[signal])
                        results[measurement] = self.process_results(signal, item, measured_value, limit_round=True)
                        self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                    except Exception as e:
                        self.logger.debug(traceback.format_exc())
                        self.logger.error(e)

                    item = "Low Period"
                    measurement = f"{frame} {signal} {item}"
                    attempted_measurements.append(measurement)
                    try:
                        low_level = results[f'{frame} {signal} Low-Level Voltage']['Measured Value']
                        window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges[signal], "low", low_level)
                        results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                        self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                        clk_low_period = measured_value
                    except Exception as e:
                        self.logger.debug(traceback.format_exc())
                        self.logger.error(e)

                    item = "High Period"
                    measurement = f"{frame} {signal} {item}"
                    attempted_measurements.append(measurement)
                    try:
                        high_level = results[f'{frame} {signal} High-Level Voltage']['Measured Value']
                        window, x_markers, measured_value = self.find_clock_period(waveforms[signal], edges[signal], "high", high_level)
                        results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                        self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                    except Exception as e:
                        self.logger.debug(traceback.format_exc())
                        self.logger.error(e)

                item = "Overshoot"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges[signal], "max", signal)
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Undershoot"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, y_markers, measured_value = self.find_edge_overshoot(waveforms[signal], edges[signal], "min", signal)
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, y_markers=y_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Rise Time(30%-70%)"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges[signal], ["VIL_RISE", "VIH_RISE"])
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Fall Time(70%-30%)"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges[signal], ["VIH_FALL", "VIL_FALL"])
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Rise Time(20%-80%)"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges[signal], ["VOL_RISE", "VOH_RISE"])
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

                item = "Fall Time(80%-20%)"
                measurement = f"{frame} {signal} {item}"
                attempted_measurements.append(measurement)
                try:
                    window, x_markers, measured_value = self.find_edge_rate(waveforms[signal], edges[signal], ["VOH_FALL", "VOL_FALL"])
                    results[measurement] = self.process_results(f"{frame} {signal}", item, measured_value, limit_round=True)
                    self.plot_scope_shot(measurement, waveforms, [signal], window, x_markers=x_markers, result=results[measurement])
                except Exception as e:
                    self.logger.debug(traceback.format_exc())
                    self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            item = "Bus Park Voltage"
            measurement = f"{frame} {item}"
            attempted_measurements.append(measurement)
            try:
                window, x_markers, y_markers, measured_value = self.find_bus_park_voltage(waveforms, edges_map, windows[frame + " Park"], frame, clk_low_period)
                results[measurement] = self.process_results(frame, item, measured_value, limit_round=True)
                self.plot_scope_shot(measurement, waveforms, ["SCLK", "SDATA"], window, x_markers=x_markers, y_markers=y_markers, result=results[measurement])
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

            texts = ["tHD", "tSU", "tDR", "tDF"]
            directions = {'Rise': 'Rising', 'Fall': 'Falling'}
            for text in texts:
                for direction in directions.keys():
                    for thresh in thresholds_text.keys():
                        item = f"{text} {direction}{thresh}"
                        measurement = f"{frame} {item}"
                        attempted_measurements.append(measurement)
                        try:
                            window, x_markers, measured_value = self.find_delta_time(waveforms, edges_map, text, windows[frame],
                                                                                     thresholds_text[thresh], directions[direction])
                            results[measurement] = self.process_results(frame, item, measured_value, limit_round=True)
                            self.plot_scope_shot(measurement, waveforms, ["SCLK", "SDATA"], window, x_markers=x_markers, result=results[measurement])
                        except Exception as e:
                            self.logger.debug(traceback.format_exc())
                            self.logger.error(f"{measurement} not plotted; fatal exception:\n{e}")

        for attempt in attempted_measurements:
            if attempt not in results.keys():
                signals = ["SDATA", "SCLK"]
                found = True
                for signal in signals:
                    worlds = attempt.split(f" {signal} ")
                    if len(worlds) == 2:
                        results[attempt] = {
                            "Net": f"{worlds[0]} {signal}",
                            "Measurement": worlds[1],
                            "Lower Limit": "-",
                            "Lower Warning": "-",
                            "Measured Value": "/",
                            "Upper Warning": "-",
                            "Upper Limit": "-",
                            "Unit": "",
                            "Result": 'Measurement Failed. No data could be gathered. Check Logs.',
                        }
                    else:
                        found = False
                if not found and "Master" in attempt:
                    results[attempt] = {
                        "Net": "Master",
                        "Measurement": attempt.replace("Master ", ""),
                        "Lower Limit": "-",
                        "Lower Warning": "-",
                        "Measured Value": "/",
                        "Upper Warning": "-",
                        "Upper Limit": "-",
                        "Unit": "",
                        "Result": 'Measurement Failed. No data could be gathered. Check Logs.',
                    }
                if not found and "Slave" in attempt:
                    results[attempt] = {
                        "Net": "Slave",
                        "Measurement": attempt.replace("Slave ", ""),
                        "Lower Limit": "-",
                        "Lower Warning": "-",
                        "Measured Value": "/",
                        "Upper Warning": "-",
                        "Upper Limit": "-",
                        "Unit": "",
                        "Result": 'Measurement Failed. No data could be gathered. Check Logs.',
                    }
        return results

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    def find_SSC(self, edges_map, start_ind):
        """
        Find sequence start condition (SSC) in the given edge sequence.
        """
        rising_data_edges = [e for e in edges_map["SDATA"] if e[1] == "VIM_RISE" and e[0] > start_ind]
        falling_data_edges = [e for e in edges_map["SDATA"] if e[1] == "VIM_FALL" and e[0] > start_ind]
        for e in rising_data_edges:
            data_next = self.get_next_edge(e[0], falling_data_edges)
            clk_next = self.get_next_edge(e[0], edges_map["SCLK"])
            if data_next[0] < clk_next[0]:
                return e[0]
        self.logger.debug(f"Could not find SSC in data")
        return -1

    def check_parity(self, bits, p):
        total = 0
        for b in bits:
            total = total + b
        if (total + 1) % 2 != p:
            self.logger.debug(f"WRONG PARITY: Byte:  {str(bits)}; Parity: {str(p)}")

    @staticmethod
    def bits2num(bits):
        number = 0
        bits.reverse()
        for i in range(len(bits)):
            number = number + bits[i] * 2 ** i
        return number

    @staticmethod
    def find_command(command, command_list):
        for cmd in command_list:
            if command_list[cmd][0] <= command <= command_list[cmd][1]:
                return cmd
        return "unknown"

    def next_byte(self, bits, next_bit):
        byte = bits[next_bit:next_bit + 8]
        p = bits[next_bit + 8]
        self.check_parity(byte, p)
        byte = self.bits2num(byte)
        return byte, next_bit + 9

    def find_edge_rate(self, waveform, edges, thresholds):
        """Calculate edge rate."""
        if thresholds not in [["VIH_FALL", "VIL_FALL"], ["VOH_FALL", "VOL_FALL"], ["VIL_RISE", "VIH_RISE"],
                              ["VOL_RISE", "VOH_RISE"]]:
            raise Exception(f"[SPMIAnalyzer]: Edge rate thresholds not found: {thresholds}")
        t_delta = None
        index = None
        x_markers = None
        next_edge = 2
        if "VIL" in thresholds[0] or "VIH" in thresholds[0]:
            next_edge = 2
        elif "VOL" in thresholds[0] or "VOH" in thresholds[0]:
            next_edge = 4
        margin = PLOT_EDGE_MARGIN
        for i, edge in enumerate(edges[:-1 * next_edge]):

            if not (thresholds[0] in edge[1] and thresholds[1] in edges[i + next_edge][1]):
                continue
            x_markers = [edge[0], edges[i + next_edge][0]]
            t_delta = waveform['t'].iloc[edges[i + next_edge][0]] - waveform['t'].iloc[edge[0]]
            # get padding margin value
            x_delta = abs(x_markers[1] - x_markers[0])
            if x_delta != 0:
                # scale  margin by an integer. The rise/fall time * this integer is the padding value
                margin = x_delta * 4
            index = edge[0]
            break
        if index is None:
            self.logger.error(f"ERROR: No rising or falling edge found!")
            return [-1, -1], None, None, None
            # raise Exception("[SPMIAnalyzer]: No rising edge found!")
        return self.pad_window(waveform, (x_markers[0], x_markers[1]), margin), x_markers, None, t_delta

    @staticmethod
    def get_edges_within_byte_range(edges_map, byte_range_idx):
        """Filter edges from an edges map data structure within a time index range."""
        return {
            signal: [
                e for e in edges if byte_range_idx[0] <= e[0] <= byte_range_idx[1]
            ] for signal, edges in edges_map.items()
        }

    def find_bus_park_voltage(self, waveforms, edges_map, window, driver, clk_low_period):
        # The window input has strict criteria of starting one SCLK falling edge before the bus park for when master is the driver.
        # Window is expected to be of length 1 in case of slave driving and should contain the VIH position of the last SCLK falling edge.
        e1 = []
        e2 = []
        if driver == 'master':
            e1 = [e for e in edges_map["SCLK"] if e[1] == "VIL_FALL" and self.is_index_in_window(e[0], window)][1]
            e2 = [e for e in edges_map["SCLK"] if e[1] == "VIL_RISE" and self.is_index_in_window(e[0], window)][1]

        elif driver == "slave":
            e1 = [e for e in edges_map["SCLK"] if e[1] == "VIL_FALL" and e[0] > window[0]][0]
            for i in range(e1[0], len(waveforms["SCLK"]['t'])):
                if waveforms["SCLK"]['t'][i] - waveforms["SCLK"]['t'].iloc[e1[0]] >= clk_low_period:
                    e2 = [i, "Fake Edge"]
                    break
                # If the waveform cuts off before the end of the clock period, just use the last data point
                e2 = [i, "Fake Edge"]

        x_markers = [e1[0], e2[0]]

        filtered_v = waveforms["SDATA"][e1[0]:e2[0]]["v"]
        mean = float(filtered_v.mean())
        return self.pad_window(waveforms["SCLK"], (x_markers[0], x_markers[1]), PLOT_EDGE_MARGIN), x_markers, None, mean

    def find_delta_time(self, waveforms, edges_map, mode, input_window, thresh, direction):
        """Calculate delta time between specific edges, based on SPMI spec definition.
        thresh is given as a space-separated string e.g. 'VIH VIL' indicates the threshold for the first edge
        is VIH, and the second edge is VIL."""

        if mode not in ["tHD", "tSU", "tDR", "tDF"]:
            raise Exception(f"[SPMIAnalyzer]: Delta time mode not found: {mode}")

        x_markers = []
        data_name, sclk_name = thresh.split()
        data_name += "_" + direction
        data_first = True
        e1 = []
        e2 = []
        if mode == "tSU":
            # If there is no rising or falling edge within the slave window, code will error, so use try/except
            try:
                # first SDATA edge
                e1 = [e for e in edges_map["SDATA"] if e[1] == data_name and self.is_index_in_window(e[0], input_window)][0]
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.debug(f"Unable to find edges for tSU on SDATA {data_name} \n{e}")
                return [-1, -1], -1, -1, -1
            # first SCLK falling edge after SDATA
            e2_search = [e for e in edges_map["SCLK"] if
                         e[0] > e1[0] and e[1] == f"{sclk_name}_FALL" and self.is_index_in_window(e[0], input_window)]
            if len(e2_search) == 0:
                self.logger.debug("Unable to find edges for tSU on SDATA " + data_name)
                return [-1, -1], -1, -1, -1
            e2 = e2_search[0]
        elif mode == "tHD":
            # Find first read
            e_first_read = [e for e in edges_map["SCLK"] if
                            e[1] == f"{sclk_name}_FALL" and self.is_index_in_window(e[0], input_window)][0]
            # Find first SDATA edge after first read
            e2_search = [e for e in edges_map["SDATA"] if
                         e[0] > e_first_read[0] and e[1] == data_name and self.is_index_in_window(e[0], input_window)]
            if len(e2_search) == 0:
                self.logger.debug("Unable to find edges for tHD on SDATA " + data_name)
                return [-1, -1], -1, -1, -1
            e2 = e2_search[0]
            # first SCLK falling edge before SDATA
            e1 = [e for e in edges_map["SCLK"] if
                  e[0] < e2[0] and e[1] == f"{sclk_name}_FALL" and self.is_index_in_window(e[0], input_window)][-1]
            data_first = False

        elif "tDR" in mode or "tDF" in mode:
            try:
                # first SDATA edge
                e1 = [e for e in edges_map["SDATA"] if e[1] == data_name and self.is_index_in_window(e[0], input_window)][0]
            except Exception as e:
                self.logger.debug(traceback.format_exc())
                self.logger.debug(f"Unable to find edges for tDR/tDF on SDATA {data_name} \n{e}")
                return [-1, -1], -1, -1, -1
            if len(e1) == 0:
                return [-1, -1], -1, -1, -1
            e2list = [e for e in edges_map["SCLK"] if
                      e[1] == f"{sclk_name}_RISE" and self.is_index_in_window(e[0], input_window)]
            # Find the closest SCLK rising edge to first SDATA edge
            t_SDATA = waveforms["SDATA"]['t'].iloc[e1[0]]
            min_delta = abs(waveforms["SCLK"]['t'].iloc[e2list[0][0]] - t_SDATA)
            min_e2 = e2list[0]
            for e2 in e2list:
                t_e2 = waveforms["SCLK"]['t'].iloc[e2[0]]
                if abs(t_e2 - t_SDATA) < min_delta:
                    min_delta = abs(t_e2 - t_SDATA)
                    min_e2 = e2

            if min_e2[0] > e1[0]:
                e2 = min_e2
            else:
                e2 = e1
                e1 = min_e2
                data_first = False

        window = [e1[0], e2[0]]
        x_markers.extend(window)
        if data_first:
            SDATA_transition = waveforms["SDATA"]['t'].iloc[e1[0]]
            SCLK_fall = waveforms["SCLK"]['t'].iloc[e2[0]]
            result = SCLK_fall - SDATA_transition
        else:
            SDATA_transition = waveforms["SDATA"]['t'].iloc[e2[0]]
            SCLK_fall = waveforms["SCLK"]['t'].iloc[e1[0]]
            result = SDATA_transition - SCLK_fall
        return self.pad_window(waveforms["SCLK"], window, PLOT_TIMING_MARGIN), x_markers, None, result
