from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient
from streamlit_autorefresh import st_autorefresh

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
st.set_page_config(page_title="IoT Lab Monitor", page_icon="📡", layout="wide")

COLORS = {"Raw": "#2a78d6", "Processed": "#eb6834"}
UNITS = {
    "temperature_c": "°C",
    "humidity_pct": "%",
    "distance_cm": "cm",
    "rssi_dbm": "dBm",
}


def config():
    return {
        "url": os.getenv("INFLUX_URL", "http://localhost:8086"),
        "token": os.getenv("INFLUX_TOKEN", "change-me"),
        "org": os.getenv("INFLUX_ORG", "iot-lab"),
        "bucket": os.getenv("INFLUX_BUCKET", "iot"),
    }


@st.cache_data(ttl=5, show_spinner=False)
def query(measurement: str, start: str) -> pd.DataFrame:
    cfg = config()
    flux = f'''from(bucket: "{cfg['bucket']}")
  |> range(start: {start})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> pivot(rowKey: ["_time", "device_id"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])'''
    with InfluxDBClient(url=cfg["url"], token=cfg["token"], org=cfg["org"]) as client:
        tables = client.query_api().query_data_frame(flux)
    frames = tables if isinstance(tables, list) else [tables]
    frames = [frame for frame in frames if not frame.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def trend_chart(raw: pd.DataFrame, processed: pd.DataFrame, field: str):
    frames = []
    if not raw.empty and field in raw:
        frames.append(raw[["_time", field]].assign(Series="Raw").rename(columns={field: "value"}))
    if not processed.empty and field in processed:
        frames.append(processed[["_time", field]].assign(Series="Processed").rename(columns={field: "value"}))
    if not frames:
        return None
    plot = pd.concat(frames, ignore_index=True)
    fig = px.line(plot, x="_time", y="value", color="Series", color_discrete_map=COLORS,
                  labels={"_time": "Time (UTC)", "value": UNITS[field]})
    fig.update_traces(line={"width": 2}, hovertemplate="%{x}<br><b>%{y:.2f}</b><extra>%{fullData.name}</extra>")
    fig.update_layout(height=310, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                      legend_title_text="Series", plot_bgcolor="#fcfcfb", paper_bgcolor="#fcfcfb")
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e1e0d9", zerolinecolor="#c3c2b7")
    return fig


st.title("IoT Real-time Monitoring")
st.caption("Raw telemetry, processed time-series and data-quality indicators")

with st.sidebar:
    st.header("Filters")
    range_label = st.selectbox("Time range", ["15 minutes", "1 hour", "6 hours", "24 hours"], index=1)
    refresh = st.toggle("Auto refresh", value=True)
    refresh_seconds = st.slider("Refresh every (seconds)", 5, 60, int(os.getenv("DASHBOARD_REFRESH_SECONDS", "5")))

if refresh:
    st_autorefresh(interval=refresh_seconds * 1000, key="iot-refresh")

ranges = {"15 minutes": "-15m", "1 hour": "-1h", "6 hours": "-6h", "24 hours": "-24h"}
try:
    raw_all = query("sensor_raw", ranges[range_label])
    processed_all = query("sensor_processed", ranges[range_label])
except Exception as exc:
    st.error(f"Cannot query InfluxDB: {exc}")
    st.stop()

if raw_all.empty:
    st.info("No telemetry is available yet. Start Docker, run the collector, then power the ESP32 or publish a test message.")
    st.stop()

devices = sorted(raw_all["device_id"].dropna().unique())
device = st.selectbox("Device", devices)
raw = raw_all[raw_all["device_id"] == device].copy()
processed = processed_all[processed_all["device_id"] == device].copy() if not processed_all.empty else pd.DataFrame()
latest = raw.sort_values("_time").iloc[-1]

kpis = st.columns(4)
for column, field, label in zip(kpis, UNITS, ["Temperature", "Humidity", "Distance", "Wi-Fi RSSI"]):
    value = latest.get(field)
    column.metric(label, "—" if pd.isna(value) else f"{value:.2f} {UNITS[field]}")

st.subheader("Sensor trends")
left, right = st.columns(2)
for container, field, title in [(left, "temperature_c", "Temperature"), (right, "humidity_pct", "Humidity")]:
    container.markdown(f"**{title}**")
    chart = trend_chart(raw, processed, field)
    if chart:
        container.plotly_chart(chart, use_container_width=True)
left2, right2 = st.columns(2)
for container, field, title in [(left2, "distance_cm", "Distance"), (right2, "rssi_dbm", "Wi-Fi signal")]:
    container.markdown(f"**{title}**")
    chart = trend_chart(raw, processed, field)
    if chart:
        container.plotly_chart(chart, use_container_width=True)

st.subheader("Quality and pipeline")
q1, q2, q3, q4, q5 = st.columns(5)
q1.metric("Raw points", len(raw))
q2.metric("Processed points", len(processed))
q3.metric("Outlier windows", int(processed.get("is_outlier", pd.Series(dtype=float)).fillna(0).sum()))
q4.metric("Imputed windows", int(processed.get("is_imputed", pd.Series(dtype=float)).fillna(0).sum()))
latency = pd.to_numeric(raw.get("latency_ms", pd.Series(dtype=float)), errors="coerce").dropna()
q5.metric("Latency p95", "—" if latency.empty else f"{latency.quantile(0.95):.0f} ms")

st.subheader("Data table")
tab_raw, tab_processed = st.tabs(["Raw", "Processed"])
with tab_raw:
    st.dataframe(raw.sort_values("_time", ascending=False), use_container_width=True, hide_index=True)
with tab_processed:
    if processed.empty:
        st.info("Run preprocess/preprocess.py to create processed data.")
    else:
        st.dataframe(processed.sort_values("_time", ascending=False), use_container_width=True, hide_index=True)
