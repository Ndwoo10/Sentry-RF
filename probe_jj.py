"""Read-only probe of JJ v3.0 on COM6. No transmit commands issued."""
import serial, time

PORT = "COM6"
BAUD = 115200


def hexdump(b):
    return b.hex(" ") if b else "<empty>"


def read_window(s, seconds, label):
    end = time.time() + seconds
    chunks = []
    while time.time() < end:
        d = s.read(4096)
        if d:
            chunks.append(d)
    raw = b"".join(chunks)
    text = raw.decode("utf-8", errors="replace")
    print(f"--- {label}: {len(raw)} bytes ---")
    if raw:
        print("decoded:")
        print(text)
        print(f"hex: {hexdump(raw[:128])}{' ...' if len(raw) > 128 else ''}")
    else:
        print("(no data)")
    print()
    return raw, text


def send(s, payload, label):
    print(f">>> send {label}: {payload!r}")
    s.write(payload)
    s.flush()


def main():
    print(f"Opening {PORT} at {BAUD}...")
    # Disable flow control. pyserial still asserts DTR/RTS on open by default on Windows,
    # which on ESP32-S3 dev boards typically causes a reboot — that's useful (we'll see a banner).
    s = serial.Serial(PORT, BAUD, timeout=0.2, rtscts=False, dsrdtr=False,
                      xonxoff=False)
    print(f"Opened. DTR={s.dtr} RTS={s.rts}")

    # Phase 0 — capture anything JJ is printing without us saying hello.
    # This catches a boot banner if the port open caused a reset, or a prompt if it didn't.
    read_window(s, 2.0, "Phase 0: passive listen (2.0s after open)")

    # Phase 1 — send just a bare \r\n, wait 500ms, then a 1s read.
    send(s, b"\r\n", r"'\r\n'")
    time.sleep(0.5)
    raw1, text1 = read_window(s, 1.0, "Phase 1: reply after '\\r\\n'")

    # Echo check: did we just get our \r or \n back immediately?
    cr_echo = b"\r" in raw1 or b"\n" in raw1
    print(f"echo check (CR/LF): bytes_seen={cr_echo}\n")

    # Phase 2 — '?' + \r\n
    send(s, b"?\r\n", r"'?\r\n'")
    raw2, text2 = read_window(s, 1.0, "Phase 2: reply after '?'")
    echo_qm = b"?" in raw2
    print(f"echo check ('?'): {echo_qm}\n")

    # Phase 3 — 'h' + \r\n
    send(s, b"h\r\n", r"'h\r\n'")
    raw3, text3 = read_window(s, 1.0, "Phase 3: reply after 'h'")
    echo_h = b"h" in raw3
    print(f"echo check ('h'): {echo_h}\n")

    # Phase 4 — 'help' + \r\n
    send(s, b"help\r\n", r"'help\r\n'")
    raw4, text4 = read_window(s, 1.5, "Phase 4: reply after 'help'")
    echo_help = b"help" in raw4 or b"h" in raw4
    print(f"echo check ('help' token): {echo_help}\n")

    # Summary
    total_rx = len(raw1) + len(raw2) + len(raw3) + len(raw4)
    print("========== SUMMARY ==========")
    print(f"Any reply at all: {total_rx > 0}")
    print(f"Echo on '?' : {echo_qm}")
    print(f"Echo on 'h' : {echo_h}")
    print(f"Echo on 'help' : {echo_help}")
    print(f"Total bytes received across 4 probes: {total_rx}")

    s.close()


if __name__ == "__main__":
    main()
