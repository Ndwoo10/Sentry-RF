#ifndef GEO_UTILS_H
#define GEO_UTILS_H

// Sprint 4.5 (v3 Tier 1) — shared geographic helpers used by wifi_scanner
// and ble_scanner for ASTM F3411 RID proximity escalation. Lives outside
// gps_manager.h so that gps_manager keeps its narrow u-blox-driver focus.

// Equirectangular distance between two (latitude, longitude) points in
// decimal degrees. Returns meters. Accurate to sub-meter at distances
// below a few kilometres at any reasonable latitude — well below the
// typical ASTM F3411 GPS uncertainty (~5 m). Used for the
// RID_PROXIMITY_THRESHOLD_M = 500 m comparison; do NOT use for
// long-range navigation calculations.
float ridDistanceMeters(float lat1Deg, float lon1Deg,
                        float lat2Deg, float lon2Deg);

#endif // GEO_UTILS_H
