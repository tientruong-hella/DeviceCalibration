import logging
from abc import abstractmethod, ABC
from collections.abc import Callable
from enum import Enum

from typing_extensions import override

from utils import create_logger


class RfChannel(Enum):
    def __new__(cls, *args, **kwargs):
        value = len(cls.__members__) + 1
        obj = object.__new__(cls)
        obj._value_ = value
        return obj

    def __init__(self, channel_idx: int, center_freq_mhz: float):
        self.channel_idx = channel_idx
        self.center_freq_mhz = center_freq_mhz

    UWB_CH8 = 8, 7488.0
    UWB_CH9 = 9, 7987.2


class Settings(ABC):
    def __init__(self,
                 channel: RfChannel,
                 target_value: float,
                 calibration_accuracy: float,
                 convert_to_hmm_parameter_function: Callable[[float], float] = None):
        self._logger = create_logger(log_name="settings")
        self.channel = channel
        self._target_value = target_value
        self._calibration_accuracy = calibration_accuracy

        self._current_value = None
        self._deviation = None
        self._calibration_value = None
        self._calibration_value_hmm = None
        self._convert_to_hmm_parameter_function = convert_to_hmm_parameter_function

    @abstractmethod
    def __json__(self):
        # This method should be implemented in subclasses to provide a JSON representation of the settings
        # Values without / same units are given here
        self._logger.info("Creating json representation of settings")
        return {
            "channel": self.channel.name,
            "center_frequency_mhz": self.channel.center_freq_mhz,
            "calibration_value_hmm": self._calibration_value_hmm
        }

    def is_measured(self):
        if self._current_value is not None:
            self._logger.debug("Value is measured")
            return True
        else:
            self._logger.debug("Value is not measured")
            return False

    def is_calibrated(self):
        if abs(self._deviation) <= self._calibration_accuracy:
            self._logger.debug("Value is calibrated")
            return True
        else:
            self._logger.debug("Value is not calibrated")
            return False

    def needs_calibration(self):
        if self._calibration_value is None:
            self._logger.debug("Calibration is not needed for this setting")
            return False
        else:
            self._logger.debug("Calibration is needed for this setting")
            return True

    def update_value(self, new_value: float):
        self._current_value = new_value
        self._deviation = self._target_value - new_value
        self._logger.info(f"Updated value: {new_value}, Target: {self._target_value}, Deviation: {self._deviation}")

    def get_calibration_value(self):
        self._current_value = None # Reset current value to None before recalculating to indicate that a new measurement is needed
        self._calibration_value += self._deviation
        self._calibration_value_hmm = self._convert_to_hmm_parameter_function(self._calibration_value)
        self._logger.info(f"Calibration value updated: {self._calibration_value}, "
                          f"Calibration value HMM: {self._calibration_value_hmm}")

        return self._calibration_value_hmm

    def set_init_calibration_value(self, calibration_value: float):
        self._calibration_value = calibration_value
        self._calibration_value_hmm = self._convert_to_hmm_parameter_function(calibration_value)
        self._logger.info(f"Initial calibration value set: {self._calibration_value}, "
                          f"Calibration value HMM: {self._calibration_value_hmm}")

    def get_current_value(self):
        if self._current_value is None:
            self._logger.warning("Current value is not set, returning None")
            return None
        else:
            self._logger.debug(f"Current value: {self._current_value}")
            return self._current_value

    def get_target_value(self):
        self._logger.debug(f"Target value: {self._target_value}")
        return self._target_value


class ModulatedFrameSettings(Settings):
    def __init__(self, uwb_channel: RfChannel, target_power_dbm_mhz:float, calibration_accuracy_db:float,
                 db_to_calib_value_function: Callable[[float, int], int] = None):
        super().__init__(channel=uwb_channel,
                         target_value=target_power_dbm_mhz,
                         calibration_accuracy=calibration_accuracy_db,
                         convert_to_hmm_parameter_function=db_to_calib_value_function)

    def __json__(self):
        output = super().__json__()
        output["target_value_dbm_mhz"] = self._target_value
        output["measured_value_dbm_mhz"] = self._current_value
        output["deviation_error_dB"] = self._deviation
        output["passed"] = self.is_calibrated()

        return output


class StsFrameSettings(ModulatedFrameSettings):
    def __init__(self, uwb_channel: RfChannel, target_power_dbm_mhz:float, calibration_accuracy_db:float,
                 db_to_calib_value_function: Callable[[float, int], int] = None):
        super().__init__(uwb_channel=uwb_channel,
                         target_power_dbm_mhz=target_power_dbm_mhz,
                         calibration_accuracy_db=calibration_accuracy_db,
                         db_to_calib_value_function=db_to_calib_value_function)


class RadarFrameSettings(ModulatedFrameSettings):
    def __init__(self, uwb_channel: RfChannel, target_power_dbm_mhz:float, calibration_accuracy_db:float,
                 db_to_calib_value_function: Callable[[float, int], int] = None):
        super().__init__(uwb_channel=uwb_channel,
                         target_power_dbm_mhz=target_power_dbm_mhz,
                         calibration_accuracy_db=calibration_accuracy_db,
                         db_to_calib_value_function=db_to_calib_value_function)

    @override
    def update_value(self, new_value: float):
        self._current_value = new_value
        self._deviation = -1 * (self._target_value - new_value)  # Inverse deviation for radar frame
        self._logger.info(
            f"Updated radar frame value: {new_value}, Target: {self._target_value}, Deviation: {self._deviation}")


class CwPowerSettings(Settings):
    def __init__(self, uwb_channel: RfChannel, target_power_dbm: float, calibration_accuracy_db: float):
        super().__init__(channel=uwb_channel,
                         target_value=target_power_dbm,
                         calibration_accuracy=calibration_accuracy_db)

    def __json__(self):
        output = super().__json__()
        output["target_value_dbm"] = self._target_value
        output["measured_value_dbm"] = self._current_value
        output["deviation_error_dB"] = self._deviation
        output["passed"] = self.is_calibrated()

        return output


class FrequencySettings(Settings):
    def __init__(self, uwb_channel: RfChannel, target_ppm: float, calibration_accuracy_ppm: float,
                 ppm_to_calib_value_function: Callable[[float, int], int] = None):
        super().__init__(channel=uwb_channel,
                         target_value=target_ppm,
                         calibration_accuracy=calibration_accuracy_ppm,
                         convert_to_hmm_parameter_function=ppm_to_calib_value_function)

    def __json__(self):
        output = super().__json__()
        output["target_value_ppm"] = self._target_value
        output["measured_value_ppm"] = self._current_value
        output["deviation_error_ppm"] = self._deviation
        output["passed"] = self.is_calibrated()

        return output

    @override
    def update_value(self, new_value: float):
        self._current_value = new_value
        self._deviation = -1 * (self._target_value - new_value)  # Inverse deviation for radar frame
        self._logger.info(
            f"Updated value: {new_value}, Target: {self._target_value}, Deviation: {self._deviation}")

    def freq_mhz_to_ppm(self, frequency_mhz: float):
        ppm = (frequency_mhz - self.channel.center_freq_mhz) / self.channel.center_freq_mhz * 1e6
        self._logger.debug(f"Calculated PPM: {ppm}")
        return ppm