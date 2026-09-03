from abc import abstractmethod

import can
from PyQt6.QtWidgets import QWidget
from PyQt6 import uic
from can.interfaces.vector import VectorBus

from can_interface import APP_NAME, APP_CHANNEL, FBD6Can


def get_hw():
    configs = can.detect_available_configs(interfaces="vector")
    hw = [c["hw_type"].name for c in configs]
    hw = set([c.split("_")[-1] for c in hw])

    return list(hw)

def get_can_channels(can_case: str):
    configs = can.detect_available_configs(interfaces="vector")
    configs = [c for c in configs if can_case in c["hw_type"].name]
    channels = [f"Channel {c['channel']+1}" for c in configs]

    return channels


class DutSettings(QWidget):
    def __init__(self):
        super().__init__()

        self.can_interface = None

        self.ui = uic.loadUi("GUI/dut_settings.ui", self)
        self._make_connections()


    def _make_connections(self):
        self.ui.pushButtonReloadCan.clicked.connect(self._load_can_cases_to_combo_box)
        self.ui.comboBoxCanCase.currentTextChanged.connect(self._load_can_channels_to_combo_box)

        self.ui.pushButtonReloadDevice.clicked.connect(self._load_devices)

    def showEvent(self, event):
        self._load_can_cases_to_combo_box()
        self._load_can_channels_to_combo_box()

    def _load_can_cases_to_combo_box(self):
        hw_list = get_hw()
        self.ui.comboBoxCanCase.clear()
        [self.ui.comboBoxCanCase.addItem(hw) for hw in hw_list]

    def _load_can_channels_to_combo_box(self):
        selected_hw = self.ui.comboBoxCanCase.currentText()
        channel_list = get_can_channels(selected_hw)
        self.ui.comboBoxCanChannel.clear()
        [self.ui.comboBoxCanChannel.addItem(channel) for channel in channel_list]

    def _load_devices(self):
        selected_hw = self.ui.comboBoxCanCase.currentText()
        selected_channel = self.ui.comboBoxCanChannel.currentText()
        selected_project = self.ui.comboBoxProject.currentText()

        if selected_hw == "" or selected_channel == "" or selected_project == "":
            return

        selected_channel_number = int(selected_channel.split(" ")[-1])-1

        if selected_project == "FBD6":
            try:
                self.can_interface = FBD6Can(selected_hw, selected_channel_number)
            except RuntimeError as e:
                return

            devices = self.can_interface.get_connected_devices()
            self.ui.comboBoxDeviceList.clear()
            [self.ui.comboBoxDeviceList.addItem(device.variant_name) for device in devices]
