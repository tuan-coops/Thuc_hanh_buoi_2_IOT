from __future__ import annotations

import json
import logging
import os
import signal
import time
from collections import defaultdict, deque
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from schema import ValidationError, validate_telemetry

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collector")

MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_PREFIX = os.getenv("MQTT_TOPIC_PREFIX", "iot")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "iot-gateway")
INFLUX_URL = os.getenv("INFLUX_URL", "http://localhost:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "change-me")
INFLUX_ORG = os.getenv("INFLUX_ORG", "iot-lab")
INFLUX_BUCKET = os.getenv("INFLUX_RAW_BUCKET", os.getenv("INFLUX_BUCKET", "iot"))

influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
writer = influx.write_api(write_options=SYNCHRONOUS)
seen: dict[str, deque[int]] = defaultdict(lambda: deque(maxlen=2048))
counters = defaultdict(int)
running = True


def topic_device(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) != 3 or parts[0] != MQTT_PREFIX or parts[2] != "telemetry":
        raise ValidationError("unexpected MQTT topic")
    return parts[1]


def on_connect(client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
    if reason_code == 0:
        topic = f"{MQTT_PREFIX}/+/telemetry"
        client.subscribe(topic, qos=1)
        LOG.info("connected to MQTT and subscribed to %s", topic)
    else:
        LOG.error("MQTT connection failed: %s", reason_code)


def on_message(client: mqtt.Client, userdata, message: mqtt.MQTTMessage) -> None:
    received_ms = int(time.time() * 1000)
    try:
        device_from_topic = topic_device(message.topic)
        payload = json.loads(message.payload.decode("utf-8"))
        data = validate_telemetry(payload, device_from_topic)
        if data.sequence in seen[data.device_id]:
            counters["duplicate"] += 1
            LOG.warning("duplicate ignored device=%s sequence=%d", data.device_id, data.sequence)
            return

        previous = seen[data.device_id][-1] if seen[data.device_id] else None

        point = (
            Point("sensor_raw")
            .tag("device_id", data.device_id)
            .tag("source", "mqtt")
            .tag("topic", message.topic)
            .field("device_uptime_ms", data.ts_ms)
            .field("temperature_c", data.temperature_c)
            .field("humidity_pct", data.humidity_pct)
            .field("distance_cm", data.distance_cm)
            .field("rssi_dbm", data.rssi_dbm)
            .field("sequence", data.sequence)
            .field("ingested_at_ms", received_ms)
        )
        if data.sent_at_epoch_ms > 0:
            point = point.field("sent_at_epoch_ms", data.sent_at_epoch_ms).field(
                "latency_ms", max(0, received_ms - data.sent_at_epoch_ms)
            )
        point = point.time(received_ms, WritePrecision.MS)
        writer.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
        if previous is not None and data.sequence > previous + 1:
            counters["missing_sequence"] += data.sequence - previous - 1
            LOG.warning("sequence gap device=%s previous=%d current=%d", data.device_id, previous, data.sequence)
        seen[data.device_id].append(data.sequence)
        counters["stored"] += 1
        LOG.info("stored device=%s sequence=%d", data.device_id, data.sequence)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        counters["invalid"] += 1
        LOG.warning("invalid message topic=%s error=%s", message.topic, exc)
    except Exception:
        counters["write_error"] += 1
        LOG.exception("failed to process message")


def stop(*_) -> None:
    global running
    running = False


def main() -> None:
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=MQTT_CLIENT_ID)
    client.on_connect = on_connect
    client.on_message = on_message
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()
    LOG.info("collector started")
    try:
        while running:
            time.sleep(1)
    finally:
        client.loop_stop()
        client.disconnect()
        writer.close()
        influx.close()
        LOG.info("collector stopped counters=%s", dict(counters))


if __name__ == "__main__":
    main()
