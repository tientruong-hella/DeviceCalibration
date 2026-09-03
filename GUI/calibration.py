from PyQt6.QtWidgets import QWidget
from PyQt6 import uic

class Calibration(QWidget):
    def __init__(self):
        super().__init__()

        self.ui = uic.loadUi("GUI/calibration.ui", self)