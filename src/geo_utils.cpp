#include "geo_utils.h"
#include <math.h>

float ridDistanceMeters(float lat1Deg, float lon1Deg,
                        float lat2Deg, float lon2Deg) {
    // Sprint 4.5 (v3 Tier 1): promoted from a static helper in
    // wifi_scanner.cpp so ble_scanner can use the same arithmetic for
    // its own proximity escalation. See geo_utils.h for accuracy
    // bounds.
    constexpr float DEG_TO_RAD_F = 0.017453293f;       // pi/180
    constexpr float METERS_PER_DEG_LAT = 111320.0f;
    const float dLat = (lat2Deg - lat1Deg) * METERS_PER_DEG_LAT;
    const float dLon = (lon2Deg - lon1Deg) *
                       METERS_PER_DEG_LAT * cosf(lat1Deg * DEG_TO_RAD_F);
    return sqrtf(dLat * dLat + dLon * dLon);
}
