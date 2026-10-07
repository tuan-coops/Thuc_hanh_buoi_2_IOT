from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
FIELDS = ["temperature_c", "humidity_pct", "distance_cm", "rssi_dbm"]


def preprocess_frame(frame: pd.DataFrame, window: str = "10s") -> pd.DataFrame:
    if frame.empty:
        return frame
    result_parts = []
    for device_id, group in frame.groupby("device_id"):
        group = group.copy()
        group["time"] = pd.to_datetime(group["time"], utc=True)
        group = group.sort_values("time").drop_duplicates(subset=["time"], keep="last").set_index("time")
        numeric = group[FIELDS].apply(pd.to_numeric, errors="coerce")
        sampled = numeric.resample(window).mean()
        sampled["is_imputed"] = sampled.isna().any(axis=1).astype(int)
        sampled["is_outlier"] = 0

        for field in FIELDS:
            series = sampled[field]
            q1, q3 = series.quantile([0.25, 0.75])
            iqr = q3 - q1
            if pd.notna(iqr) and iqr > 0:
                mask = (series < q1 - 1.5 * iqr) | (series > q3 + 1.5 * iqr)
                sampled.loc[mask, "is_outlier"] = 1
                sampled.loc[mask, field] = np.nan
            sampled[field] = sampled[field].interpolate(method="time", limit=3, limit_direction="both")
            sampled[f"{field}_rolling_mean"] = sampled[field].rolling(3, min_periods=1).mean()
            sampled[f"{field}_delta"] = sampled[field].diff().fillna(0.0)
            std = sampled[field].std(ddof=0)
            sampled[f"{field}_zscore"] = 0.0 if not std or pd.isna(std) else (sampled[field] - sampled[field].mean()) / std

        sampled["device_id"] = device_id
        result_parts.append(sampled.reset_index())
    return pd.concat(result_parts, ignore_index=True)


def flux_time(value: str) -> str:
    return value if value.startswith("-") else f'time(v: "{value}")'


def query_raw(client: InfluxDBClient, bucket: str, start: str, stop: str | None) -> pd.DataFrame:
    stop_clause = f", stop: {flux_time(stop)}" if stop else ""
    flux = f'''from(bucket: "{bucket}")
  |> range(start: {flux_time(start)}{stop_clause})
  |> filter(fn: (r) => r._measurement == "sensor_raw")
  |> filter(fn: (r) => contains(value: r._field, set: {json.dumps(FIELDS)}))
  |> pivot(rowKey: ["_time", "device_id"], columnKey: ["_field"], valueColumn: "_value")'''
    tables = client.query_api().query_data_frame(flux)
    frames = tables if isinstance(tables, list) else [tables]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    frame = pd.concat(frames, ignore_index=True)
    return frame.rename(columns={"_time": "time"})[["time", "device_id", *FIELDS]]


def write_processed(client: InfluxDBClient, bucket: str, org: str, frame: pd.DataFrame) -> None:
    write_api = client.write_api(write_options=SYNCHRONOUS)
    records = []
    for row in frame.to_dict("records"):
        point = Point("sensor_processed").tag("device_id", row["device_id"])
        for key, value in row.items():
            if key not in {"time", "device_id"} and pd.notna(value):
                point = point.field(key, int(value) if key.startswith("is_") else float(value))
        point = point.time(pd.Timestamp(row["time"]).to_pydatetime(), WritePrecision.NS)
        records.append(point)
    if records:
        write_api.write(bucket=bucket, org=org, record=records)
    write_api.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Preprocess IoT time-series data")
    parser.add_argument("--start", default="-1h", help="InfluxDB range start, e.g. -1h")
    parser.add_argument("--stop", default=None, help="Optional RFC3339 stop time")
    parser.add_argument("--window", default="10s", help="Pandas resampling window")
    args = parser.parse_args()

    url = os.getenv("INFLUX_URL", "http://localhost:8086")
    token = os.getenv("INFLUX_TOKEN", "change-me")
    org = os.getenv("INFLUX_ORG", "iot-lab")
    raw_bucket = os.getenv("INFLUX_RAW_BUCKET", os.getenv("INFLUX_BUCKET", "iot"))
    processed_bucket = os.getenv("INFLUX_PROCESSED_BUCKET", os.getenv("INFLUX_BUCKET", "iot"))

    with InfluxDBClient(url=url, token=token, org=org) as client:
        raw = query_raw(client, raw_bucket, args.start, args.stop)
        processed = preprocess_frame(raw, args.window)
        if processed.empty:
            print("No raw data found in the requested interval.")
            return
        write_processed(client, processed_bucket, org, processed)
        print(f"raw_rows={len(raw)} processed_rows={len(processed)} outliers={int(processed['is_outlier'].sum())} imputed={int(processed['is_imputed'].sum())}")


if __name__ == "__main__":
    main()
