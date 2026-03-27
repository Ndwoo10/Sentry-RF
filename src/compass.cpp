#include "compass.h"
#include "board_config.h"
#include <Arduino.h>
#include <Wire.h>
#include <math.h>

static const uint8_t QMC_ADDR = 0x0D;
static bool compassDetected = false;

// Calibration state
static bool calibrating = false;
static float calMinX, calMaxX, calMinY, calMaxY, calMinZ, calMaxZ;
static unsigned long calStartMs = 0;
static const unsigned long CAL_DURATION_MS = 10000;

// Peak bearing expiry
static const unsigned long PEAK_EXPIRY_MS = 30000;

// 16-point compass rose
static const char* DIRECTION_NAMES[] = {
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"
};

// ── I2C helpers on Wire1 ────────────────────────────────────────────────────

static void writeReg(uint8_t reg, uint8_t val) {
    Wire1.beginTransmission(QMC_ADDR);
    Wire1.write(reg);
    Wire1.write(val);
    Wire1.endTransmission();
}

static uint8_t readReg(uint8_t reg) {
    Wire1.beginTransmission(QMC_ADDR);
    Wire1.write(reg);
    Wire1.endTransmission(false);
    Wire1.requestFrom(QMC_ADDR, (uint8_t)1);
    return Wire1.available() ? Wire1.read() : 0;
}

// ── Public API ──────────────────────────────────────────────────────────────

bool compassInit() {
#if !defined(BOARD_T3S3) && !defined(BOARD_T3S3_LR1121)
    compassDetected = false;
    return false;
#else
    if (!HAS_COMPASS) {
        compassDetected = false;
        return false;
    }

    // Configure QMC5883L — Wire1 already initialized by initCompassBus()
    writeReg(0x0B, 0x01);  // Period register (recommended)
    writeReg(0x09, 0x1D);  // Continuous, 200Hz, 8G range, 512x oversampling
    writeReg(0x0A, 0x40);  // Pointer rollover enable

    // Verify chip presence — QMC5883L chip ID register returns 0xFF
    uint8_t chipId = readReg(0x0D);
    if (chipId != 0xFF) {
        Serial.printf("[COMPASS] Not detected (ID=0x%02X, expected 0xFF)\n", chipId);
        compassDetected = false;
        return false;
    }

    compassDetected = true;
    Serial.println("[COMPASS] QMC5883L detected on Wire1");
    return true;
#endif
}

void compassRead(CompassData& data) {
    if (!compassDetected) {
        data.valid = false;
        return;
    }

    // Check data ready
    uint8_t status = readReg(0x06);
    if (!(status & 0x01)) {
        // DRDY not set — keep previous values, still valid
        return;
    }

    // Read 6 bytes: X LSB, X MSB, Y LSB, Y MSB, Z LSB, Z MSB
    Wire1.beginTransmission(QMC_ADDR);
    Wire1.write(0x00);
    Wire1.endTransmission(false);
    Wire1.requestFrom(QMC_ADDR, (uint8_t)6);

    if (Wire1.available() < 6) return;

    data.rawX = Wire1.read() | (Wire1.read() << 8);
    data.rawY = Wire1.read() | (Wire1.read() << 8);
    data.rawZ = Wire1.read() | (Wire1.read() << 8);

    // Apply hard iron calibration
    float cx = ((float)data.rawX - data.offsetX) * data.scaleX;
    float cy = ((float)data.rawY - data.offsetY) * data.scaleY;

    // Compute heading from calibrated X/Y
    float heading = atan2f(cy, cx) * 180.0f / M_PI;
    if (heading < 0) heading += 360.0f;
    data.heading = heading;

    // 16-point direction string
    int sector = (int)((heading + 11.25f) / 22.5f) % 16;
    strncpy(data.directionStr, DIRECTION_NAMES[sector], sizeof(data.directionStr) - 1);
    data.directionStr[3] = '\0';

    data.valid = true;
}

void compassUpdatePeakBearing(CompassData& data, float currentRSSI) {
    if (!data.valid) return;

    // Expire old peaks
    if (millis() - data.peakTimestamp > PEAK_EXPIRY_MS) {
        data.peakRSSI = -200.0;
    }

    if (currentRSSI > data.peakRSSI) {
        data.peakRSSI = currentRSSI;
        data.peakBearing = data.heading;
        data.peakTimestamp = millis();
    }
}

void compassStartCalibration() {
    if (calibrating) {
        // Second call stops calibration
        calibrating = false;
        Serial.println("[COMPASS] Calibration stopped");
        return;
    }

    calibrating = true;
    calStartMs = millis();
    calMinX = calMinY = calMinZ = 32767.0;
    calMaxX = calMaxY = calMaxZ = -32768.0;
    Serial.println("[COMPASS] Calibration started — rotate 360 degrees");
}

bool compassIsCalibrating() {
    return calibrating;
}

void compassCalibrationTick(CompassData& data) {
    if (!calibrating || !compassDetected) return;

    // Auto-stop after 10 seconds
    if (millis() - calStartMs > CAL_DURATION_MS) {
        calibrating = false;

        // Compute hard iron offsets and scale factors
        data.offsetX = (calMaxX + calMinX) / 2.0f;
        data.offsetY = (calMaxY + calMinY) / 2.0f;
        data.offsetZ = (calMaxZ + calMinZ) / 2.0f;

        float rangeX = (calMaxX - calMinX) / 2.0f;
        float rangeY = (calMaxY - calMinY) / 2.0f;
        float rangeZ = (calMaxZ - calMinZ) / 2.0f;

        // Avoid division by zero
        data.scaleX = (rangeX > 0) ? (1.0f / rangeX) : 1.0f;
        data.scaleY = (rangeY > 0) ? (1.0f / rangeY) : 1.0f;
        data.scaleZ = (rangeZ > 0) ? (1.0f / rangeZ) : 1.0f;

        Serial.println("[COMPASS] Calibration complete:");
        Serial.printf("  Offsets: X=%.1f Y=%.1f Z=%.1f\n",
                      data.offsetX, data.offsetY, data.offsetZ);
        Serial.printf("  Scales:  X=%.4f Y=%.4f Z=%.4f\n",
                      data.scaleX, data.scaleY, data.scaleZ);
        return;
    }

    // Read raw and track min/max
    uint8_t status = readReg(0x06);
    if (!(status & 0x01)) return;

    Wire1.beginTransmission(QMC_ADDR);
    Wire1.write(0x00);
    Wire1.endTransmission(false);
    Wire1.requestFrom(QMC_ADDR, (uint8_t)6);
    if (Wire1.available() < 6) return;

    float x = (int16_t)(Wire1.read() | (Wire1.read() << 8));
    float y = (int16_t)(Wire1.read() | (Wire1.read() << 8));
    float z = (int16_t)(Wire1.read() | (Wire1.read() << 8));

    if (x < calMinX) calMinX = x;
    if (x > calMaxX) calMaxX = x;
    if (y < calMinY) calMinY = y;
    if (y > calMaxY) calMaxY = y;
    if (z < calMinZ) calMinZ = z;
    if (z > calMaxZ) calMaxZ = z;
}
