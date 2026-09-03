import asyncio
import os
import socket
import time

from RsInstrument import RsInstrument

from utils import create_logger


def get_device(device_name: str):
    device_address = RsInstrument.list_resources("?*","rs")
    device_address = [address for address in device_address if "TCPIP" in address or "USB" in address]

    for address in device_address:
        device = RsInstrument(address, id_query=True, reset=False)

        if device_name in device.full_instrument_model_name:
            return device
        device.close()

    return None

class Device:
    def __init__(self):
        self._logger = create_logger(log_name="rs")


class DstDevice(Device):
    def __init__(self, host: str, port: int):
        super().__init__()
        self._host = host
        self._port = port

        if not self._test_tcp_port():
            raise ConnectionError(f"Could not connect to {self._host}:{self._port}")

    def _test_tcp_port(self):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((self._host, self._port))
                print(f"Connected to {self._host}:{self._port}")
                return True
        except socket.error:
            print(f"Connection to {self._host}:{self._port} failed")
            return False

    def query(self, command: str):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((self._host, self._port))
            s.sendall(command.encode())
            data = s.recv(1024)

        return data.decode()


class FSW(Device):
    def __init__(self, screenshot_path: str =None):
        super().__init__()
        self._screenshot_path = screenshot_path
        self._device = get_device("FSW")  # Replace with the actual device name
        self._init_device()
        self._load_settings()

    def __del__(self):
        self._logger.info("Closing FSW device connection")
        self._device.go_to_local()
        self._device.close()

    def _write_str(self, command: str, with_opc: bool):
        """
        Write a command string to the device.
        :param command: Command string to send to the device
        """
        if with_opc:
            self._device.write_str_with_opc(command)
            self._logger.debug(f"Command sent with OPC: {command}")
        else:
            self._device.write_str(command)
            self._logger.debug(f"Command sent without OPC: {command}")

    def _query_opc(self):
        self._logger.debug("Querying OPC")
        self._device.query_opc()

    def _query_float(self, command: str):
        """
        Query a float value from the device.
        :param command: Command string to send to the device
        :return: Float value returned by the device
        """
        self._logger.debug(f"Querying float value with command: {command}")
        value = self._device.query_float(command)
        self._logger.debug(f"Received float value: {value}")
        return value

    def _init_device(self):
        self._device.visa_timeout = 5000
        self._device.opc_timeout = 5000
        self._device.instrument_status_checking = True

        self._logger.debug(f"Driver Version: {self._device.driver_version}")
        self._logger.debug(f"SpecAn IDN: {self._device.idn_string}")
        self._logger.debug(f"SpecAn Options: {','.join(self._device.instrument_options)}")

        self._device.clear_status()
        self._device.reset()
        self._write_str("INIT:CONT OFF", with_opc=False)  # Switch OFF the continuous sweep
        self._write_str("SYST:DISP:UPD ON", with_opc=False)  # Display update ON - switch OFF after debugging

        self._logger.info("Device initialized")


    def _load_settings(self):
        self._write_str("MMEM:LOAD:STAT 1, \'C:\R_S\Instr\\user\daniel-g\\auto-calib\'", with_opc=False)
        self._query_opc()
        self._logger.info("Settings loaded from C:\\R_S\\Instr\\user\\daniel-g\\auto-calib")

    def take_screenshot(self):
        if not os.path.exists(self._screenshot_path):
            os.makedirs(self._screenshot_path)
        temp_path = os.path.join(self._screenshot_path,
                                 time.strftime("%Y-%m-%d_%H-%M-%S.png"))

        self._write_str("HCOP:DEV:LANG PNG", with_opc=False)
        self._write_str(r"MMEM:NAME 'c:\temp\Temp_Screenshot.png'", with_opc=False)
        self._write_str("HCOP:IMM", with_opc=False)  # Make the screenshot now
        self._query_opc()  # Wait for the screenshot to be saved
        self._device.read_file_from_instrument_to_pc(source_instr_file=r"c:\temp\Temp_Screenshot.png",
                                                     target_pc_file=temp_path)
        self._query_opc()  # Wait for the screenshot to be saved
        self._logger.info(f"Screenshot taken and saved to {temp_path}")

    def _measure(self):
        self._logger.debug("Starting measurement")
        self._write_str("INIT", with_opc=True)  # Start the measurement
        self._query_opc()
        self._logger.debug("Measurement done")

    async def measure_cw(self, channel: int):
        self._logger.info(f"Measuring CW on channel {channel}")

        self._write_str(f"INST:SEL \'cw ch{channel} 1mhz span\'", with_opc=False)
        self._device.VisaTimeout = 2000
        self._query_opc()

        self._measure()

        freq_hz = self._query_float("CALC:MARK1:X?")
        power_dbm = self._query_float("CALC:MARK1:Y?")
        self._logger.info(f"CW measurement on channel {channel} completed: "
                          f"Frequency: {freq_hz / 1e9} GHz, Power: {power_dbm} dBm")

        return freq_hz, power_dbm

    async def measure_sts(self, channel: int):
        self._logger.info(f"Measuring STS on channel {channel}")

        self._write_str(f"INST:SEL \'ch{channel} sts\'", with_opc=False)
        self._device.opc_timeout = 40000
        self._device.VisaTimeout = 40000
        self._query_opc()

        self._measure()

        self._device.opc_timeout = 3000

        power_dbm = self._query_float('CALC:MARK1:Y?')
        self._logger.info(f"STS measurement on channel {channel} completed: Power: {power_dbm} dBm/MHz")

        return power_dbm

    async def measure_radar(self, channel: int):
        self._logger.info(f"Measuring Radar on channel {channel}")

        self._write_str(f"INST:SEL \'ch{channel} radar\'", with_opc=False)
        self._device.opc_timeout = 60000
        self._device.VisaTimeout = 60000
        self._query_opc()

        self._measure()

        self._device.opc_timeout = 3000

        power_dbm = self._query_float('CALC:MARK1:Y?')
        self._logger.info(f"Radar measurement on channel {channel} completed: Power: {power_dbm} dBm/MHz")

        return power_dbm


async def main():
    temp_path = os.path.join(os.path.abspath("."),
                             "export",
                             "test")
    fsw = FSW(screenshot_path=temp_path)
    # await asyncio.sleep(3)
    await fsw.measure_cw(9)
    await asyncio.sleep(3)
    await fsw.measure_sts(9)
    await asyncio.sleep(3)
    await fsw.measure_radar(9)
    # await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())

