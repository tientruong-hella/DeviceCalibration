from PyQt6.QtWidgets import QMainWindow
from PyQt6 import uic

from GUI.json_display import JsonDisplay
from GUI.calibration import Calibration
from GUI.dut_settings import DutSettings
from GUI.equipment_settings import EquipmentSettings


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        self._calibration = Calibration()
        self._dut_settings = DutSettings()
        self._equipment_settings = EquipmentSettings()
        self._json_display = JsonDisplay()


        self.ui = uic.loadUi("GUI/main_window.ui", self)

        self.ui.tabWidget.addTab(self._calibration, "Calibration")
        self.ui.tabWidget.addTab(self._dut_settings, "DUT Settings")
        self.ui.tabWidget.addTab(self._equipment_settings, "Equipment Settings")
        self.ui.tabWidget.addTab(self._json_display, "JSON Display")


        self.show()