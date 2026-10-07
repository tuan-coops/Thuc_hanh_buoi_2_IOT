# Bài thực hành số 2 — IoT data pipeline

Pipeline hoàn chỉnh: **ESP32 → MQTT/Mosquitto → Python collector → InfluxDB → preprocessing → Streamlit dashboard**.

## 1. Cấu trúc

```text
firmware/      ESP32 PlatformIO + Wokwi wiring
gateway/       MQTT subscriber, validation, InfluxDB writer
preprocess/    missing/outlier/resampling/features
dashboard/     Streamlit real-time dashboard
infra/         Mosquitto configuration
docs/          architecture and report template
```

## 2. Chuẩn bị

- Docker Desktop đang chạy.
- Python 3.10+.
- VS Code + PlatformIO (để build/nạp ESP32).
- ESP32, DHT22, HC-SR04, LED và điện trở 220 Ω; hoặc Wokwi.

Sao chép cấu hình:

```powershell
Copy-Item .env.example .env
```

Mở `.env` và đặt `INFLUX_TOKEN=change-this-token` để khớp `docker-compose.yml`. Trước khi nộp, đổi toàn bộ mật khẩu/token mặc định và không commit `.env`.

## 3. Khởi động MQTT và InfluxDB

Tại thư mục project:

```powershell
docker compose up -d
docker compose ps
```

Mở InfluxDB: <http://localhost:8086>

- Username: `admin`
- Password mặc định lab: `change-this-password`
- Organization: `iot-lab`
- Bucket: `iot`
- Token: `change-this-token`

## 4. Chạy collector

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r gateway\requirements.txt
python gateway\collector.py
```

Gửi bản tin thử mà chưa cần ESP32:

```powershell
docker exec iot-mosquitto mosquitto_pub -h localhost -t iot/esp32-lab-01/telemetry -m '{"device_id":"esp32-lab-01","ts_ms":5000,"sent_at_epoch_ms":0,"temperature_c":25.5,"humidity_pct":60,"distance_cm":100,"rssi_dbm":-55,"sequence":1}'
```

Collector phải in `stored device=esp32-lab-01 sequence=1`.

## 5. Firmware ESP32

Mở `firmware/src/main.cpp`, thay:

- `YOUR_WIFI_SSID`
- `YOUR_WIFI_PASSWORD`
- `MQTT_HOST`: IPv4 LAN của máy chạy Docker, **không dùng `localhost`** trên ESP32.

Kết nối mạch:

| Thiết bị | Chân thiết bị | ESP32 |
|---|---|---|
| DHT22 | DATA | GPIO15 |
| HC-SR04 | TRIG | GPIO5 |
| HC-SR04 | ECHO | GPIO18 |
| LED | Anode qua 220 Ω | GPIO2 |

Build và upload bằng PlatformIO:

```powershell
pio run -d firmware
pio run -d firmware -t upload
pio device monitor -d firmware
```

Nếu dùng HC-SR04 thật, chân ECHO có thể phát mức 5 V; dùng cầu chia áp trước GPIO18 để bảo vệ ESP32.

## 6. Tiền xử lý

Cài dependency rồi chạy:

```powershell
pip install -r preprocess\requirements.txt
python preprocess\preprocess.py --start=-1h --window=10s
python gateway\metrics.py --start=-1h
```

Kết quả được ghi vào measurement `sensor_processed`. Lệnh `metrics.py` in throughput, sequence bị thiếu và latency min/p50/p95/max khi ESP32 đã đồng bộ NTP.

## 7. Dashboard

```powershell
pip install -r dashboard\requirements.txt
streamlit run dashboard\app.py
```

Mở URL Streamlit được in trong terminal (thường là <http://localhost:8501>).

## 8. Kiểm thử

```powershell
python -m unittest discover -s gateway -p "test_*.py"
python -m unittest discover -s preprocess -p "test_*.py"
docker compose config
```

Thử thêm:

1. Gửi JSON sai kiểu/range → collector phải log `invalid message`.
2. Gửi lặp cùng sequence → collector phải log `duplicate ignored`.
3. Tắt/mở Wi-Fi hoặc broker → ESP32/client phải reconnect.
4. Chạy preprocess → dashboard xuất hiện tab và đường processed.

## 9. Tài liệu nộp

- Sơ đồ, schema: `docs/architecture.md`
- Mẫu báo cáo: `docs/report.md`
- Chụp ảnh thật sau khi chạy: Serial Monitor, InfluxDB Data Explorer, dashboard, Docker containers.
- Không điền số liệu giả vào báo cáo. Dùng số đo từ lần demo cuối.

## 10. Bảo mật và giới hạn

Cấu hình Mosquitto đang cho phép anonymous để dễ thực hành trong mạng nội bộ. Host port dùng `1884` vì container ThingsBoard `mytb` đang dùng `1883`; bên trong container Mosquitto vẫn nghe `1883`. Không mở các cổng MQTT ra Internet. Bản production phải bật username/password hoặc TLS, giới hạn ACL và đổi token InfluxDB.
# Thuc_hanh_buoi_2_IOT
