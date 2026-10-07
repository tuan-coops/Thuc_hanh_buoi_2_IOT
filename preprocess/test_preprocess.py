import unittest

import pandas as pd

from preprocess import preprocess_frame


class PreprocessTest(unittest.TestCase):
    def test_resampling_and_features(self):
        frame = pd.DataFrame(
            {
                "time": pd.to_datetime([
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T00:00:10Z",
                    "2026-01-01T00:00:30Z",
                ]),
                "device_id": ["d1"] * 3,
                "temperature_c": [20.0, 21.0, 100.0],
                "humidity_pct": [50.0, 51.0, 52.0],
                "distance_cm": [100.0, 101.0, 102.0],
                "rssi_dbm": [-50.0, -51.0, -52.0],
            }
        )
        result = preprocess_frame(frame, "10s")
        self.assertEqual(len(result), 4)
        self.assertIn("temperature_c_rolling_mean", result.columns)
        self.assertIn("temperature_c_zscore", result.columns)
        self.assertGreaterEqual(result["is_imputed"].sum(), 1)


if __name__ == "__main__":
    unittest.main()
