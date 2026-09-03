import asyncio
import json
import os.path

import utils
from utils import ppm_to_hmm, db_to_hmm, create_logger
from calibration_settings import Settings, CwPowerSettings, RfChannel, StsFrameSettings, RadarFrameSettings, \
    FrequencySettings
from can_interface import FBD6Can
from rohde_schwarz import FSW


class FBD6AntennaConfig:
    def __init__(self,
                 calibration: Settings,
                 antenna_config: FBD6Can.AntennaConfig):
        self._calibration_type = calibration.__class__.__name__
        self.calibration = calibration
        self.antenna_config = antenna_config

    def __json__(self):
        output = {
            "calibration_type": self._calibration_type,
            "antenna_config": self.antenna_config.name,
        }
        output.update(self.calibration.__json__())

        return output

    async def load_calibration_hmm(self, can_interface: FBD6Can):
        if isinstance(self.calibration, FrequencySettings):
            low_byte_value = await can_interface.hmm_read_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_oscillator_drift_LowByte)
            high_byte_value = await can_interface.hmm_read_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_oscillator_drift_HighByte)

            calib_value_bytes = bytes([high_byte_value, low_byte_value])
            calib_value = int.from_bytes(calib_value_bytes, "big", signed=True)
            calib_value /= 10.0 # Convert to PPM value
        elif isinstance(self.calibration, StsFrameSettings):
            channel_idx = self.calibration.channel.channel_idx
            antenna_idx = self.antenna_config.get_tx_antenna_idx()
            key = f"p_n_FBD6_UWB_TxPower_Ch{channel_idx}_Ant{antenna_idx}_Offset"
            param_address = FBD6Can.CalibrationParameterAddress[key]

            calib_value = await can_interface.hmm_read_param(parameter_address=param_address)
            calib_value = int.from_bytes(bytes([calib_value]), "big", signed=True)
            calib_value *= 0.17  # Convert to dBm value

        elif isinstance(self.calibration, RadarFrameSettings):
            if self.calibration.channel == RfChannel.UWB_CH8:
                # Radar channel 8 is not calibrated in FBD6
                return

            calib_value = await can_interface.hmm_read_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_CPD_Offset_TxPower)
            calib_value = int.from_bytes(bytes([calib_value]), "big", signed=True)
            calib_value *= 0.17  # Convert to dBm value

        else:
            return

        self.calibration.set_init_calibration_value(calib_value)

    async def upload_calibration_hmm(self, can_interface: FBD6Can):
        if not self.calibration.needs_calibration() or self.calibration.is_calibrated():
            return

        if isinstance(self.calibration, FrequencySettings):
            calibration_param = self.calibration.get_calibration_value()
            await can_interface.hmm_write_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_oscillator_drift_LowByte,
                new_value=calibration_param[1])
            await can_interface.hmm_write_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_oscillator_drift_HighByte,
                new_value=calibration_param[0])

        elif isinstance(self.calibration, StsFrameSettings):
            channel_idx = self.calibration.channel.channel_idx
            antenna_idx = self.antenna_config.get_tx_antenna_idx()
            key = f"p_n_FBD6_UWB_TxPower_Ch{channel_idx}_Ant{antenna_idx}_Offset"
            param_address = FBD6Can.CalibrationParameterAddress[key]

            calibration_param = self.calibration.get_calibration_value()

            await can_interface.hmm_write_param(parameter_address=param_address,
                                                new_value=calibration_param)

        elif isinstance(self.calibration, RadarFrameSettings):
            calibration_param = self.calibration.get_calibration_value()

            await can_interface.hmm_write_param(
                parameter_address=FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_CPD_Offset_TxPower,
                new_value=calibration_param)


class FBD6:
    def __init__(self, serial_number: str):
        self._logger = create_logger(log_name="base")
        self._logger.info(f"Initializing FBD6 device with serial number: {serial_number}")

        self._serial_number = serial_number
        utils.SERIAL_NR = serial_number

        self._logger.info("Creating CAN interface for FBD6 device")
        self._can_interface = FBD6Can(can_case_channel=1, hw_type="VN1630")
        hmm_configs = self._can_interface.get_connected_devices()
        self._can_interface.hmm_config = hmm_configs[0]
        self._can_interface.connect()
        self.locked = self._can_interface.is_locked()
        self._logger.info(f"CAN interface created successfully, locked: {self.locked}")

        self._logger.info("Creating FSW interface for FBD6 device")
        screenshot_path = os.path.join(os.path.abspath("."),
                                       "export",
                                       "measurement_screenshots",
                                       serial_number)
        self._fsw = FSW(screenshot_path=screenshot_path)
        self._logger.info("FSW interface created successfully")

        self._logger.info("Initializing FBD6 device settings")
        self._antenna_configs = []

        # Frequency calibration settings
        self._logger.info("Loading frequency calibration settings")
        freq_calibration = FrequencySettings(uwb_channel=RfChannel.UWB_CH9,
                                             target_ppm=3.0,
                                             calibration_accuracy_ppm=0.5,
                                             ppm_to_calib_value_function=lambda x: ppm_to_hmm(x, num_bytes=2))
        self._antenna_configs.append(FBD6AntennaConfig(calibration=freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_2))
        self._logger.info("Frequency calibration settings loaded successfully")

        self._load_power_calibration_settings()
        self._load_cw_measurement_settings()

        self._logger.info("FBD6 initialized successfully")

    def __json__(self):
        return {
            "serial_number": self._serial_number,
            "variant_type": self._can_interface.get_variant_type(),
            "is_locked": self.locked,
            "antenna_configs": [antenna_config.__json__() for antenna_config in self._antenna_configs]
        }

    def _export_json(self):
        export_path = os.path.join(os.path.abspath("."),
                                   "export",
                                   "measurement_data",
                                   self._serial_number)

        self._logger.info(f"Exporting calibration data to {export_path}.json")

        with open(f"{export_path}.json", "w", encoding="utf-8") as f:
            json.dump(self.__json__(), f, ensure_ascii=False, indent=4)

        self._logger.info("Export completed")

    def _load_power_calibration_settings(self):
        self._logger.info("Loading power calibration settings")
        convert_func = lambda x: db_to_hmm(x, num_bytes=1)

        # Power calibration settings STS antenna 1
        ant1_ch8_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH8,
                                                target_power_dbm_mhz=-50.9,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-51.4,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch8_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_1))

        ant1_ch9_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH9,
                                                target_power_dbm_mhz=-54.8,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-53.3,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch9_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_1))

        # Power calibration settings STS antenna 2
        ant2_ch8_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH8,
                                                target_power_dbm_mhz=-46.4,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-46.9,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch8_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_2))

        ant2_ch9_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH9,
                                                target_power_dbm_mhz=-47.6,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-48.1,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch9_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_2))

        # Power calibration settings STS antenna 3
        ant3_ch8_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH8,
                                                target_power_dbm_mhz=-49.3,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-49.8,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant3_ch8_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_3))

        ant3_ch9_power_calib = StsFrameSettings(uwb_channel=RfChannel.UWB_CH9,
                                                target_power_dbm_mhz=-50.2,
                                                calibration_accuracy_db=0.5,
                                                #target_power_dbm_mhz=-50.7,
                                                #calibration_accuracy_db=1,
                                                db_to_calib_value_function=convert_func)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant3_ch9_power_calib,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_3))

        # Power calibration settings Radar antenna 1
        if self._can_interface.get_variant_type() == 14 or self._can_interface.get_variant_type() == 24:
            self._logger.info("Loading Radar power calibration settings")

            ant1_ch9_power_calib = RadarFrameSettings(uwb_channel=RfChannel.UWB_CH9,
                                                      target_power_dbm_mhz=-54.4,
                                                      calibration_accuracy_db=1,
                                                      #target_power_dbm_mhz=-54.9,
                                                      #calibration_accuracy_db=1.5,
                                                      db_to_calib_value_function=convert_func)
            self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch9_power_calib,
                                                           antenna_config=FBD6Can.AntennaConfig.RADAR))

            ant1_ch8_power_calib = RadarFrameSettings(uwb_channel=RfChannel.UWB_CH8,
                                                      target_power_dbm_mhz=-50.1,
                                                      calibration_accuracy_db=1,
                                                      #target_power_dbm_mhz=-50.6,
                                                      #calibration_accuracy_db=1.5,
                                                      db_to_calib_value_function=convert_func)
            self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch8_power_calib,
                                                           antenna_config=FBD6Can.AntennaConfig.RADAR))
        else:
            self._logger.warning("Radar power calibration settings not available for this device variant")

        self._logger.info("Power calibration settings loaded successfully")

    def _load_cw_measurement_settings(self):
        self._logger.info("Loading CW measurement settings")

        ant1_ch8_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH8,
                                                    target_power_dbm=-10.1,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch8_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_1))

        ant1_ch9_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH9,
                                                    target_power_dbm=-11.3,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant1_ch9_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_1))

        ant2_ch8_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH8,
                                                    target_power_dbm=-4.4,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch8_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_2))

        ant2_ch9_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH9,
                                                    target_power_dbm=-4.5,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch9_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_2))

        ant2_ch8_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH8,
                                                    target_power_dbm=-6.3,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch8_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_3))

        ant2_ch9_freq_calibration = CwPowerSettings(uwb_channel=RfChannel.UWB_CH9,
                                                    target_power_dbm=-6.8,
                                                    calibration_accuracy_db=1.5)
        self._antenna_configs.append(FBD6AntennaConfig(calibration=ant2_ch9_freq_calibration,
                                                       antenna_config=FBD6Can.AntennaConfig.ANTENNA_3))

        self._logger.info("CW measurement settings loaded successfully")

    def _all_calibrated(self):
        for antenna_calib in self._antenna_configs:
            calibration = antenna_calib.calibration

            if calibration.needs_calibration() and not calibration.is_calibrated():
                calibration_type = calibration.__class__.__name__
                self._logger.debug(f"{calibration_type} for {antenna_calib.antenna_config.name}, "
                                     f"channel {calibration.channel.channel_idx} is not done yet!")
                return False

        self._logger.debug("All parameters are calibrated!")
        return True

    async def _measure_cw(self, channel: int, antenna_config: FBD6Can.AntennaConfig):
        self._logger.debug(f"Measuring CW on channel {channel}, antenna {antenna_config.name}")

        task = asyncio.create_task(self._fsw.measure_cw(channel))
        await self._can_interface.uwb_cw_burst(channel, antenna_config=antenna_config)
        frequency_hz, power_dbm = await task

        self._logger.debug(f"CW measurement on channel {channel}, antenna {antenna_config.name} completed: "
                         f"Frequency: {frequency_hz / 1e6} MHz, Power: {power_dbm} dBm")

        return frequency_hz*1e-6, power_dbm

    async def _measure_sts(self, channel: int, antenna_config: FBD6Can.AntennaConfig):
        self._logger.debug(f"Measuring STS on channel {channel}, antenna {antenna_config.name}")

        self._can_interface.uwb_start_tx_sts(channel, antenna_config=antenna_config)
        new_power_dbm_mhz = await self._fsw.measure_sts(channel)
        self._can_interface.uwb_stop_testmodes()

        self._logger.debug(f"STS measurement on channel {channel}, antenna {antenna_config.name} completed: "
                            f"Power: {new_power_dbm_mhz} dBm/MHz")

        return new_power_dbm_mhz

    async def _measure_radar(self, channel: int):
        self._logger.debug(f"Measuring Radar on channel {channel}")

        self._can_interface.uwb_start_tx_radar(channel)
        new_power_dbm_mhz = await self._fsw.measure_radar(channel)
        self._can_interface.uwb_stop_radar()

        self._logger.debug(f"Radar measurement on channel {channel} completed: Power: {new_power_dbm_mhz} dBm/MHz")

        return new_power_dbm_mhz

    def _needs_measurement(self,
                           calibration: Settings,
                           skip_non_calib_measurements: bool):
        if skip_non_calib_measurements and not calibration.needs_calibration():
            self._logger.debug(f"Skipping measurement for now as no calibration is needed for this setting")
            return False

        if calibration.is_measured():
            # Device was measured at least once
            if calibration.needs_calibration():
                # Device measured and needs calibration
                if calibration.is_calibrated():
                    # Device measured and calibrated, no further measurement needed
                    self._logger.debug(f"Skipping measurement as it is already measured and calibrated")
                    return False
                else:
                    # Device measured, but not calibrated, measurement needed
                    self._logger.debug(f"Measurement done but not calibrated yet")
            else:
                # Device measured, no calibration needed
                self._logger.debug(f"Skipping measurement as it is already measured")
                return False
        else:
            self._logger.debug(f"Measurement pending")

        return True

    def _take_screenshot(self,
                         skip_non_calib_measurements: bool,
                         needs_measurement: bool):
        if skip_non_calib_measurements:
            # If we skip non-calibration measurements, we only take a screenshot if device is properly calibrated
            if needs_measurement:
                # Device is not calibrated, no screenshot needed
                self._logger.debug(f"Skipping screenshot as device is not calibrated")
                return False
            else:
                self._logger.debug(f"Taking screenshot as device is calibrated")
                # Device is calibrated, screenshot needed
                pass
        else:
            # If we do not skip non-calibration measurements, we take a screenshot always
            self._logger.debug(f"Taking screenshot non-calibration measurements")
            pass

        return True

    async def measure_device(self,
                             skip_non_calib_measurements: bool = False,
                             export_json: bool = False):
        self._logger.info("Starting device measurement...")

        for antenna_calib in self._antenna_configs:
            antenna_config = antenna_calib.antenna_config
            calibration = antenna_calib.calibration

            self._logger.info(f"Processing {calibration.__class__.__name__} for {antenna_config.name}, "
                              f"channel {calibration.channel.channel_idx}")

            if not self._needs_measurement(calibration, skip_non_calib_measurements):
                self._logger.info(f"Skipping measurement")
                continue

            if isinstance(calibration, FrequencySettings):
                self._logger.info(f"Measuring CW-Frequency...")

                frequency_mhz, power_dbm = await self._measure_cw(channel=calibration.channel.channel_idx,
                                                                  antenna_config=antenna_config)

                self._logger.info(f"CW measurement completed: "
                                  f"Frequency = {frequency_mhz} MHz, Power = {power_dbm} dBm")

                measurement_value = calibration.freq_mhz_to_ppm(frequency_mhz)
            elif isinstance(calibration, StsFrameSettings):
                self._logger.info(f"Measuring STS power...")

                dbm_mhz = await self._measure_sts(channel=calibration.channel.channel_idx,
                                                  antenna_config=antenna_config)

                self._logger.info(f"STS measurement completed: "
                                     f"Power = {dbm_mhz} dBm/MHz")

                measurement_value = dbm_mhz
            elif isinstance(calibration, RadarFrameSettings):
                self._logger.info(f"Measuring Radar power...")

                dbm_mhz = await self._measure_radar(channel=calibration.channel.channel_idx)

                self._logger.info(f"Radar measurement completed: Power = {dbm_mhz} dBm/MHz")

                measurement_value = dbm_mhz
            elif isinstance(calibration, CwPowerSettings):
                self._logger.info(f"Measuring CW-power...")

                frequency_mhz, power_dbm = await self._measure_cw(channel=calibration.channel.channel_idx,
                                                 antenna_config=antenna_config)

                self._logger.info(f"CW measurement completed: "
                                  f"Frequency = {frequency_mhz} MHz, Power = {power_dbm} dBm",)

                measurement_value = power_dbm
            else:
                self._logger.error(f"Unknown calibration type for {antenna_config.name}, channel {calibration.channel.channel_idx}")
                continue

            calibration.update_value(measurement_value)

            if self._take_screenshot(skip_non_calib_measurements,
                                     self._needs_measurement(calibration, skip_non_calib_measurements)):
                self._logger.info(f"Taking screenshot as no more measurements needed for this setting")
                self._fsw.take_screenshot()

        if export_json:
            self._export_json()

    async def calibrate_device(self):
        self._logger.info("Starting device calibration...")

        for antenna_calib in self._antenna_configs:
            calibration_type = antenna_calib.calibration.__class__.__name__
            self._logger.info(f"Loading {calibration_type} for {antenna_calib.antenna_config.name}, "
                              f"channel {antenna_calib.calibration.channel.channel_idx}")
            await antenna_calib.load_calibration_hmm(self._can_interface)

        await self.measure_device(skip_non_calib_measurements=True,
                                  export_json=False)

        for idx in range(3):
            if self._all_calibrated():
                break
            self._logger.info(f"Calibration iteration {idx}, recalibrating...")

            for antenna_calib in self._antenna_configs:
                calibration_type = antenna_calib.calibration.__class__.__name__
                self._logger.info(f"Re-uploading {calibration_type} for {antenna_calib.antenna_config.name}, "
                                    f"channel {antenna_calib.calibration.channel.channel_idx}")
                await antenna_calib.upload_calibration_hmm(self._can_interface)

            await asyncio.sleep(3)  # Wait for device to apply calibration changes

            await self.measure_device(skip_non_calib_measurements=True,
                                      export_json=False)

        if self._all_calibrated():
            self._logger.info("All parameters calibrated successfully!")
        else:
            for antenna_calib in self._antenna_configs:
                antenna_config = antenna_calib.antenna_config
                calibration = antenna_calib.calibration
                calibration_type = antenna_calib.calibration.__class__.__name__
                if calibration.needs_calibration() and not calibration.is_calibrated():
                    self._logger.warning(f"{calibration_type} for {antenna_config.name}, "
                                         f"channel {calibration.channel.channel_idx} failed!"
                                         f" Current value: {calibration.get_current_value()}, "
                                         f"Target value: {calibration.get_target_value()}")

        # measure settings which do not need calibration after device is fully calibrated
        self._logger.info("Measuring settings which do not need calibration after device is fully calibrated")
        await self.measure_device(skip_non_calib_measurements=False,
                                  export_json=True)
        self._logger.info("Device calibration completed")

    def log_error(self, error_message: str):
        self._logger.error(error_message)


async def main():
    try:
        serial_number = input("Enter the serial number of the device: ")
        fbd6 = None
        try:
            fbd6 = FBD6(serial_number=serial_number)

            if fbd6.locked:
                await fbd6.measure_device(export_json=True)
            else:
                await fbd6.calibrate_device()
        except Exception as e:
            if fbd6 is not None:
                fbd6.log_error(str(e))
            raise
    except KeyboardInterrupt:
        print("Measurement interrupted by user!")



if __name__ == '__main__':
    asyncio.run(main())