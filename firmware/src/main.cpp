#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <DHTesp.h>
#include <time.h>

// Set these values before flashing the ESP32.
const char *WIFI_SSID = "YOUR_WIFI_SSID";
const char *WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char *MQTT_HOST = "192.168.1.100"; // Gateway computer LAN address.
const uint16_t MQTT_PORT = 1884;
const char *DEVICE_ID = "esp32-lab-01";

constexpr uint8_t DHT_PIN = 15;
constexpr uint8_t TRIG_PIN = 5;
constexpr uint8_t ECHO_PIN = 18;
constexpr uint8_t LED_PIN = 2;
constexpr unsigned long PUBLISH_INTERVAL_MS = 5000;

WiFiClient networkClient;
PubSubClient mqtt(networkClient);
DHTesp dht;
unsigned long lastPublish = 0;
unsigned long sequence = 0;
unsigned long lastWifiAttempt = 0;
unsigned long lastMqttAttempt = 0;
bool ntpConfigured = false;

String telemetryTopic() {
  return String("iot/") + DEVICE_ID + "/telemetry";
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED || millis() - lastWifiAttempt < 10000) return;
  lastWifiAttempt = millis();
  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

unsigned long long epochMs() {
  struct timeval now;
  gettimeofday(&now, nullptr);
  if (now.tv_sec < 1700000000) return 0;
  return (unsigned long long)now.tv_sec * 1000ULL + now.tv_usec / 1000ULL;
}

void connectMqtt() {
  if (WiFi.status() != WL_CONNECTED || mqtt.connected() || millis() - lastMqttAttempt < 5000) return;
  lastMqttAttempt = millis();
  String clientId = String(DEVICE_ID) + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("[mqtt] connecting to %s:%u\n", MQTT_HOST, MQTT_PORT);
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("[mqtt] connected");
  } else {
    Serial.printf("[mqtt] failed rc=%d\n", mqtt.state());
  }
}

float readDistanceCm() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) return NAN;
  return duration * 0.0343f / 2.0f;
}

bool validReading(float temperature, float humidity, float distance) {
  return isfinite(temperature) && temperature >= -40 && temperature <= 85 &&
         isfinite(humidity) && humidity >= 0 && humidity <= 100 &&
         isfinite(distance) && distance >= 2 && distance <= 400;
}

void publishTelemetry() {
  TempAndHumidity reading = dht.getTempAndHumidity();
  float distance = readDistanceCm();
  if (!validReading(reading.temperature, reading.humidity, distance)) {
    Serial.printf("[sensor] invalid temperature=%.2f humidity=%.2f distance=%.2f\n",
                  reading.temperature, reading.humidity, distance);
    return;
  }

  ++sequence;
  char payload[320];
  snprintf(payload, sizeof(payload),
           "{\"device_id\":\"%s\",\"ts_ms\":%lu,\"sent_at_epoch_ms\":%llu,\"temperature_c\":%.2f,\"humidity_pct\":%.2f,\"distance_cm\":%.2f,\"rssi_dbm\":%d,\"sequence\":%lu}",
           DEVICE_ID, millis(), epochMs(), reading.temperature, reading.humidity,
           distance, WiFi.RSSI(), sequence);

  bool sent = mqtt.publish(telemetryTopic().c_str(), payload);
  Serial.printf("[telemetry] %s | publish=%s\n", payload, sent ? "OK" : "FAILED");
  digitalWrite(LED_PIN, HIGH);
  delay(50);
  digitalWrite(LED_PIN, LOW);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  dht.setup(DHT_PIN, DHTesp::DHT22);
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setBufferSize(384);
  connectWiFi();
}

void loop() {
  connectWiFi();
  if (WiFi.status() == WL_CONNECTED && !ntpConfigured) {
    configTime(0, 0, "pool.ntp.org", "time.google.com");
    ntpConfigured = true;
    Serial.println("[time] NTP configured");
  }
  connectMqtt();
  if (mqtt.connected()) mqtt.loop();

  unsigned long now = millis();
  if (mqtt.connected() && now - lastPublish >= PUBLISH_INTERVAL_MS) {
    lastPublish = now;
    publishTelemetry();
  }
  delay(5);
}
