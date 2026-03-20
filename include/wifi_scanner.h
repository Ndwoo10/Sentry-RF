#ifndef WIFI_SCANNER_H
#define WIFI_SCANNER_H

#include "detection_types.h"

// Known drone manufacturer MAC OUI prefixes (first 3 bytes)
struct DroneOUI {
    uint8_t oui[3];
    const char* name;
};

// Initialize WiFi in promiscuous mode for drone frame capture
void wifiScannerInit();

// Stop promiscuous mode — call before switching to dashboard AP mode
void wifiScannerStop();

// FreeRTOS task: dequeues captured packets, channel-hops, matches MACs
void wifiScanTask(void* param);

#endif // WIFI_SCANNER_H
