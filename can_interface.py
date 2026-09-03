import asyncio
import logging
import time
from abc import abstractmethod, ABC
from dataclasses import dataclass

from enum import Enum

import can
from can.interfaces.vector import VectorBus

from utils import create_logger

APP_CHANNEL = 0
APP_NAME = "python-can"


class CanListener(can.Listener):
    def __init__(self, logger: logging.Logger):
        super().__init__()
        self._message_buffer = []
        self._logger = logger
        logger.info("CAN Listener initialized.")

    def on_message_received(self, msg: can.Message):
        print(msg)
        self._logger.debug(str(msg))
        self._message_buffer.append(msg)

    def wait_hmm_confirmation(self, expected_response: can.Message, timeout: float = 1.0):
        self._message_buffer.clear()

        start_time = time.time()
        while (time.time() - start_time) <= timeout:
            for received_msg in self._message_buffer:
                if received_msg.arbitration_id == expected_response.arbitration_id:
                    if received_msg.data[0] == expected_response.data[0]:
                        self._logger.info(f"Received expected message: {received_msg}")
                        return received_msg
            self._message_buffer.clear()
            time.sleep(0.05)

        self._logger.warning(f"Did not receive expected message: {expected_response} within timeout ({timeout}s).")
        return None

    def wait_response(self, arbitration_id: int, timeout: float = 1.0):
        self._message_buffer.clear()

        start_time = time.time()
        while (time.time() - start_time) <= timeout:
            for received_msg in self._message_buffer:
                if received_msg.arbitration_id == arbitration_id:
                    self._logger.info(f"Received message: {received_msg}")
                    return received_msg
            self._message_buffer.clear()
            time.sleep(0.05)

        self._logger.warning(f"Did not receive expected response within timeout ({timeout}s).")
        return None

    def get_buffered_messages(self):
        return self._message_buffer

@dataclass
class HMMConfig:
    variant_name: str
    variant_id: int
    hmm_rx_id: int
    hmm_tx_id: int
    cpd_device_address: int = None
    cpd_command_arbitration_id: int = None
    cpd_data_arbitration_id: int = None


class CanInterface(ABC):
    def __init__(self,
                 hw_type: str,
                 can_case_channel: int):
        self._logger = create_logger(log_name="can")
        self._hw_type = hw_type
        self._can_case_channel = can_case_channel

        configs = can.detect_available_configs(interfaces="vector")
        config = list(filter(lambda x: x["hw_channel"] == can_case_channel and hw_type in x["hw_type"].name, configs))

        if not config:
            raise RuntimeError(f"No suitable hardware found for hw_channel: {can_case_channel} and hw_type: {hw_type}")

        config = config[0]
        VectorBus.set_application_config(app_name=APP_NAME, app_channel=APP_CHANNEL, **config)

        self._bus = VectorBus(channel=APP_CHANNEL, app_name=APP_NAME, fd=True)
        self._bus_listener = CanListener(self._logger)
        self._bus_notifier = can.Notifier(self._bus, [self._bus_listener], timeout=1)
        self._logger.info(f"Initialized CAN interface on '{hw_type}' on channel {can_case_channel}")

        self.hmm_config = None

    def __del__(self):
        self._logger.info("Shutting down CAN interface.")

        if self._bus is not None:
            self._bus.stop_all_periodic_tasks()
            self._bus_notifier.stop()
            self._bus_listener.stop()
            self._bus.shutdown()

        self._logger.info("CAN interface shutdown complete.")

    @abstractmethod
    def get_connected_devices(self) -> list[HMMConfig]:
        """Load the HMM IDs based on the variant type."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    def connect(self):
        self._hmm_init()
        self._hmm_login()
        self._logger.info(f"Successfully connected to {self.hmm_config.variant_name} (ID: {self.hmm_config.variant_id}).")

    def _hmm_init(self):
        """Start a periodic keep-alive message to the HMM device."""
        keep_alive = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                 data=[],
                                 is_extended_id=False)

        self._bus.send_periodic(keep_alive, period=0.2)
        self._logger.info(f"Initialized HMM with TX ID: {self.hmm_config.hmm_tx_id}, RX ID: {self.hmm_config.hmm_rx_id}, "
                          f"Variant: {self.hmm_config.variant_name} (ID: {self.hmm_config.variant_id})")

    @abstractmethod
    def _hmm_login(self):
        """Initialize the HMM device."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    @abstractmethod
    def is_locked(self):
        raise NotImplementedError("This method should be implemented in subclasses.")

    @abstractmethod
    def uwb_stop_testmodes(self):
        """Stop all test modes on the HMM device."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    @abstractmethod
    def hmm_read_param(self, parameter_address: list[int]) -> int:
        """Read a parameter from the HMM device."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    @abstractmethod
    def hmm_write_param(self, parameter_address: list[int], new_value: int) -> None:
        """Write a parameter to the HMM device."""
        raise NotImplementedError("This method should be implemented in subclasses.")

    def get_variant_type(self) -> int:
        """Get the variant type of the HMM device."""
        if self.hmm_config.variant_id is None:
            raise ValueError("Variant ID is not set. Please check the connection and try again.")
        return self.hmm_config.variant_id

    def _send_hmm_cmd(self, can_message: can.Message):
        expected_response = can.Message(arbitration_id=self.hmm_config.hmm_rx_id,
                                        data=[can_message.data[0]],
                                        is_extended_id=False)

        for idx in range(3):
            self._logger.debug(f"Sending HMM command: {can_message}")
            self._bus.send(can_message)
            msg = self._bus_listener.wait_hmm_confirmation(expected_response)
            if msg is not None:
                return msg

        raise TimeoutError(f"Did not receive expected response for message: {can_message} after 3 attempts.")




class FBD6Can(CanInterface):
    class AntennaConfig(Enum):
        ANTENNA_1 = 0b0001
        TX1_RX1 = 0b0001
        TX1_RX3 = 0b0011
        TX1_RX1_RX2 = 0b0101

        ANTENNA_2 = 0b0000
        TX2_RX2 = 0b0000
        TX2_RX3 = 0b0010
        TX2_RX2_RX3 = 0b0100

        ANTENNA_3 = 0b1010
        TX3_RX3 = 0b1010
        TX3_RX1 = 0b1001
        TX3_RX1_RX3 = 0b1101

        RADAR = 0b1111

        def get_tx_antenna_idx(self):
            if self == FBD6Can.AntennaConfig.ANTENNA_1:
                return 1
            elif self == FBD6Can.AntennaConfig.ANTENNA_2:
                return 2
            elif self == FBD6Can.AntennaConfig.ANTENNA_3:
                return 3
            else:
                raise ValueError("Invalid antenna configuration for TX antenna index.")

    class CalibrationParameterAddress(Enum):
        p_n_FBD6_UWB_AoA_correction_offset_LowByte = [0x04, 0x27]
        p_n_FBD6_UWB_AoA_correction_offset_HighByte = [0x04, 0x28]
        p_n_FBD6_UWB_AoA_correction_slope_LowByte = [0x04, 0x29]
        p_n_FBD6_UWB_AoA_correction_slope_HighByte = [0x04, 0x2A]

        p_n_FBD6_UWB_oscillator_drift_LowByte = [0x05, 0x1D]
        p_n_FBD6_UWB_oscillator_drift_HighByte = [0x05, 0x1E]

        p_n_FBD6_UWB_CPD_Offset_TxPower = [0x05, 0x23]

        p_n_FBD6_UWB_TxPower_Ch8_Ant1_Offset = [0x0B, 0x0E]
        p_n_FBD6_UWB_TxPower_Ch8_Ant2_Offset = [0x0B, 0x10]
        p_n_FBD6_UWB_TxPower_Ch8_Ant3_Offset = [0x0B, 0x12]
        p_n_FBD6_UWB_TxPower_Ch9_Ant1_Offset = [0x0B, 0x14]
        p_n_FBD6_UWB_TxPower_Ch9_Ant2_Offset = [0x0B, 0x16]
        p_n_FBD6_UWB_TxPower_Ch9_Ant3_Offset = [0x0B, 0x18]


    def __init__(self, hw_type: str,can_case_channel: int):
        self._cpd_arbitration_id = 0x12E
        self._cpd_data_arbitration_id = None
        self._cpd_device_address = None

        super().__init__(hw_type, can_case_channel)

    def __del__(self):
        self._logger.info("Shutting down FBD6 CAN interface.")
        if self.hmm_config is not None:
            self.uwb_stop_testmodes()
            self.uwb_stop_radar()
            super().__del__()

    def get_connected_devices(self):
        self._logger.info("Loading HMM IDs...")
        ping_msg = can.Message(arbitration_id=0x00,
                               data=[],
                               is_extended_id=False)
        self._bus.send(ping_msg)
        time.sleep(1)
        self._bus.send(ping_msg)
        time.sleep(1)
        self._bus.send(ping_msg)
        time.sleep(1)
        buffered_messages = self._bus_listener.get_buffered_messages()

        hmm_configs = []
        for msg in buffered_messages:
            if msg.data[0] != 0x02:
                continue

            config = None
            if msg.arbitration_id == 0x96:
                config = HMMConfig(
                    variant_name="VM",
                    variant_id=14,
                    hmm_rx_id=0x44D,
                    hmm_tx_id=0x44C,
                    cpd_device_address=0x01,
                    cpd_data_arbitration_id=0x14A,
                    cpd_command_arbitration_id=0x12E
                )
                hmm_configs.append(config)
                self._logger.info(f"Detected FBD6 VM variant {config}")
            elif msg.arbitration_id == 0x97:
                config = HMMConfig(
                    variant_name="HM",
                    variant_id=24,
                    hmm_rx_id=0x44F,
                    hmm_tx_id=0x44E,
                    cpd_device_address=0x02,
                    cpd_data_arbitration_id=0x14B,
                    cpd_command_arbitration_id=0x12E
                )
                hmm_configs.append(config)

            elif msg.arbitration_id == 0x9C:
                config = HMMConfig(
                    variant_name="HL",
                    variant_id=34,
                    hmm_rx_id=0x459,
                    hmm_tx_id=0x458
                )
                hmm_configs.append(config)

            if config:
                self._logger.info(f"Detected FBD6 {config}")
            else:
                self._logger.warning("Couldn't detect any FBD6!")

        return hmm_configs

    # 'HMM' Commands
    def _hmm_login(self):
        init_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                   data=[0xC3, 0x48, 0x50, 0x4D, 0x00, 0x00, 0x00, 0x00],
                                   is_extended_id=False)
        self._send_hmm_cmd(init_message)
        self._read_temperature()
        self._logger.info("HMM login completed.")

    def _read_temperature(self):
        # reading temperature to ensure oscillator offset is properly set (BUG in i450-SW)
        read_temp_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                        data=[0x20, 0x00, 0x20],
                                        is_extended_id=False)
        self._send_hmm_cmd(read_temp_message)
        self.uwb_stop_testmodes()
        self._logger.info("HMM Temperature read completed.")

    def is_locked(self) -> bool:
        """Check if the HMM is locked."""
        locked_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                     data=[0xD9, 0x01],
                                     is_extended_id=False)
        try:
            self._send_hmm_cmd(locked_message)
            return False
        except TimeoutError:
            self._logger.warning("Failed to receive response. Device is locked.")
            return True

    def uwb_stop_testmodes(self):
        stop_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                   data=[0x20, 0x00],
                                   is_extended_id=False)
        self._send_hmm_cmd(stop_message)
        self._logger.info("Stopped all UWB test modes.")

    def _antenna_select(self, antenna_config: AntennaConfig):
        port_config = int(antenna_config.value >> 1)
        port_config_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                             data=[0x10, 0x00, port_config],
                                             is_extended_id=False)
        self._send_hmm_cmd(port_config_message)

        spdt_config = antenna_config.value & 0b0001
        spdt_config_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                          data=[0x30, spdt_config, 0x00, 0x00, 0x00, 0x03, 0xE8],
                                          is_extended_id=False)
        self._send_hmm_cmd(spdt_config_message)
        self._logger.info(f"Selected antenna configuration: {antenna_config.name} "
                          f"(TX Antenna: {antenna_config.get_tx_antenna_idx()})")

    # UWB testmodes

    def read_serial_number(self) -> int:
        serial_number_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                            data=[0x08],
                                            is_extended_id=False)
        response = self._send_hmm_cmd(serial_number_message)

        serial_number = response.data[1:5]
        serial_number = int.from_bytes(serial_number, "big", signed=False)
        self._logger.info(f"Read serial number: {serial_number}")

        return serial_number

    def read_nonce(self) -> int:
        serial_number_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                            data=[0x09],
                                            is_extended_id=False)
        response = self._send_hmm_cmd(serial_number_message)

        serial_number = response.data[1:5]
        serial_number = int.from_bytes(serial_number, "big", signed=False)
        self._logger.info(f"Read serial number: {serial_number}")

        return serial_number

    async def uwb_cw_burst(self, channel: int, antenna_config: AntennaConfig):
        self._antenna_select(antenna_config)

        uwb_cw_start = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                   data=[0x20, 0x01, channel, 0x00, 0x00, 0x00, 0x00, 0x0C],
                                   is_extended_id=False)

        self._logger.info(f"Starting UWB CW burst on channel {channel} with antenna configuration {antenna_config.name}.")
        self._send_hmm_cmd(uwb_cw_start)
        await asyncio.sleep(0.01)
        self.uwb_stop_testmodes()
        self._logger.info("UWB CW burst stopped.")

    def uwb_start_tx_sts(self, channel: int, antenna_config: AntennaConfig,
                         interval_ms: int = 5):
        self._antenna_select(antenna_config)

        uwb_tx_sts_start = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                       data=[0x20, 0x02, channel, 0x00, 0x00, 0x00, 0x00, interval_ms],
                                       is_extended_id=False)
        self._send_hmm_cmd(uwb_tx_sts_start)
        self._logger.info(f"Starting UWB STS transmission on channel {channel} with antenna configuration {antenna_config.name} and interval {interval_ms} ms.")

    def uwb_start_tx_radar(self, channel: int):
        if self.hmm_config.cpd_command_arbitration_id is None:
            return

        cpd_channel = 8 if channel == 9 else 4
        uwb_tx_radar_start = can.Message(arbitration_id=self.hmm_config.cpd_command_arbitration_id,
                                         is_fd=True,
                                         dlc=20,
                                         data=[self.hmm_config.cpd_device_address, 0x00, 0x01, 0x00, 0x01, cpd_channel],
                                         is_extended_id=False)

        for idx in range(3):
            self._bus.send(uwb_tx_radar_start)
            response = self._bus_listener.wait_response(self.hmm_config.cpd_data_arbitration_id)
            if response is not None:
                self._logger.info(f"Started UWB radar transmission on channel {channel}.")
                return

        raise TimeoutError(f"Did not receive expected response for message: {uwb_tx_radar_start} after 3 attempts.")

    def uwb_stop_radar(self):
        if self.hmm_config.cpd_command_arbitration_id is None:
            return

        stop_message = can.Message(arbitration_id=self.hmm_config.cpd_command_arbitration_id,
                                   is_fd=True,
                                   data=[self.hmm_config.cpd_device_address, 0x00, 0x04],
                                   dlc=20,
                                   is_extended_id=False)

        for idx in range(3):
            self._bus.send(stop_message)
            response = self._bus_listener.wait_response(self._cpd_data_arbitration_id, timeout=0.5)
            if response is None:
                self._logger.info(f"Stopped UWB radar transmission.")
                return

        raise TimeoutError(f"Did not receive expected response for message: {stop_message} after 3 attempts.")

    # Calibration Values

    async def hmm_read_param(self, parameter_address: CalibrationParameterAddress) -> int:
        read_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                   data=[0xD9, 0x01] + parameter_address.value,
                                   is_extended_id=False)

        response = self._send_hmm_cmd(read_message)
        response_data = response.data[1]

        self._logger.info(f"Read calibration value for {parameter_address.name}: {response_data}")
        return response_data

    async def hmm_write_param(self, parameter_address: CalibrationParameterAddress, new_value: int) -> None:
        write_message = can.Message(arbitration_id=self.hmm_config.hmm_tx_id,
                                    data=[0xD1, 0x01] + parameter_address.value + [new_value],
                                    is_extended_id=False)

        for idx in range(3):
            response = self._send_hmm_cmd(write_message)
            if int(response.data[1]) == new_value:
                self._logger.info(f"Successfully set calibration value for {parameter_address.name} to {new_value}.")
                time.sleep(1)
                self._read_temperature()
                return

        raise ValueError(f"Failed to set calibration value for {parameter_address.name} after 3 attempts. ")




async def main():
    fbd6 = FBD6Can(can_case_channel=2, hw_type="VN1640")
    hmm_config = fbd6.get_connected_devices()
    fbd6.hmm_config = hmm_config[0]
    fbd6.connect()

    # await asyncio.sleep(1)
    # val = await fbd6.get_calibration_value(FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_TxPower_Ch8_Ant1_Offset)
    # await fbd6.set_calibration_value(FBD6Can.CalibrationParameterAddress.p_n_FBD6_UWB_TxPower_Ch8_Ant1_Offset, new_value=val+1)
    # input()

    fbd6.uwb_start_tx_radar(channel=9)
    await asyncio.sleep(5)
    fbd6.uwb_stop_radar()

if __name__ == '__main__':
    asyncio.run(main())



