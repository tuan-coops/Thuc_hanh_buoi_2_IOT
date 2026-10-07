import unittest

from schema import ValidationError, validate_telemetry


VALID = {
    "device_id": "esp32-lab-01",
    "ts_ms": 5000,
    "sent_at_epoch_ms": 1791340800000,
    "temperature_c": 25.5,
    "humidity_pct": 60.0,
    "distance_cm": 100.0,
    "rssi_dbm": -55,
    "sequence": 1,
}


class TelemetryValidationTest(unittest.TestCase):
    def test_valid_payload(self):
        data = validate_telemetry(VALID, "esp32-lab-01")
        self.assertEqual(data.sequence, 1)

    def test_topic_device_must_match(self):
        with self.assertRaises(ValidationError):
            validate_telemetry(VALID, "another-device")

    def test_out_of_range_humidity_is_rejected(self):
        payload = {**VALID, "humidity_pct": 101}
        with self.assertRaises(ValidationError):
            validate_telemetry(payload, "esp32-lab-01")

    def test_boolean_is_not_numeric(self):
        payload = {**VALID, "sequence": True}
        with self.assertRaises(ValidationError):
            validate_telemetry(payload, "esp32-lab-01")


if __name__ == "__main__":
    unittest.main()
