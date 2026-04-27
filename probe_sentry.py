"""Quick read of COM14 to see what SENTRY-RF is actually printing right now."""
import serial, time

s = serial.Serial("COM14", 115200, timeout=1)
print(f"opened {s.port} @ {s.baudrate}")

# Pulse RTS to reset
s.setDTR(False)
s.setRTS(True)
time.sleep(0.3)
s.setRTS(False)
print("RTS reset pulsed")

t0 = time.time()
buf = b""
while time.time() - t0 < 25:
    data = s.read(4096)
    if data:
        buf += data
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = repr(data)
        print(text, end="", flush=True)

s.close()
print(f"\n--- captured {len(buf)} bytes total ---")
