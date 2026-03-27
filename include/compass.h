#ifndef COMPASS_H
#define COMPASS_H

#include <stdint.h>

struct CompassData {
    int16_t rawX, rawY, rawZ;
    float heading;                   // Magnetic heading 0-359 degrees
    char directionStr[4];            // "N", "NE", "E", etc. (16-point)
    bool valid;                      // false if compass not detected

    // Calibration offsets (hard iron compensation)
    float offsetX, offsetY, offsetZ;
    float scaleX, scaleY, scaleZ;

    // Peak bearing tracking for RF direction finding
    float peakRSSI;
    float peakBearing;
    unsigned long peakTimestamp;
};

// Init QMC5883L on Wire1 — Wire1.begin() must already be called
bool compassInit();

// Read heading, apply calibration
void compassRead(CompassData& data);

// Track bearing of strongest signal — peak expires after 30s
void compassUpdatePeakBearing(CompassData& data, float currentRSSI);

// Calibration: rotate device 360° over ~10 seconds
void compassStartCalibration();
bool compassIsCalibrating();
void compassCalibrationTick(CompassData& data);

#endif // COMPASS_H
