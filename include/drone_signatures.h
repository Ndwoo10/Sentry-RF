#ifndef DRONE_SIGNATURES_H
#define DRONE_SIGNATURES_H

#include <stdint.h>

struct DroneProtocol {
    const char* name;
    float bandStart;      // MHz
    float bandEnd;        // MHz
    float channelSpacing; // MHz
    uint16_t numChannels;
    bool is24GHz;         // true for 2.4 GHz protocols
};

struct FreqMatch {
    const DroneProtocol* protocol;  // nullptr if no match
    uint16_t channel;
    float deviationKHz;
};

extern const int DRONE_PROTOCOL_COUNT;
extern const DroneProtocol DRONE_PROTOCOLS[];

// WiFi channel reference — for filtering known WiFi AP energy from detections
extern const float WIFI_CHANNEL_CENTERS[];
extern const int WIFI_CHANNEL_COUNT;

// Match a frequency against the sub-GHz protocol database
FreqMatch matchFrequency(float freqMHz);

// Match a frequency against the 2.4 GHz protocol database
FreqMatch matchFrequency24(float freqMHz);

// Returns true if frequency is within ±11 MHz of a standard WiFi channel center
bool isWiFiChannel(float freqMHz);

#endif // DRONE_SIGNATURES_H
