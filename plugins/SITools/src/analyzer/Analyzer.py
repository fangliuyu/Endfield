
import abc
from typing import Union, Literal

import numpy as np
import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.formatting import Rule
from openpyxl.styles import PatternFill
from openpyxl.styles.differential import DifferentialStyle
import matplotlib
import matplotlib.gridspec as gridspec  # NOQA

import logging
from pathlib import Path

from lib.custommath import get_scale_for_units

from ..setting import SetupData

# constants
PLOT_EDGE_MARGIN = 200
CROP_MARGIN_SAMPLES = 10000


class Analyzer(abc.ABC):

    def __init__(self, config: SetupData, limits: pd.DataFrame, data_dir: Path, logger: logging):
        matplotlib.use("Agg")
        self.config = config
        self.limits = self.limits_trans(limits.to_dict('index'))
        self.logger = logger
        self.data_dir = data_dir
        self.voltage = float(str(self.config.Analysis.Configuration.get("voltage", 1.2)).lower().replace("v", ""))
        self.specLower, self.specUpper = self.config.Analysis.Configuration.get("thresholds", (0.3, 0.7))

    def load_waveforms(self):
        waveforms = {}

        self.logger.debug("Parsing CSV files...")

        channel_list = self.config.Oscilloscope.Channel
        for channel, info in channel_list.items():
            net: str = info.Net
            if info.EN:
                csv_path = f"{net}_{channel}_waveform.csv"
                file = self.data_dir / "waveform_csv" / csv_path
                if not file.exists():
                    self.logger.error(f"[I2CAnalyzer::parseCSV] {file} is not existed")
                    continue
                self.logger.info(f"load waveform data: {file}")
                waveforms[net] = pd.read_csv(file, names=["t", "v"])
            else:
                waveforms[net] = pd.DataFrame()  # 如果没启动则是空数据

        if len(waveforms) == 0:
            raise Exception("Check scope capture to make sure traffic is present No edges found. Check scope screen to make sure traffic is present.")

        edges_map = {}
        for signal, waveform in waveforms.items():
            edges_map[signal] = self.find_edges(waveform)

        return waveforms.copy(), edges_map.copy()

    @abc.abstractmethod
    def analyze_data(self):
        pass

    @staticmethod
    def safe_to_numeric(series):
        try:
            return pd.to_numeric(series)
        except ValueError:
            return series

    @staticmethod
    def limits_trans(limits: dict):
        limit_dict = {}
        for row, data in limits.items():
            # print(row, data)
            limit_dict[data["Net."] + " " + data["Measurement"]] = {
                "Lower Limit": data["Lower Limit"],
                "Lower Warning": data["Lower Warning"],
                "Upper Warning": data["Upper Warning"],
                "Upper Limit": data["Upper Limit"],
                "Unit": data["Unit"],
            }
        return limit_dict

    def process_results(self, net: str, item: str, measurement: float, limit_round=False):
        """Helper function to format measurement results with spec limits."""
        unit = self.limits.get(net + " " + item, {}).get("Unit", "")
        scaled_measurement = measurement / get_scale_for_units(unit)
        if limit_round:
            scaled_measurement = float("{:.3f}".format(scaled_measurement))
        lower_limit = self.limits.get(net + " " + item, {}).get("Lower Limit", "-")
        # if lower_limit != "-" and float(lower_limit) % 1 != 0:
        #     lower_limit = float("{:.3f}".format(float(lower_limit)))
        lower_warn = self.limits.get(net + " " + item, {}).get("Lower Warning", "-")
        # if lower_warn != "-" and float(lower_warn) % 1 != 0:
        #     lower_warn = float("{:.3f}".format(float(lower_warn)))
        upper_warn = self.limits.get(net + " " + item, {}).get("Upper Warning", "-")
        # if upper_warn != "-" and float(upper_warn) % 1 != 0:
        #     upper_warn = float("{:.3f}".format(float(upper_warn)))
        upper_limit = self.limits.get(net + " " + item, {}).get("Upper Limit", "-")
        # if upper_limit != "-" and float(upper_limit) % 1 != 0:
        #     upper_limit = float("{:.3f}".format(float(upper_limit)))
        status = "Pass"
        if lower_warn != "-" and scaled_measurement < float(lower_warn):
            status = "Warning: marginal pass"
        if lower_limit != "-" and scaled_measurement < float(lower_limit):
            status = "Fail"
        if upper_warn != "-" and scaled_measurement > float(upper_warn):
            status = "Warning: marginal pass"
        if upper_limit != "-" and scaled_measurement > float(upper_limit):
            status = "Fail"
        return {
            "Net": net,
            "Measurement": item,
            "Lower Limit": lower_limit,
            "Lower Warning": lower_warn,
            "Measured Value": scaled_measurement,
            "Upper Warning": upper_warn,
            "Upper Limit": upper_limit,
            "Unit": unit,
            "Result": status,
            "Link": f"./picture/{net} {item.replace(':', '_')}.png",
        }

    def check_results(self, net: str, attempted_measurements: list, results: dict):
        for attempt in attempted_measurements:
            if attempt not in results.keys():
                results[attempt] = {
                    "Net": net,
                    "Measurement": attempt.replace(net+" ", ""),
                    "Lower Limit": self.limits.get(attempt, {}).get("Lower Limit", "-"),
                    "Lower Warning": self.limits.get(attempt, {}).get("Lower Warning", "-"),
                    "Measured Value": "/",
                    "Upper Warning": self.limits.get(attempt, {}).get("Upper Warning", "-"),
                    "Upper Limit": self.limits.get(attempt, {}).get("Upper Limit", "-"),
                    "Unit": self.limits.get(attempt, {}).get("Unit", "-"),
                    "Result": 'Measurement Failed. No data could be gathered. Check Logs.',
                }
        return results

    def plot_scope_shot(self, title: str, waveforms: dict, signals: list, window, x_markers=None, y_markers=None, result=None):
        pass

    def convertToWorkbook(self):
        wb = Workbook()
        ws = wb.active
        ws.title = "Measurement Data"
        file_path = self.data_dir / "Measurement Data.xlsx"
        measurementWb = load_workbook(file_path)
        redFill = PatternFill(bgColor="F1948A")
        greenFill = PatternFill(bgColor="82E0AA")
        yellowFill = PatternFill(bgColor="F9E79F")
        red = DifferentialStyle(fill=redFill)
        green = DifferentialStyle(fill=greenFill)
        yellow = DifferentialStyle(fill=yellowFill)
        passing = Rule(type="expression", dxf=green, stopIfTrue=False)
        passing.formula = ['$I2="Pass"']
        warn = Rule(type="expression", dxf=yellow, stopIfTrue=False)
        warn.formula = ['$I2="Warning: marginal pass"']
        fail = Rule(type="expression", dxf=red, stopIfTrue=False)
        fail.formula = ['$I2="Fail"']

        top_sheet = measurementWb.active
        for row in top_sheet:
            for cell in row:
                ws[cell.coordinate] = cell.value
                if cell.coordinate[0] == 'J' and int(cell.coordinate[1]) > 1:
                    ws[cell.coordinate].hyperlink = cell.value
        ws.auto_filter.ref = ws.dimensions
        ws.conditional_formatting.add("A2:J500", passing)
        ws.conditional_formatting.add("A2:J500", warn)
        ws.conditional_formatting.add("A2:J500", fail)

        ws.column_dimensions['A'].width = 25  # "Net."
        ws.column_dimensions['B'].width = 40  # "Measurement"
        ws.column_dimensions['C'].width = 15  # "Lower Limit"
        ws.column_dimensions['D'].width = 15  # "Lower Warning"
        ws.column_dimensions['E'].width = 30  # "Measured Value"
        ws.column_dimensions['F'].width = 15  # "Upper Warning"
        ws.column_dimensions['G'].width = 15  # "Upper Limit"
        ws.column_dimensions['H'].width = 15  # "Uint"
        ws.column_dimensions['I'].width = 15  # "Result"
        ws.column_dimensions['J'].width = 50  # "Link"
        wb.save(file_path)

    """#############################################################################################
    ########################### waveform 处理 ##################################
    #############################################################################################"""

    def find_edges(self, waveform: pd.DataFrame):
        """Find all edge transitions within the recorded waveform data structure.
        Defined edge types indicate threshold and direction (VIL_RISE, VIL_FALL, VIH_RISE, VIH_FALL).
        Edges that do not cross both VIL and VIH thresholds are ignored.

        Arguments:
        waveform -- Dataframe of waveform data {"v":[], "t":[]}

        Returns:
        Array of edges in time-sorted order [(time index int, edge type string), ...]
        Uses the array indices from original waveform dataframe.
        """

        edges = []

        upper = float(self.voltage) * self.specUpper
        lower = float(self.voltage) * self.specLower
        self.logger.debug(f"VIH:{upper}, VIL:{lower}")
        # do one pass for each threshold level
        for cross, label in [(upper, "VIH"), (lower, "VIL")]:
            # create a bool dataframe for all entries above and below the threshold
            above = waveform['v'] > cross
            below = ~above

            # offset the bool dataframe and use the logical AND to pick out the threshold crossings
            left_shift_above = above.shift(-1)[:-1]
            left_shift_below = below.shift(-1)[:-1]

            for i in (left_shift_above & below[:-1]).to_numpy().nonzero()[0]:
                edges.append((i, f"{label}_RISE"))
            for i in (left_shift_below & above[:-1]).to_numpy().nonzero()[0]:
                edges.append((i, f"{label}_FALL"))

        # sort the edges in order of increasing time
        edges = sorted(edges, key=lambda x: x[0])

        # apply hysteresis in edge detection, ensuring that each edge crosses both VIL and VIH thresholds
        valid_edges = []
        for e1, e2 in zip(edges[:-1], edges[1:]):
            if (e1[1] == "VIH_FALL" and e2[1] == "VIL_FALL") or (e1[1] == "VIL_RISE" and e2[1] == "VIH_RISE"):
                valid_edges.append(e1)
                valid_edges.append(e2)
            # else:
            #     self.logger.debug(f"Discarding edge: {e1} {e2}")
        return valid_edges

    def find_high_level_voltage(self, waveform: pd.DataFrame, window, signal: str):
        """Find high level voltage (mode of all points >VIH) within a time index window for , I2S, ControlSignals

        Arguments:
            df -- waveform data containing time and voltage coordinate pairs
            window -- tuple of edges specifying the window being observed
            signal -- string giving the name of the signal being analyzed

        Results:
            mode -- floating point mode of all points > VIH
        """
        filtered_v = waveform[window[0]:window[1]][waveform[["v"]] > self.limits[f"{signal} High-Level Voltage"]["Lower Limit"]][["v"]]
        # take the mean in case more than one value occurs the most
        mode = filtered_v.mode().v.mean()
        return mode

    def find_low_level_voltage(self, waveform: pd.DataFrame, window, signal: str):
        """Find low level voltage (average of all points <VIL) within a time index window for , I2S, ControlSignals

        Arguments:
            df -- waveform data containing time and voltage coordinate pairs
            window -- tuple of edges specifying the window being observed
            signal -- string giving the name of the signal being analyzed

        Results:
            mode -- floating point mode of all points < VIL
        """
        filtered_v = waveform[window[0]:window[1]][waveform[["v"]] < self.limits[f"{signal} Low-Level Voltage"]["Upper Limit"]][["v"]]
        # take the mean in case more than one value occurs the most
        mode = filtered_v.mode().v.mean()
        return mode

    @staticmethod
    def pad_window(waveform: pd.DataFrame, window: Union[list, tuple], padding: int):
        """Helper function to expand a waveform window (index pair) within waveform limits."""
        minimum = max(window[0] - padding, 0)
        maximum = min(window[1] + padding, len(waveform.index) - 1)
        return minimum, maximum

    def find_edge_rate(self, waveform, edges, mode: Literal["falling", "rising"]):
        """Calculate edge rate."""
        if mode not in ["falling", "rising"]:
            raise Exception(f"[Analyzer]: Edge rate mode not found: {mode}")
        falling = mode == "falling"
        t_delta = None
        index = None
        x_markers = None
        margin = PLOT_EDGE_MARGIN
        for i, edge in enumerate(edges[:-1]):
            if falling:
                if not ("VIH_FALL" in edge[1] and "VIL_FALL" in edges[i + 1][1]):
                    continue
            else:
                if not ("VIL_RISE" in edge[1] and "VIH_RISE" in edges[i + 1][1]):
                    continue
            x_markers = [edge[0], edges[i + 1][0]]
            t_delta = waveform['t'].iloc[edges[i + 1][0]] - waveform['t'].iloc[edge[0]]
            # get padding margin value
            margin = PLOT_EDGE_MARGIN
            x_delta = abs(x_markers[1] - x_markers[0])
            if x_delta != 0:
                # scale  margin by an integer. The rise/fall time * this integer is the padding value
                margin = x_delta * 4
            index = edge[0]
            break
        if index is None:
            raise Exception(f"[Analyzer]: No {mode} edge found!")
        return self.pad_window(waveform, [x_markers[0], x_markers[1]], margin), x_markers, t_delta

    def find_edge_overshoot(self, waveform, edges, mode: Literal["min", "max"], signal: str):
        """Calculate overshoot / undershoot for an edge."""
        if mode not in ["min", "max"]:
            raise Exception(f"[Analyzer]: Peak mode not found: {mode}")
        min_mode = mode == "min"
        peak_val = None
        peak_window = None
        if min_mode:
            filtered_edges = [e[0] for e in edges if e[1] == "VIL_FALL"]
        else:
            filtered_edges = [e[0] for e in edges if e[1] == "VIH_RISE"]
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
            raise Exception(f"[Analyzer]: Edge peak mode not found: {mode}")
        if min_mode:
            final = self.find_low_level_voltage(waveform, peak_window, signal)
        else:
            final = self.find_high_level_voltage(waveform, peak_window, signal)
        return peak_window, (peak_val, final), peak_val - final

    @staticmethod
    def find_peak_voltage(waveform, window, mode: Literal["min", "max"]):
        """Helper function to find a peak value within a window."""
        if mode not in ["min", "max"]:
            raise Exception(f"[Analyzer]: Peak mode not found: {mode}")
        min_mode = mode == "min"
        if min_mode:
            i = waveform[window[0]:window[1]]['v'].idxmin()
        else:
            i = waveform[window[0]:window[1]]['v'].idxmax()
        return i, waveform.iloc[i, 1]

    def find_clock_frequency(self, waveform, edges):
        """Calculate waveform frequency from found edges, assuming the edges are periodic."""
        fall_indices = [e[0] for e in edges if e[1] == "VIL_FALL"]
        fall_edges = [waveform['t'].iloc[i] for i in fall_indices]
        if len(fall_edges) < 8:
            raise Exception("[Analyzer]: Edges not found for frequency measurement!")
        window = self.pad_window(waveform, [fall_indices[0], fall_indices[7]], 0)
        periods = np.subtract(fall_edges[1:8], fall_edges[0:7])
        frequency = len(periods) / sum(periods)
        return window, [fall_indices[3], fall_indices[4]], frequency

    def find_clock_period(self, waveform, edges, mode: Literal["low", "high"], high_level):
        """Calculate waveform period from found edges, assuming the edges are periodic."""
        if mode not in ["low", "high"]:
            raise Exception(f"[Analyzer]: Period mode not found: {mode}")
        low = mode == "low"
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
            period = t2 - t1
            if min_period is None:
                min_period = period
            else:
                if period < min_period:
                    min_period = period
                    min_index = i
        if min_period is None:
            raise Exception("[Analyzer]: No low period found!")
        else:
            x_markers = [edges[min_index + 5][0], edges[min_index + 6][0]]
            window = self.pad_window(waveform, (edges[min_index + 5][0], edges[min_index + 6][0]), PLOT_EDGE_MARGIN)
        return window, x_markers, min_period

    @staticmethod
    def get_next_edge(index, edges):
        """Get the next edge after a waveform time index."""
        for e in edges:
            if e[0] > index:
                return e
        return None

    @staticmethod
    def get_previous_edge(index, edges):
        """Get the previous edge before a waveform time index."""
        for e in reversed(edges):
            if e[0] < index:
                return e
        return None

    @staticmethod
    def is_index_in_window(index, window):
        """Helper function to check if a time index is within a time index window."""
        return window[0] <= index <= window[1]
