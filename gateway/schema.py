from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ValidationError(ValueError):
    pass


@dataclass(frozen=True)
class Telemetry:
    device_id: str
    ts_ms: int
    sent_at_epoch_ms: int
    temperature_c: float
    humidity_pct: float
    distance_cm: float
    rssi_dbm: int
    sequence: int


def _number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{key} must be numeric")
    return float(value)


def validate_telemetry(payload: Any, topic_device_id: str) -> Telemetry:
    if not isinstance(payload, dict):
        raise ValidationError("payload must be a JSON object")

    device_id = payload.get("device_id")
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValidationError("device_id must be a non-empty string")
    if device_id != topic_device_id:
        raise ValidationError("device_id does not match MQTT topic")

    ts_ms = int(_number(payload, "ts_ms"))
    raw_epoch = payload.get("sent_at_epoch_ms", 0)
    if isinstance(raw_epoch, bool) or not isinstance(raw_epoch, (int, float)):
        raise ValidationError("sent_at_epoch_ms must be numeric")
    sent_at_epoch_ms = int(raw_epoch)
    temperature = _number(payload, "temperature_c")
    humidity = _number(payload, "humidity_pct")
    distance = _number(payload, "distance_cm")
    rssi = int(_number(payload, "rssi_dbm"))
    sequence = int(_number(payload, "sequence"))

    if ts_ms < 0:
        raise ValidationError("ts_ms must be non-negative")
    if sent_at_epoch_ms < 0:
        raise ValidationError("sent_at_epoch_ms must be non-negative")
    if not -40 <= temperature <= 85:
        raise ValidationError("temperature_c outside DHT22 range")
    if not 0 <= humidity <= 100:
        raise ValidationError("humidity_pct outside valid range")
    if not 2 <= distance <= 400:
        raise ValidationError("distance_cm outside HC-SR04 range")
    if not -120 <= rssi <= 0:
        raise ValidationError("rssi_dbm outside expected Wi-Fi range")
    if sequence < 1:
        raise ValidationError("sequence must be positive")

    return Telemetry(device_id, ts_ms, sent_at_epoch_ms, temperature, humidity, distance, rssi, sequence)
