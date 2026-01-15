"""Menu implementations for Phi CLI."""

from interfaces_cli.menus.main_menu import MainMenu
from interfaces_cli.menus.operate import InferenceMenu, OperateMenu, TeleopMenu
from interfaces_cli.menus.record import RecordMenu
from interfaces_cli.menus.train import TrainMenu, TrainingJobsMenu
from interfaces_cli.menus.storage import (
    DatasetsMenu,
    ModelsMenu,
    StorageMenu,
)
from interfaces_cli.menus.setup import (
    CalibrationMenu,
    DevicesMenu,
    ProjectMenu,
    SetupMenu,
)
from interfaces_cli.menus.info import InfoMenu
from interfaces_cli.menus.config import ConfigMenu

__all__ = [
    # Main
    "MainMenu",
    # Operate
    "OperateMenu",
    "TeleopMenu",
    "InferenceMenu",
    # Record
    "RecordMenu",
    # Train
    "TrainMenu",
    "TrainingJobsMenu",
    # Storage
    "StorageMenu",
    "DatasetsMenu",
    "ModelsMenu",
    # Setup
    "SetupMenu",
    "ProjectMenu",
    "DevicesMenu",
    "CalibrationMenu",
    # Info & Config
    "InfoMenu",
    "ConfigMenu",
]
