#include "env_mode.h"
#include "sentry_config.h"
#include "detection_types.h"
#include <Arduino.h>
#include <nvs.h>
#include <nvs_flash.h>

// Sprint 7 Part A: env-mode runtime variable + NVS persistence.
//
// The NVS namespace and key are short-by-design: ESP-IDF caps namespaces
// at 15 chars and keys at 15 chars. "sentry_cfg" / "env_mode" leave room
// for future settings without renaming.
static const char* NVS_NS  = "sentry_cfg";
static const char* NVS_KEY = "env_mode";

static EnvMode g_envMode = EnvMode::SUBURBAN;
static bool    g_nvsReady = false;

static EnvMode clampMode(uint8_t v) {
    if (v <= (uint8_t)EnvMode::RURAL) return (EnvMode)v;
    return EnvMode::SUBURBAN;
}

const char* envModeLabel(EnvMode m) {
    switch (m) {
        case EnvMode::URBAN:    return "URBAN";
        case EnvMode::SUBURBAN: return "SUBURBAN";
        case EnvMode::RURAL:    return "RURAL";
    }
    return "?";
}

static bool nvsOpenRW(nvs_handle_t* h) {
    esp_err_t err = nvs_open(NVS_NS, NVS_READWRITE, h);
    if (err != ESP_OK) {
        Serial.printf("[ENV-MODE] nvs_open(rw) failed: %s\n", esp_err_to_name(err));
        return false;
    }
    return true;
}

static bool persistMode(EnvMode m) {
    if (!g_nvsReady) return false;
    nvs_handle_t h;
    if (!nvsOpenRW(&h)) return false;
    bool ok = true;
    esp_err_t err = nvs_set_u8(h, NVS_KEY, (uint8_t)m);
    if (err != ESP_OK) {
        Serial.printf("[ENV-MODE] nvs_set_u8 failed: %s\n", esp_err_to_name(err));
        ok = false;
    } else {
        err = nvs_commit(h);
        if (err != ESP_OK) {
            Serial.printf("[ENV-MODE] nvs_commit failed: %s\n", esp_err_to_name(err));
            ok = false;
        }
    }
    nvs_close(h);
    return ok;
}

void envModeInit() {
    // NVS partition init is idempotent; if the partition is missing or
    // truncated (typical first boot after a fresh flash) the recovery
    // path erases and re-inits. Failure here is non-fatal — we keep the
    // SUBURBAN default in RAM and the operator can still long-press to
    // change mode for the current session.
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        Serial.printf("[ENV-MODE] nvs_flash_init recovery: %s, erasing\n",
                      esp_err_to_name(err));
        if (nvs_flash_erase() == ESP_OK) {
            err = nvs_flash_init();
        }
    }
    if (err != ESP_OK) {
        Serial.printf("[ENV-MODE] nvs_flash_init failed: %s — using RAM default SUBURBAN\n",
                      esp_err_to_name(err));
        g_nvsReady = false;
        g_envMode = EnvMode::SUBURBAN;
        return;
    }
    g_nvsReady = true;

    nvs_handle_t h;
    err = nvs_open(NVS_NS, NVS_READONLY, &h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        // First boot — namespace doesn't exist. Default SUBURBAN, write it.
        g_envMode = EnvMode::SUBURBAN;
        Serial.println("[ENV-MODE] first boot, writing SUBURBAN default");
        persistMode(g_envMode);
        return;
    }
    if (err != ESP_OK) {
        Serial.printf("[ENV-MODE] nvs_open(ro) failed: %s — using RAM default SUBURBAN\n",
                      esp_err_to_name(err));
        g_envMode = EnvMode::SUBURBAN;
        return;
    }

    uint8_t raw = (uint8_t)EnvMode::SUBURBAN;
    err = nvs_get_u8(h, NVS_KEY, &raw);
    nvs_close(h);
    if (err == ESP_ERR_NVS_NOT_FOUND) {
        g_envMode = EnvMode::SUBURBAN;
        Serial.println("[ENV-MODE] key missing, writing SUBURBAN default");
        persistMode(g_envMode);
        return;
    }
    if (err != ESP_OK) {
        Serial.printf("[ENV-MODE] nvs_get_u8 failed: %s — using SUBURBAN\n",
                      esp_err_to_name(err));
        g_envMode = EnvMode::SUBURBAN;
        return;
    }
    g_envMode = clampMode(raw);
    SERIAL_SAFE(Serial.printf("[ENV-MODE] loaded from NVS: %s (tap=%.1f skip=%ums)\n",
                              envModeLabel(g_envMode),
                              currentTapThresholdDb(),
                              (unsigned)currentSkipTtlMs()));
}

EnvMode envModeGet() { return g_envMode; }

void envModeSet(EnvMode m) {
    g_envMode = m;
    persistMode(m);
}

EnvMode envModeCycle() {
    EnvMode prev = g_envMode;
    EnvMode next;
    switch (prev) {
        case EnvMode::URBAN:    next = EnvMode::SUBURBAN; break;
        case EnvMode::SUBURBAN: next = EnvMode::RURAL;    break;
        case EnvMode::RURAL:    next = EnvMode::URBAN;    break;
        default:                next = EnvMode::SUBURBAN; break;
    }
    envModeSet(next);
    SERIAL_SAFE(Serial.printf("[ENV-MODE] changed: %s -> %s (tap=%.1f skip=%ums)\n",
                              envModeLabel(prev), envModeLabel(next),
                              currentTapThresholdDb(),
                              (unsigned)currentSkipTtlMs()));
    return next;
}

float currentTapThresholdDb() {
    switch (g_envMode) {
        case EnvMode::URBAN:    return 12.0f;
        case EnvMode::SUBURBAN: return 10.0f;
        case EnvMode::RURAL:    return  6.0f;
    }
    return 10.0f;
}

uint32_t currentSkipTtlMs() {
    switch (g_envMode) {
        case EnvMode::URBAN:    return SPRINT6_SKIP_TTL_URBAN_MS;
        case EnvMode::SUBURBAN: return SPRINT6_SKIP_TTL_SUBURBAN_MS;
        case EnvMode::RURAL:    return SPRINT6_SKIP_TTL_RURAL_MS;
    }
    return SPRINT6_SKIP_TTL_SUBURBAN_MS;
}
