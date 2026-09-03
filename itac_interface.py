"""iTAC Class"""

import json

import requests
import datetime

API_URL = "http://mes1264ap1.hro.hella.com:9090/mes/imsapi/rest/actions/"
HEADERS = {"Content-Type": "application/json"}
user = None
password = None


class ITACInterface:
    def __init__(self, credentials) -> None:
        self._api_url = API_URL
        self._headers = HEADERS
        self._session_context = None

        self._credentials = credentials
        self._login()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._logout()

    def _login(self) -> None:
        """Authenticate as a machine with user data."""
        url = self._api_url + "regLogin"
        payload = {
            "sessionValidationStruct": {
                "stationNumber":    self._credentials["station_id"],
                "stationPassword":  "",
                "user":             self._credentials["user"],
                "password":         self._credentials["pwd"],
                "client":           "01",
                "registrationType": "S",
                "systemIdentifier": self._credentials["station_id"]
            }
        }

        res = requests.post(url=url, data=json.dumps(payload), headers=self._headers, timeout=5)
        res.raise_for_status()
        self._session_context = res.json()["result"]["sessionContext"]
        print(self._session_context)


    def _logout(self) -> None:
        """Desactivate the current session."""
        url = self._api_url + "regLogout"
        payload = {
            "sessionContext":       self._session_context
        }

        res = requests.post(url=url, data=json.dumps(payload), headers=self._headers, timeout=5)
        res.raise_for_status()
        print("Successfully logged out from ITAC")

    @staticmethod
    def _format_measurement_data(measurement_data: list[str]) -> list[tuple]:
        """Format the output to a dictionary."""
        step_name = measurement_data[0::2]
        value = measurement_data[1::2]

        formatted_data = []
        for data in zip(step_name, value):
            test_step = data[0]
            test_value = data[1]

            try:
                test_value = float(test_value)
            except ValueError:
                test_value = str(test_value)

            formatted_data.append((test_step, test_value,))

        formatted_data = sorted(formatted_data, key=lambda x: x[0])

        return formatted_data

    @staticmethod
    def _format_metadata(metadata: list[str]) -> list[tuple]:
        """Format the output to a dictionary."""
        step_name = metadata[0::2]
        date_created = metadata[1::2]

        for data in zip(step_name, date_created):
            if "EOL" not in data[0]:
                continue

            eol_name = data[0]
            eol_idx = eol_name.split(" ")[1]

            try:
                eol_idx = int(eol_idx)
            except ValueError:
                eol_idx = None

            datetime_ms = data[1]
            try:
                datetime_ms = int(datetime_ms)
                datetime_date = datetime.datetime.fromtimestamp(datetime_ms / 1000.0)
                datetime_str = datetime_date.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError:
                datetime_str = None

            return eol_name, eol_idx, datetime_str

        return None, None, None

    def get_measurement_data(self, part_number: str, measure_name_filter: str) -> dict:
        """Get attribute values from the passed serial number."""
        url = self._api_url + "trGetResultDataForSerialNumber"
        payload = {
            "sessionContext":           self._session_context,
            "stationNumber":            self._credentials["station_id"],
            "processLayer":             2,
            "serialNumber":             part_number,
            "serialNumberPos":          -1,
            "type":                     "-1",
            "name":                     measure_name_filter,
            "allProductEntries":        2,
            "onlyLastEntry":            2,
            "resultDataFilters":        [],
            "resultDataKeys":           ["MEASURE_NAME", "MEASURE_VALUE"]
        }

        res = requests.post(url=url, data=json.dumps(payload), headers=self._headers, timeout=5)
        res.raise_for_status()
        data = res.json()["result"]["resultDataValues"]
        formatted_data = self._format_measurement_data(data)

        return formatted_data

    def get_metadata(self, part_number: str) -> dict:
        """Get attribute values from the passed serial number."""
        url = self._api_url + "trGetSerialNumberHistoryData"
        payload = {
            "sessionContext":               self._session_context,
            "stationNumber":                self._credentials["station_id"],
            "serialNumber":                 part_number,
            "serialNumberPos":              -1,
            "processLayer":                 2,
            "desolvingSerialNumber":        0,
            "desolvingLevel":               0,
            "bookingResultKeys":            ["STATION_DESC", "BOOK_DATE"],
            "failureDataResultKeys":        [],
            "failureSlipDataResultKeys":    [],
            "measureDataResultKeys":        []
        }

        res = requests.post(url=url, data=json.dumps(payload), headers=self._headers, timeout=5)
        res.raise_for_status()
        data = res.json()["result"]["bookingResultValues"]

        return self._format_metadata(data)


class FBD6ITAC:
    def __init__(self) -> None:
        global user, password
        if user is None or password is None:
            user = input("Enter ITAC user: ")
            password = input("Enter ITAC password: ")

        self._itac = ITACInterface(credentials={
            "station_id": "25204010",
            "user":       user,
            "pwd":        password
        })

    def get_measurement_information(self, part_number: str):
        """Get EOL data from ITAC."""
        return self._itac.get_metadata(part_number=part_number)

    def get_center_frequency(self, part_number: str) -> [int, float]:
        """Get center frequency from the passed serial number."""
        ppm_result = self._itac.get_measurement_data(part_number=part_number,
                                                     measure_name_filter="*Transform Offset in ppm*")
        if not ppm_result:
            return None, None

        ppm_value = ppm_result[-1][1]

        hmm_filter = "*" + ":".join(ppm_result[0][0].split(":")[0:3]) + ":*Calculate Expression String*"
        hmm_calib_result = self._itac.get_measurement_data(part_number=part_number,
                                                           measure_name_filter=hmm_filter)
        hmm_calib_result = hmm_calib_result[1][1]
        hmm_calib_result_split = hmm_calib_result.split(" ")

        hmm_high_byte = int(hmm_calib_result_split[0], 16)
        hmm_low_byte = int(hmm_calib_result_split[1], 16)
        hmm_value = [hmm_high_byte, hmm_low_byte]

        return hmm_value, ppm_value

    def get_cw(self, part_number: str, antenna_idx: int) -> [int, float]:
        """Get center frequency from the passed serial number."""
        power_result = self._itac.get_measurement_data(part_number=part_number,
                                                       measure_name_filter="*Calculate UWB TX Power Antenna " + str(antenna_idx) + "*")
        if not power_result:
            return None, None, None

        if len(power_result) < 2:
            power_dbm = power_result[0][1]
        else:
            power_dbm = power_result[1][1]

        hmm_calib_result = self._itac.get_measurement_data(part_number=part_number,
                                                           measure_name_filter="*26*CAN HPM: Get Antenna " + str(antenna_idx) + "*")

        hmm_value_ch9 = hmm_calib_result[0][1].split(" ")
        hmm_value_ch9 = int(hmm_value_ch9[1], 16)

        hmm_value_ch8 = hmm_calib_result[1][1].split(" ")
        hmm_value_ch8 = int(hmm_value_ch8[1], 16)

        return hmm_value_ch8, hmm_value_ch9, power_dbm




if __name__ == '__main__':
    fbd6_itac_interface = FBD6ITAC()
    print(fbd6_itac_interface.get_measurement_information("2263EP0000076243"))

    print(fbd6_itac_interface.get_center_frequency("2263EP0000076243"))
    print(fbd6_itac_interface.get_cw("2263EP0000076243", antenna_idx=2))

    # fbd6_itac_interface._itac._logout()

