import json
import os
import re
import shutil
import time

from dotenv import load_dotenv
load_dotenv()

from itac_interface import FBD6ITAC


def get_filenames():
    working_dir = os.path.join(os.path.abspath("."), "export", "measurement_data")
    filenames = os.listdir(working_dir)
    filenames = [filename for filename in filenames if filename.endswith(".json")]
    return filenames


def get_json_by_filename(filename: str):
    working_dir = os.path.join(os.path.abspath("."), "export", "measurement_data")
    filepath = os.path.join(working_dir, filename)

    if os.path.exists(filepath):
        with open(filepath, 'r') as file:
            measurement_data = json.load(file)
        return measurement_data

    return None


def fix_json():
    """
    Load all JSON files in the measurement_data folder and update them to the latest version.
    Updates will be written to the same file.
    JSON data version is specified in the .env file.
    No backup is created by this function. Backup is created by the resync_json function.

    :return:
    """
    working_dir = os.path.join(os.path.abspath("."), "measurement_data")
    create_backup(working_dir)
    files = os.listdir(working_dir)

    for file in files:
        if not file.endswith(".json"):
            continue

        filepath = os.path.join(working_dir, file)
        with open(filepath, 'r') as f:
            measurement_data = json.load(f)

        if data_version_matched(measurement_data):
            print(file + ": JSON data version matches latest version. No update necessary")
            continue
        print(f"Updating JSON file: {file} to version {os.environ['JSON_DATA_VERSION']}")

        remove_calibration_dimension(measurement_data)
        remove_units(measurement_data)
        fix_calibration_values(measurement_data)
        measurement_data["measurement_date"] = measurement_data.get("measurement_date", None)
        measurement_data["is_locked"] = measurement_data.get("is_locked", None)

        itac_read = False
        while not itac_read:
            try:
                add_itac_values(measurement_data)
                itac_read = True
            except Exception as e:
                print(f"Error reading ITAC data for {measurement_data['serial_number']}: {e}")
                time.sleep(5)

        measurement_data["json_version"] = os.environ["JSON_DATA_VERSION"]
        measurement_data = rearrange_dict(measurement_data)

        with open(filepath, 'w') as file:
            json.dump(measurement_data, file, ensure_ascii=False, indent=4)


def create_backup(working_dir: str):
    """Create a backup of the JSON files in the working directory."""
    backup_dir = os.path.join(os.path.abspath("."), "measurement_data_backup")
    if os.path.exists(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)

    shutil.copytree(src=working_dir,
                    dst=backup_dir,
                    dirs_exist_ok=True)

    print(f"Backup created in {backup_dir}")

def version_to_list(version: str) -> (list[int], int):
    """
    Converts a version string to a list of integers.
    Extracts the version number from the version string.
    Given: "1.2.3", returns ([1, 2, 3], 123)

    :param version: The version string.
    :return: A tuple containing the list of integers and the version number.
    """
    try:
        version_list = [int(num) for num in version.split(".")]
        version_number = int(version.replace(".", ""))
    except ValueError:
        raise ValueError("Version number must be numeric of type x.x.x. Given version  is \"" + version + "\".")

    if len(version_list) != 3:
        raise ValueError("Invalid version number \"" + version + "\".")

    return version_list, version_number


def data_version_matched(measurement_data: dict) -> bool:
    """
    Compares the JSON data version with the code version.
    The JSON data version is expected to be in the format x.x.x.
    The code version is expected to be in the format x.x.x in the environment variable

    :param measurement_data: The JSON data to compare.
    :return: True if the JSON data version is the same as the code version, False otherwise.
    """
    _, global_version = version_to_list(os.environ["JSON_DATA_VERSION"])
    _, json_version = version_to_list(measurement_data.get("json_version", "0.0.0")) # 0.0.0 if no version present in json

    if json_version > global_version:
        raise ValueError(f"JSON Data Version {json_version} is newer than the code version {global_version}")

    if json_version == global_version:
        return True
    else:
        return False


def remove_calibration_dimension(measurement_data: dict):
    """
    Removes the calibration dimension from the JSON data.
    Returns None, as it updates the input dictionary in place.

    :param measurement_data:
    :return:
    """
    for config in measurement_data["antenna_configs"]:
        if config.get("calibration") is None:
            continue

        calibration = config["calibration"]
        config.update(calibration)
        del config["calibration"]


def remove_units(measurement_data: dict):
    """
    Removes the unit from the JSON data.

    :param measurement_data: The JSON data to update.
    :return:
    """
    keys = ["target", "measured", "deviation", "itac_measurement"]

    for config in measurement_data["antenna_configs"]:
        for target_key in keys:
            full_key = [key for key in config.keys() if target_key in key]
            if not full_key:
                continue
            full_key = full_key[0]
            full_key = full_key.split("_")

            if full_key[-1].lower() in ["dbm", "ppm"]:
                new_key = "_".join(full_key[:-1])
                config[new_key] = config.pop("_".join(full_key))
                config["measurement_unit"] = full_key[-1]
            elif full_key[-1].lower() == "db":
                new_key = "_".join(full_key[:-1])
                config[new_key] = config.pop("_".join(full_key))
            elif full_key[-2] + "_" + full_key[-1] == "dbm_mhz":
                new_key = "_".join(full_key[:-2])
                config[new_key] = config.pop("_".join(full_key))
                config["measurement_unit"] = "dBm/MHz"
            else:
                continue


def fix_calibration_values(measurement_data: dict):
    """
    Update the JSON data with the correct calibration value types.
    Converts the calibration value to the correct type for FrequencySettings and other settings.
    In case of FrequencySettings, the calibration value is converted from PPM to HMM value.
    Converts the HMM and ITAC calibration values to lists.
    A new key "calibration_value_hmm" is added to the JSON data.
    If the HMM or ITAC calibration value is None, it is set to None.

    :param measurement_data:
    :return:
    """
    for config in measurement_data["antenna_configs"]:
        if config["calibration_type"] == "FrequencySettings":
            # HMM and ITAC values are list objects for FrequencySettings
            hmm_value = config.get("calibration_value_hmm")

            if hmm_value is None or isinstance(hmm_value, int):
                # create a new key with None value if not present and set int to None (must be a list)
                config["calibration_value_hmm"] = None

            itac_calib = config.get("calibration_value_itac")
            if itac_calib is None or isinstance(itac_calib, int):
                # create a new key with None value if not present and set int to None (must be a list)
                config["calibration_value_itac"] = None
        else:
            itac_value = config.get("calibration_value_itac")

            if itac_value is None:
                # create a new key with None value if not present and set int to None (must be a list)
                config["calibration_value_hmm"] = None

            itac_calib = config.get("calibration_value_itac")
            if itac_calib is None:
                # create a new key with None value if not present and set int to None (must be a list)
                config["calibration_value_itac"] = None


def add_itac_values(measurement_data: dict):
    """
    Adds the ITAC values to the JSON data by fetching them from the ITAC interface.

    :param measurement_data: The JSON data to update.
    :return:
    """
    fbd6_itac_interface = FBD6ITAC()
    serial_number = measurement_data["serial_number"]

    eol_name, eol_idx, eol_date = fbd6_itac_interface.get_measurement_information(serial_number)
    if "eol" not in measurement_data.keys():
        configs = measurement_data["antenna_configs"]
        del measurement_data["antenna_configs"]
        measurement_data["eol"] = eol_idx
        measurement_data["antenna_configs"] = configs
    if "eol_date" not in measurement_data.keys():
        configs = measurement_data["antenna_configs"]
        del measurement_data["antenna_configs"]
        measurement_data["eol_date"] = eol_date
        measurement_data["antenna_configs"] = configs

    for config in measurement_data["antenna_configs"]:
        # trying to get value from ITAC
        antenna_config = config["antenna_config"]
        antenna_idx = re.search(r'\d+', antenna_config)
        if antenna_idx is not None:
            antenna_idx = int(antenna_idx.group(0))

        if config["calibration_type"] == "FrequencySettings":
            calib_value, ppm_value = fbd6_itac_interface.get_center_frequency(serial_number)
            config["calibration_value_itac"] = calib_value
            config["itac_measurement"] = ppm_value

        elif config["calibration_type"] == "CwPowerSettings":
            itac_value_ch8, itac_value_ch9, dbm_value = fbd6_itac_interface.get_cw(serial_number, antenna_idx)
            if config["channel"] == "UWB_CH8":
                itac_value = itac_value_ch8
                dbm_value = None
            elif config["channel"] == "UWB_CH9":
                itac_value = itac_value_ch9
            else:
                raise ValueError(f"Unknown channel: {config['channel']}")

            config["calibration_value_itac"] = itac_value
            config["itac_measurement"] = dbm_value
        elif config["calibration_type"] == "StsFrameSettings":
            itac_value_ch8, itac_value_ch9, dbm_value = fbd6_itac_interface.get_cw(serial_number, antenna_idx)

            if config["channel"] == "UWB_CH8":
                itac_value = itac_value_ch8
            elif config["channel"] == "UWB_CH9":
                itac_value = itac_value_ch9
            else:
                raise ValueError(f"Unknown channel: {config['channel']}")

            config["calibration_value_itac"] = itac_value
            config["itac_measurement"] = None
        else:
            config["calibration_value_itac"] = None
            config["itac_measurement"] = None


def rearrange_dict(measurement_data: dict) -> dict:
    """
    Rearrange the dictionary to match the desired output format.
    Keys are moved to the beginning of the dictionary if they exist in the original dictionary.

    :param measurement_data:
    :return:
    """
    return {
        "json_version": measurement_data.get("json_version", None),
        "serial_number": measurement_data.get("serial_number", None),
        "variant_type": measurement_data.get("variant_type", None),
        "is_locked": measurement_data.get("is_locked", None),
        "eol": measurement_data.get("eol", None),
        "eol_date": measurement_data.get("eol_date", None),
        "measurement_date": measurement_data.get("measurement_date", None),
        "antenna_configs": measurement_data.get("antenna_configs", [])
    }


if __name__ == "__main__":
    fix_json()



