from __future__ import annotations

import argparse
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize IoT pipeline metrics")
    parser.add_argument("--start", default="-1h")
    args = parser.parse_args()

    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    token = os.getenv("INFLUX_TOKEN", "change-me")
    org = os.getenv("INFLUX_ORG", "iot-lab")
    bucket = os.getenv("INFLUX_BUCKET", "iot")
    flux = f'''from(bucket: "{bucket}")
  |> range(start: {args.start})
  |> filter(fn: (r) => r._measurement == "sensor_raw")
  |> filter(fn: (r) => contains(value: r._field, set: ["sequence", "latency_ms"]))
  |> pivot(rowKey: ["_time", "device_id"], columnKey: ["_field"], valueColumn: "_value")'''
    with InfluxDBClient(url=url, token=token, org=org) as client:
        result = client.query_api().query_data_frame(flux)
    frames = result if isinstance(result, list) else [result]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        print("No raw data found.")
        return
    frame = pd.concat(frames, ignore_index=True).sort_values("_time")
    duration = max((frame["_time"].max() - frame["_time"].min()).total_seconds(), 1)
    print(f"points={len(frame)} duration_s={duration:.1f} throughput_points_s={len(frame) / duration:.3f}")
    if "latency_ms" in frame:
        latency = pd.to_numeric(frame["latency_ms"], errors="coerce").dropna()
        if not latency.empty:
            print(
                f"latency_ms min={latency.min():.0f} p50={latency.quantile(0.5):.0f} "
                f"p95={latency.quantile(0.95):.0f} max={latency.max():.0f}"
            )
    for device, group in frame.groupby("device_id"):
        seq = pd.to_numeric(group.get("sequence"), errors="coerce").dropna().sort_values()
        missing = int((seq.diff() - 1).clip(lower=0).sum()) if not seq.empty else 0
        print(f"device={device} points={len(group)} missing_sequence={missing}")


if __name__ == "__main__":
    main()
