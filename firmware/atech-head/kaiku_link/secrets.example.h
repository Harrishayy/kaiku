// Copy to secrets.h (gitignored) and fill in. Never commit real values: this is a public repo.
#pragma once

#define WIFI_SSID "your-2.4GHz-ssid"       // Atech joins 2.4 GHz only; phone hotspot if the venue isolates clients
#define WIFI_PASS "..."
#define MQTT_HOST "kaiku-hub.local"         // hub laptop today (D32); the UNO Q if the broker moves there
#define MQTT_HOST_IP "192.168.1.10"         // fallback when mDNS is blocked (venue networks often block it)
#define MQTT_USER ""                        // empty = anonymous (D14); set both when the broker has a password file
#define MQTT_PASS ""
#define KAIKU_HOME_ID "demo-aino"
