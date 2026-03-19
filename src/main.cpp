#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <RadioLib.h>
#include <Adafruit_SSD1306.h>
#include "board_config.h"
#include "version.h"

// OLED display: 128x64 pixels
static const int SCREEN_WIDTH  = 128;
static const int SCREEN_HEIGHT = 64;

// LoRa radio on custom SPI pins
SPIClass loraSPI(HSPI);
SX1262 radio = new Module(PIN_LORA_CS, PIN_LORA_DIO1, PIN_LORA_RST, PIN_LORA_BUSY, loraSPI);

// OLED display on I2C
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, PIN_OLED_RST);

void initOLED() {
    // Heltec V3: power on OLED via Vext
    if (HAS_OLED_VEXT) {
        pinMode(PIN_OLED_VEXT, OUTPUT);
        digitalWrite(PIN_OLED_VEXT, LOW);
        delay(10);
    }

    // Heltec V3: pulse reset pin
    if (HAS_OLED_RST) {
        pinMode(PIN_OLED_RST, OUTPUT);
        digitalWrite(PIN_OLED_RST, LOW);
        delay(50);
        digitalWrite(PIN_OLED_RST, HIGH);
        delay(100);
    }

    Wire.begin(PIN_OLED_SDA, PIN_OLED_SCL);

    if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDR)) {
        Serial.println("[OLED] FAIL: SSD1306 not found at 0x3C");
        return;
    }

    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SSD1306_WHITE);
    display.setCursor(0, 0);
    display.printf("%s v%s", FW_NAME, FW_VERSION);
    display.setCursor(0, 16);

#ifdef BOARD_T3S3
    display.println("Board: T3S3");
#elif defined(BOARD_HELTEC_V3)
    display.println("Board: Heltec V3");
#endif

    display.display();
    Serial.println("[OLED] OK");
}

int initLoRa() {
    loraSPI.begin(PIN_LORA_SCK, PIN_LORA_MISO, PIN_LORA_MOSI, PIN_LORA_CS);

    // Heltec V3 requires TCXO voltage before begin()
    if (HAS_TCXO) {
        int tcxoState = radio.setTCXO(1.8);
        if (tcxoState != RADIOLIB_ERR_NONE) {
            Serial.printf("[LoRa] TCXO set failed: %d\n", tcxoState);
        }
    }

    // Initialize at 868 MHz (EU ISM), 125 kHz BW, SF7, CR 4/5
    int state = radio.begin(868.0, 125.0, 7, 5);

    if (state == RADIOLIB_ERR_NONE) {
        Serial.println("[LoRa] OK: SX1262 initialized");
    } else {
        Serial.printf("[LoRa] FAIL: error %d\n", state);
    }

    return state;
}

void setup() {
    Serial.begin(115200);

    // Brief delay for USB-CDC serial on T3S3
    delay(1000);

    Serial.println("========================");
    Serial.printf(" %s v%s\n", FW_NAME, FW_VERSION);
    Serial.printf(" Build: %s\n", FW_DATE);
#ifdef BOARD_T3S3
    Serial.println(" Board: LilyGo T3S3");
#elif defined(BOARD_HELTEC_V3)
    Serial.println(" Board: Heltec V3");
#endif
    Serial.println("========================");

    // Status LED
    pinMode(PIN_LED, OUTPUT);
    digitalWrite(PIN_LED, HIGH);

    // Init peripherals
    initOLED();
    int loraState = initLoRa();

    // Show LoRa status on OLED
    display.setCursor(0, 32);
    if (loraState == RADIOLIB_ERR_NONE) {
        display.println("LoRa: OK");
    } else {
        display.printf("LoRa: ERR %d", loraState);
    }
    display.display();

    // GPS UART — just open the port for now, full init in Sprint 3
    Serial1.begin(GPS_BAUD_DEFAULT, SERIAL_8N1, PIN_GPS_RX, PIN_GPS_TX);
    Serial.printf("[GPS] UART1 open at %d baud (RX=%d, TX=%d)\n",
                  GPS_BAUD_DEFAULT, PIN_GPS_RX, PIN_GPS_TX);

    digitalWrite(PIN_LED, LOW);
    Serial.println("[INIT] Sprint 1 hardware validation complete");
}

void loop() {
    // Blink LED as heartbeat — 1s on, 1s off
    digitalWrite(PIN_LED, HIGH);
    delay(1000);
    digitalWrite(PIN_LED, LOW);
    delay(1000);

    // Print RSSI at current frequency as a quick radio sanity check
    float rssi = radio.getRSSI(false);
    Serial.printf("[HEARTBEAT] RSSI: %.1f dBm\n", rssi);
}
