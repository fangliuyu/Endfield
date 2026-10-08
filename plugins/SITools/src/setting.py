
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass
class ProtocolBaseConfig:
    protocol: str = ""
    spec_file: str = ""
    base_voltage: float = 1.2
    thresholds: tuple = (0.3, 0.7)
    trigger_func: Tuple[str, str] = ("OneWire", "rising")
    channel_list: Dict[str, Tuple[bool, int, str]] = field(
        default_factory=lambda: {
            "OneWire": (True, 1, "OneWire"),
        }
    )
    protocol_configuration: Optional[dict] = None


@dataclass
class OscilloscopeHorizon:
    Range: float
    Position: float
    Points: int


@dataclass
class OscilloscopeChannel:
    EN: bool
    Net: str
    Label: str


@dataclass
class OscilloscopeTrigger:
    Channel: int
    Edge: str


@dataclass
class OscilloscopeConfig:
    Horizon: OscilloscopeHorizon
    Channel: Dict[int, OscilloscopeChannel]
    Trigger: OscilloscopeTrigger


@dataclass
class AnalysisConfig:
    ID: int
    Name: str
    Configuration: Dict[str, any]


@dataclass
class UARTConfig:
    EN: bool
    Baud: int
    InitCommand: str
    TriggerCommand: str


@dataclass
class TestItemData:
    Name: str
    SubName: str
    SubSubName: str


@dataclass
class SetupData:
    TestItem: TestItemData
    Analysis: AnalysisConfig
    Oscilloscope: OscilloscopeConfig
    Uart: UARTConfig
