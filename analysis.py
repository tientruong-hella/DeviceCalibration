import json
import os
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt


def load_measurement_data():
    path = os.path.join(os.path.abspath("."), "export", "measurement_data")

    measurement_data = []
    for file in os.listdir(path):
        if file.endswith(".json"):
            file_path = os.path.join(path, file)
            with open(file_path, 'r') as f:
                data = json.load(f)
                measurement_data.append(data)

    return measurement_data


def get_calibration_type(measurement_data: json, calibration_type: str, antenna_config: str = None) -> list:
    """
    Determines the calibration type based on the measurement data and type.

    :param measurement_data: Measurement data in JSON format
    :param calibration_type: Type of calibration (e.g., 'sts', 'radar')
    :return: Calibration type as a string
    """
    calibrations = []

    for calibrations_list in measurement_data:
        relevant_calibrations = [calibration for calibration in calibrations_list
                                 if calibration["calibration_type"] == calibration_type]

        if antenna_config is not None:
            relevant_calibrations = [calibration for calibration in relevant_calibrations
                                     if calibration["antenna_config"] == antenna_config]

        relevant_calibrations = [calibration["calibration"] for calibration in relevant_calibrations]
        calibrations.extend(relevant_calibrations)

    return calibrations


def plot_normal_distribution(data: np.array,
                             target_values: np.array = None,
                             legend: list[str] = None,
                             xlabel: str = "Value",
                             title: str = "Normal Distribution"):
    """
    Plots a normal distribution for the given data.

    :param data: List of data points
    :param legend: Legend for the plot
    """
    fig = plt.figure(figsize=(10, 6))
    colors = sns.color_palette("husl", len(data))

    for idx, value in enumerate(data):
        if legend is not None:
            label = legend[idx]
            target_label = f"{label} Target" if target_values is not None else label
        else:
            label = f"Data {idx + 1}"
            target_label = f"{label} Target" if target_values is not None else label

        sns.kdeplot(value, linewidth=2, label=label, color=colors[idx])
        plt.axvline(target_values[idx], color=colors[idx], linestyle='--', linewidth=2, label=target_label)

    ticks = np.round(plt.gca().get_xticks())
    plt.xticks(np.arange(min(ticks), max(ticks) + 0.2, 0.5))
    plt.grid()
    plt.legend()

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel("Probability")



def extrac_radar_offset():
    """
    Extracts the radar offset from the measurement data.

    :return: Radar offset value
    """
    measurement_data = load_measurement_data()

    configs = [data["antenna_configs"] for data in measurement_data]
    radar_data = get_calibration_type(configs, "RadarFrameSettings")

    measurements_ch9 = [data["measured_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH9"]
    target_ch9 = np.mean([data["target_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH9"])

    measurements_ch8 = [data["measured_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH8"]
    target_ch8 = np.mean([data["target_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH8"])

    deviation_error = np.array([measurements_ch9, measurements_ch8])
    target_values = np.array([target_ch9, target_ch8])

    plot_normal_distribution(data=deviation_error,
                             target_values=target_values,
                             legend=["Channel 9", "Channel 8"],
                             xlabel="Measured Value [dBm/MHz]",
                             title="Radar - Measured Spectral Density [dBm/MHz]")


def extract_sts_offset(antenna_idx: int):
    """
    Extracts the radar offset from the measurement data.

    :return: Radar offset value
    """
    measurement_data = load_measurement_data()

    configs = [data["antenna_configs"] for data in measurement_data]
    radar_data = get_calibration_type(measurement_data=configs,
                                      calibration_type="StsFrameSettings",
                                      antenna_config=f"ANTENNA_{antenna_idx}")

    measurements_ch9 = [data["measured_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH9"]
    target_ch9 = np.mean([data["target_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH9"])

    measurements_ch8 = [data["measured_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH8"]
    target_ch8 = np.mean([data["target_value_dbm_mhz"] for data in radar_data if data["channel"] == "UWB_CH8"])

    deviation_error = np.array([measurements_ch9, measurements_ch8])
    target_values = np.array([target_ch9, target_ch8])

    plot_normal_distribution(data=deviation_error,
                             target_values=target_values,
                             legend=["Channel 9", "Channel 8"],
                             xlabel="Measured Value [dBm/MHz]",
                             title=f"Antenna {antenna_idx} STS - Measured Spectral Density [dBm/MHz]")


def extract_pass_fail(antenna_idx: int, calibration_type_str: str):
    measurement_data = load_measurement_data()

    passed_samples = 0
    failed_samples = 0

    for data in measurement_data:
        serial_nr = data["serial_number"]
        antenna_configs = data["antenna_configs"]

        if "calibration" in antenna_configs[0]:
            continue

        sample_passed = True

        print(f"Sample {serial_nr}")

        for config in antenna_configs:
            calibration_type = config["calibration_type"]

            antenna_config = config["antenna_config"]
            if antenna_config != f"ANTENNA_{antenna_idx}":
                continue
            if calibration_type != calibration_type_str:
                continue

            channel = config["channel"]
            config_passed = config["passed"]

            target = [value for key, value in config.items() if 'target' in key.lower()][0]
            measured = [value for key, value in config.items() if 'measured' in key.lower()][0]
            deviation = [value for key, value in config.items() if 'deviation' in key.lower()][0]

            if not config_passed:
                sample_passed = False
            print(f"For Antenna config {antenna_config} and channel {channel}"
                  f"Target value: {target}, Measured Value: {measured}, Deviation: {deviation}")

        if sample_passed:
            passed_samples += 1
        else:
            failed_samples += 1
        print()

    print()
    print(f"Total samples passed: {passed_samples}")
    print(f"Total samples failed: {failed_samples}")




if __name__ == '__main__':
    # extract_sts_offset(antenna_idx=1)
    # extrac_radar_offset()
    # plt.show()
    extract_pass_fail(antenna_idx=3,
                      calibration_type_str="CwPowerSettings")





