import logging
import coloredlogs
import os
import time

SERIAL_NR = None


def create_logger(log_name: str) -> logging.Logger:
    """
    Create a logger for CAN messages.
    """
    global SERIAL_NR
    if SERIAL_NR is None:
        SERIAL_NR = time.strftime("%Y%m%d-%H%M%S")

    base_path = os.path.join(os.path.abspath("."), "log", SERIAL_NR)
    if not os.path.exists(base_path):
        os.makedirs(base_path)
    log_file_path = os.path.join(base_path, f"{log_name}.log")


    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)

    format_str = "%(asctime)s [%(filename)24s (line %(lineno)4d)] - %(levelname)8s - %(message)s"

    file_handler = logging.FileHandler(log_file_path, mode="w+", encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(format_str))
    file_handler.setLevel(logging.DEBUG)

    if log_name == "base":
        console_handler = logging.StreamHandler()
        coloredlogs.install(level="INFO", logger=logger, stream=console_handler.stream,
                            fmt=format_str)

    logger.addHandler(file_handler)

    return logger


def bytes_needed(n: int):
    """
    Calculate the number of bytes needed to represent an integer.
    :param n: Integer value
    :return: Number of bytes needed
    """
    if n == 0:
        return 1
    return (n.bit_length() + 7) // 8


def db_to_hmm(value_db: float, num_bytes: int = 1):
    """
    Convert dB value to HPM value.

    :param value_db: Value in dB
    :param num_bytes: Number of bytes to represent the value
    :return: hmm value or bytes representation of the value
    """
    value_hmm = round(value_db / 0.17)
    bytes_required = bytes_needed(value_hmm)

    if bytes_required > num_bytes:
        raise ValueError(f"Value {value_db} requires {bytes_required} bytes, but {num_bytes} bytes were specified.")

    output_bytes = value_hmm.to_bytes(num_bytes, "big", signed=True)
    output_bytes = list(output_bytes)  # Convert to list for consistency

    if len(output_bytes) == 1:
        return output_bytes[0]  # Return as single byte if only one byte is needed
    else:
        return output_bytes


def ppm_to_hmm(ppm_value: float, num_bytes: int = 1):
    """
    Convert PPM value to HPM value.

    :param ppm_value: PPM value to convert
    :param num_bytes: Number of bytes to represent the value
    :return: hmm value or bytes representation of the value
    """
    value_hmm = round(ppm_value * 10)
    bytes_required = bytes_needed(value_hmm)

    if bytes_required > num_bytes:
        raise ValueError(f"Value {ppm_value} requires {bytes_required} bytes, but {num_bytes} bytes were specified.")

    output_bytes = value_hmm.to_bytes(num_bytes, "big", signed=True)
    output_bytes = list(output_bytes)

    if len(output_bytes) == 1:
        return output_bytes[0]  # Return as single byte if only one byte is needed
    else:
        return output_bytes



def int_to_hpm(val: float, val_in_dB: bool = False):
    if val_in_dB:
        val = val / 0.17

    if val < 0:
        val = 256 - abs(val)

    return round(val)


def get_ppm_offset(f_ghz_correct: float, f_ghz_measured: float):
    ppm_offset = (f_ghz_measured - f_ghz_correct) / f_ghz_correct * 1e6
    ppm_offset -= 3

    drift_byte_high = 0
    drift_byte_low = int_to_hpm(ppm_offset*10)

    if ppm_offset < 0:
        drift_byte_high = 255

    return round(ppm_offset, 2), drift_byte_high, drift_byte_low


def get_hmm_power_offset(value: float, additional_offset_hmm: float = 0.0):
    output = -3.6 - value
    output += 0.2  # additional offset (EoL calibration is with margin to upper limits)
    output -= 0.17 * additional_offset_hmm

    return int_to_hpm(output, val_in_dB=True)




if __name__ == '__main__':
    print(bytes_needed(10))
    print(bytes_needed(-10))
    print(bytes_needed(0))
    print(bytes_needed(-128))
    print(bytes_needed(129))

    exit(0)


    while True:
        ant2_ch9_cw_center_freq_ghz = float(input('Enter the center frequency in GHz of the CW signal at the output of the antenna 2 channel 9: '))
        ant2_ch9_cw_power_dbm = float(input('Enter the power in dBm of the CW signal at the output of the antenna 2 channel 9: '))

        ppm_offset, drift_byte_high, drift_byte_low = get_ppm_offset(7.9872, ant2_ch9_cw_center_freq_ghz)
        print("\n\n")
        print(f"PPM Offset: {ppm_offset} \nDrift Byte High: {drift_byte_high} \nDrift Byte Low: {drift_byte_low}")

        print("\n\n")
        print(f"Ant1_Ch8_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=5.12)}, Target: -50.4 dBm/MHz")
        print(f"Ant1_Ch9_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=1.86)}, Target: -54,3 dBm/MHz")
        print(f"Ant2_Ch8_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=5.36)}, Target: -45.9 dBm/MHz")
        print(f"Ant2_Ch9_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=0.0)}, Target: -47.1 dBm/MHz")
        print(f"Ant3_Ch8_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=-7.91+0.75)}, Target: -48.8 dBm/MHz")
        print(f"Ant3_Ch9_Offset: {get_hmm_power_offset(ant2_ch9_cw_power_dbm, additional_offset_hmm=-7.91)}, Target: -49.7 dBm/MHz")
        print()
        print(f"CPD_Offset_Ch8: 34, Target: -49.1 dBm/MHz")
        print(f"CPD_Offset_Ch9: 34, Target: -53.4 dBm/MHz")

        print("\n\n\n\n")



