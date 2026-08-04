#pragma once
// ---------------------------------------------------------------------------
// COPY this file to  firmware/include/secrets.h  and fill in real values.
// secrets.h is gitignored so credentials never reach GitHub.
// ---------------------------------------------------------------------------

// Wi-Fi: use a phone hotspot or home router (campus eduroam will fight you).
#define WIFI_SSID   "your-hotspot-name"
#define WIFI_PASS   "your-hotspot-password"

// MQTT broker = the laptop running Mosquitto.
// Find the laptop's IP on the same hotspot:  macOS: ipconfig getifaddr en0
//                                            Windows: ipconfig   Linux: ip a
#define MQTT_HOST   "192.168.1.50"
#define MQTT_PORT   1883
#define MQTT_USER   "stationuser"
#define MQTT_PASSWD "change-me"
