# SENTRY-RF Characterization Summary

- Session: 2026-04-24T11:02:18.651369 → 2026-04-24T14:08:36.450147
- Tests attempted: 38
- Tests successful: 38
- SENTRY-RF commit: 082d300 (v2.0.0-rc1)
- JJ commit: c360f5b (v3.0.0)
- Environment: Urban bench test, Suburban USA

## 1. Ambient RF Characterization
- Tests starting at ADVISORY: 1/38
- Baseline anchor freqs observed: [902.3, 915.3, 920.4, 924.0, 928.0]
- FHSS-SPREAD subGHz baselines: min=86, max=93
- FHSS-SPREAD 2G4 baselines: min=21, max=27
- Scan-peak RSSI: p50=-98.0dBm p90=-64.0dBm p99=-53.5dBm

## 2. Master Results Table

| test | label | cmd | starting | peak | t_adv | t_warn | t_crit | pkts | hops | clear | retry | flags |
|------|-------|-----|----------|------|-------|--------|--------|------|------|-------|-------|-------|
| A01 | ELRS_FCC915_200Hz | `e1` | CLEAR | CLEAR | None | None | None | 2 | 0 | Y | 0 | - |
| A02 | ELRS_FCC915_100Hz | `e2` | CLEAR | CLEAR | None | None | None | 2 | 0 | Y | 0 | - |
| A03 | ELRS_FCC915_50Hz | `e3` | CLEAR | ADVISORY | 35.207 | None | None | 2 | 0 | Y | 0 | - |
| A04 | ELRS_FCC915_25Hz | `e4` | CLEAR | WARNING | 52.366 | 47.32 | None | 2 | 0 | Y | 0 | - |
| A05 | ELRS_FCC915_D250_500Hz | `e5` | CLEAR | ADVISORY | 35.212 | None | None | 2 | 0 | Y | 0 | - |
| A06 | ELRS_FCC915_D500 | `e6` | CLEAR | ADVISORY | 40.197 | None | None | 2 | 0 | Y | 0 | - |
| B01 | ELRS_EU868_200Hz | `e1u` | CLEAR | ADVISORY | 90.738 | None | None | 2 | 0 | Y | 0 | - |
| B02 | ELRS_EU868_100Hz | `e2u` | CLEAR | CLEAR | None | None | None | 2 | 0 | Y | 0 | - |
| B03 | ELRS_EU868_50Hz | `e3u` | CLEAR | ADVISORY | 35.186 | None | None | 2 | 0 | Y | 0 | - |
| B04 | ELRS_EU868_25Hz | `e4u` | CLEAR | ADVISORY | 35.192 | None | None | 2 | 0 | Y | 0 | - |
| C01 | ELRS_AU915_200Hz | `e1a` | CLEAR | ADVISORY | 35.186 | None | None | 2 | 0 | Y | 0 | - |
| C02 | ELRS_IN866_200Hz | `e1i` | CLEAR | ADVISORY | 35.224 | None | None | 2 | 0 | Y | 0 | - |
| D01 | ELRS_FCC915_binding_beacon | `e1fb` | CLEAR | ADVISORY | 34.219 | None | None | 2 | 0 | Y | 0 | - |
| E01 | Crossfire_FSK_FCC915_150Hz | `g` | CLEAR | ADVISORY | 85.789 | None | None | 2 | 0 | Y | 0 | - |
| E02 | Crossfire_FSK_EU868_150Hz | `g8` | CLEAR | ADVISORY | 49.409 | None | None | 2 | 0 | Y | 0 | - |
| E03 | Crossfire_LoRa_FCC915_50Hz | `gl` | CLEAR | ADVISORY | 34.272 | None | None | 2 | 0 | Y | 0 | - |
| E04 | Crossfire_LoRa_EU868_50Hz | `gl8` | CLEAR | ADVISORY | 45.264 | None | None | 2 | 0 | Y | 0 | - |
| F01 | SiK_MAVLink_US915_GFSK | `k1` | CLEAR | ADVISORY | 35.205 | None | None | 2 | 0 | Y | 0 | - |
| F02 | mLRS_FCC915_LoRa_19Hz | `l1` | CLEAR | ADVISORY | 35.209 | None | None | 2 | 0 | Y | 0 | - |
| G01 | ELRS_2G4_500Hz | `x1` | CLEAR | CLEAR | None | None | None | 2 | 0 | Y | 0 | - |
| G02 | ELRS_2G4_250Hz | `x2` | CLEAR | ADVISORY | 35.153 | None | None | 2 | 0 | Y | 0 | - |
| G03 | ELRS_2G4_150Hz | `x3` | CLEAR | ADVISORY | 35.158 | None | None | 2 | 0 | Y | 0 | - |
| G04 | ELRS_2G4_50Hz | `x4` | CLEAR | ADVISORY | 34.2 | None | None | 2 | 0 | Y | 0 | - |
| H01 | Ghost_2G4 | `x5` | CLEAR | ADVISORY | 35.202 | None | None | 2 | 0 | Y | 0 | - |
| H02 | FrSky_D16_2G4 | `x6` | CLEAR | ADVISORY | 35.138 | None | None | 2 | 0 | Y | 0 | - |
| H03 | FlySky_2G4 | `x7` | CLEAR | ADVISORY | 85.738 | None | None | 2 | 0 | N | 0 | - |
| I01 | WiFi_ODID_only | `y1` | CLEAR | ADVISORY | 45.283 | None | None | 2 | 0 | Y | 0 | - |
| I02 | BLE_ODID_only | `y2` | CLEAR | ADVISORY | 35.248 | None | None | 2 | 0 | Y | 0 | - |
| I03 | DJI_DroneID_only | `y3` | CLEAR | ADVISORY | 70.434 | None | None | 2 | 0 | Y | 0 | - |
| I04 | RemoteID_all_three_transports | `y` | ADVISORY | ADVISORY | 49.228 | None | None | 2 | 0 | Y | 0 | - |
| J01 | LoRaWAN_US915_infrastructure | `i` | CLEAR | ADVISORY | 35.237 | None | None | 2 | 0 | Y | 0 | - |
| J02 | Meshtastic_915 | `f1` | CLEAR | CLEAR | None | None | None | 2 | 0 | Y | 0 | - |
| J03 | Helium_PoC_915 | `f2` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |
| K01 | Mixed_ELRS_plus_LoRaWAN | `m` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |
| K02 | Combined_Racing_Drone | `c1` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |
| K03 | Combined_DJI_Consumer | `c2` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |
| K04 | Combined_LongRange_FPV | `c3` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |
| K05 | Combined_Everything_StressTest | `c5` | CLEAR | CLEAR | None | None | None | 2 | 0 | N | 0 | - |

## 3. Per-Group Analysis
### Group A
- **A01 ELRS_FCC915_200Hz** (`e1`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **A02 ELRS_FCC915_100Hz** (`e2`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **A03 ELRS_FCC915_50Hz** (`e3`): start=CLEAR peak=ADVISORY t_adv=35.207s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **A04 ELRS_FCC915_25Hz** (`e4`): start=CLEAR peak=WARNING t_adv=52.366s t_warn=47.32s t_crit=Nones JJ=2pkt/0hops flags=[]
- **A05 ELRS_FCC915_D250_500Hz** (`e5`): start=CLEAR peak=ADVISORY t_adv=35.212s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **A06 ELRS_FCC915_D500** (`e6`): start=CLEAR peak=ADVISORY t_adv=40.197s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group B
- **B01 ELRS_EU868_200Hz** (`e1u`): start=CLEAR peak=ADVISORY t_adv=90.738s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **B02 ELRS_EU868_100Hz** (`e2u`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **B03 ELRS_EU868_50Hz** (`e3u`): start=CLEAR peak=ADVISORY t_adv=35.186s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **B04 ELRS_EU868_25Hz** (`e4u`): start=CLEAR peak=ADVISORY t_adv=35.192s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group C
- **C01 ELRS_AU915_200Hz** (`e1a`): start=CLEAR peak=ADVISORY t_adv=35.186s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **C02 ELRS_IN866_200Hz** (`e1i`): start=CLEAR peak=ADVISORY t_adv=35.224s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group D
- **D01 ELRS_FCC915_binding_beacon** (`e1fb`): start=CLEAR peak=ADVISORY t_adv=34.219s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group E
- **E01 Crossfire_FSK_FCC915_150Hz** (`g`): start=CLEAR peak=ADVISORY t_adv=85.789s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **E02 Crossfire_FSK_EU868_150Hz** (`g8`): start=CLEAR peak=ADVISORY t_adv=49.409s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **E03 Crossfire_LoRa_FCC915_50Hz** (`gl`): start=CLEAR peak=ADVISORY t_adv=34.272s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **E04 Crossfire_LoRa_EU868_50Hz** (`gl8`): start=CLEAR peak=ADVISORY t_adv=45.264s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group F
- **F01 SiK_MAVLink_US915_GFSK** (`k1`): start=CLEAR peak=ADVISORY t_adv=35.205s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **F02 mLRS_FCC915_LoRa_19Hz** (`l1`): start=CLEAR peak=ADVISORY t_adv=35.209s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group G
- **G01 ELRS_2G4_500Hz** (`x1`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **G02 ELRS_2G4_250Hz** (`x2`): start=CLEAR peak=ADVISORY t_adv=35.153s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **G03 ELRS_2G4_150Hz** (`x3`): start=CLEAR peak=ADVISORY t_adv=35.158s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **G04 ELRS_2G4_50Hz** (`x4`): start=CLEAR peak=ADVISORY t_adv=34.2s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group H
- **H01 Ghost_2G4** (`x5`): start=CLEAR peak=ADVISORY t_adv=35.202s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **H02 FrSky_D16_2G4** (`x6`): start=CLEAR peak=ADVISORY t_adv=35.138s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **H03 FlySky_2G4** (`x7`): start=CLEAR peak=ADVISORY t_adv=85.738s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group I
- **I01 WiFi_ODID_only** (`y1`): start=CLEAR peak=ADVISORY t_adv=45.283s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **I02 BLE_ODID_only** (`y2`): start=CLEAR peak=ADVISORY t_adv=35.248s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **I03 DJI_DroneID_only** (`y3`): start=CLEAR peak=ADVISORY t_adv=70.434s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **I04 RemoteID_all_three_transports** (`y`): start=ADVISORY peak=ADVISORY t_adv=49.228s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group J
- **J01 LoRaWAN_US915_infrastructure** (`i`): start=CLEAR peak=ADVISORY t_adv=35.237s t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **J02 Meshtastic_915** (`f1`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **J03 Helium_PoC_915** (`f2`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

### Group K
- **K01 Mixed_ELRS_plus_LoRaWAN** (`m`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **K02 Combined_Racing_Drone** (`c1`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **K03 Combined_DJI_Consumer** (`c2`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **K04 Combined_LongRange_FPV** (`c3`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]
- **K05 Combined_Everything_StressTest** (`c5`): start=CLEAR peak=CLEAR t_adv=Nones t_warn=Nones t_crit=Nones JJ=2pkt/0hops flags=[]

## 4. Detection Path Coverage Map

| Protocol | peak | CAD_subConf>0 | CAD_fastConf>0 | FHSS_delta>0 | RSSI_peak_strong (<-95dBm) |
|----------|------|---------------|----------------|--------------|----------------------------|
| ELRS_FCC915_200Hz | CLEAR | N | N | Y | Y |
| ELRS_FCC915_100Hz | CLEAR | N | N | Y | Y |
| ELRS_FCC915_50Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_FCC915_25Hz | WARNING | Y | Y | Y | Y |
| ELRS_FCC915_D250_500Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_FCC915_D500 | ADVISORY | Y | Y | Y | Y |
| ELRS_EU868_200Hz | ADVISORY | Y | Y | N | Y |
| ELRS_EU868_100Hz | CLEAR | N | N | Y | Y |
| ELRS_EU868_50Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_EU868_25Hz | ADVISORY | Y | Y | N | Y |
| ELRS_AU915_200Hz | ADVISORY | Y | Y | N | Y |
| ELRS_IN866_200Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_FCC915_binding_beacon | ADVISORY | Y | Y | Y | Y |
| Crossfire_FSK_FCC915_150Hz | ADVISORY | Y | Y | Y | N |
| Crossfire_FSK_EU868_150Hz | ADVISORY | N | N | N | Y |
| Crossfire_LoRa_FCC915_50Hz | ADVISORY | Y | Y | N | Y |
| Crossfire_LoRa_EU868_50Hz | ADVISORY | Y | Y | Y | Y |
| SiK_MAVLink_US915_GFSK | ADVISORY | Y | Y | Y | Y |
| mLRS_FCC915_LoRa_19Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_2G4_500Hz | CLEAR | N | N | Y | N |
| ELRS_2G4_250Hz | ADVISORY | Y | Y | Y | N |
| ELRS_2G4_150Hz | ADVISORY | Y | Y | Y | Y |
| ELRS_2G4_50Hz | ADVISORY | Y | Y | N | N |
| Ghost_2G4 | ADVISORY | Y | Y | N | N |
| FrSky_D16_2G4 | ADVISORY | Y | Y | Y | Y |
| FlySky_2G4 | ADVISORY | Y | Y | Y | Y |
| WiFi_ODID_only | ADVISORY | Y | Y | N | Y |
| BLE_ODID_only | ADVISORY | Y | Y | Y | Y |
| DJI_DroneID_only | ADVISORY | N | Y | Y | N |
| RemoteID_all_three_transports | ADVISORY | N | N | N | Y |
| LoRaWAN_US915_infrastructure | ADVISORY | Y | Y | Y | Y |
| Meshtastic_915 | CLEAR | N | N | N | Y |
| Helium_PoC_915 | CLEAR | N | N | N | Y |
| Mixed_ELRS_plus_LoRaWAN | CLEAR | N | N | N | N |
| Combined_Racing_Drone | CLEAR | N | N | N | N |
| Combined_DJI_Consumer | CLEAR | N | N | N | N |
| Combined_LongRange_FPV | CLEAR | N | N | N | N |
| Combined_Everything_StressTest | CLEAR | N | N | N | N |

## 5. Protocol Coverage Matrix

| Protocol | Detected (≥ADVISORY) | Escalated (≥WARNING) | CRITICAL | Clean Return |
|----------|----------------------|----------------------|----------|--------------|
| ELRS_FCC915_200Hz | N | N | N | Y |
| ELRS_FCC915_100Hz | N | N | N | Y |
| ELRS_FCC915_50Hz | Y | N | N | Y |
| ELRS_FCC915_25Hz | Y | Y | N | Y |
| ELRS_FCC915_D250_500Hz | Y | N | N | Y |
| ELRS_FCC915_D500 | Y | N | N | Y |
| ELRS_EU868_200Hz | Y | N | N | Y |
| ELRS_EU868_100Hz | N | N | N | Y |
| ELRS_EU868_50Hz | Y | N | N | Y |
| ELRS_EU868_25Hz | Y | N | N | Y |
| ELRS_AU915_200Hz | Y | N | N | Y |
| ELRS_IN866_200Hz | Y | N | N | Y |
| ELRS_FCC915_binding_beacon | Y | N | N | Y |
| Crossfire_FSK_FCC915_150Hz | Y | N | N | Y |
| Crossfire_FSK_EU868_150Hz | Y | N | N | Y |
| Crossfire_LoRa_FCC915_50Hz | Y | N | N | Y |
| Crossfire_LoRa_EU868_50Hz | Y | N | N | Y |
| SiK_MAVLink_US915_GFSK | Y | N | N | Y |
| mLRS_FCC915_LoRa_19Hz | Y | N | N | Y |
| ELRS_2G4_500Hz | N | N | N | Y |
| ELRS_2G4_250Hz | Y | N | N | Y |
| ELRS_2G4_150Hz | Y | N | N | Y |
| ELRS_2G4_50Hz | Y | N | N | Y |
| Ghost_2G4 | Y | N | N | Y |
| FrSky_D16_2G4 | Y | N | N | Y |
| FlySky_2G4 | Y | N | N | N |
| WiFi_ODID_only | Y | N | N | Y |
| BLE_ODID_only | Y | N | N | Y |
| DJI_DroneID_only | Y | N | N | Y |
| RemoteID_all_three_transports | Y | N | N | Y |
| LoRaWAN_US915_infrastructure | Y | N | N | Y |
| Meshtastic_915 | N | N | N | Y |
| Helium_PoC_915 | N | N | N | N |
| Mixed_ELRS_plus_LoRaWAN | N | N | N | N |
| Combined_Racing_Drone | N | N | N | N |
| Combined_DJI_Consumer | N | N | N | N |
| Combined_LongRange_FPV | N | N | N | N |
| Combined_Everything_StressTest | N | N | N | N |
