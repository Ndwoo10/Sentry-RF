import serial, time, sys

PORT = "COM14"
BAUD = 115200
DURATION = 90
OUT = r"C:\Projects\sentry-rf\Sentry-RF-main\boot.log"

s = serial.Serial(PORT, BAUD, timeout=1)
# Proper ESP32 hardware reset: RTS=EN, DTR=GPIO0. Pull EN low to reset,
# keep GPIO0 high so we boot into the app (not bootloader).
s.setDTR(False)   # IO0 = HIGH (run normally, not bootloader)
s.setRTS(True)    # EN   = LOW  (chip in reset)
time.sleep(0.3)
s.setRTS(False)   # EN   = HIGH (release reset -> chip boots)
time.sleep(0.05)
s.reset_input_buffer()
end = time.time() + DURATION
total = 0
with open(OUT, "wb") as f:
    while time.time() < end:
        data = s.read(4096)
        if data:
            f.write(data)
            f.flush()
            total += len(data)
s.close()
print(f"captured {total} bytes in ~{DURATION}s -> {OUT}")
