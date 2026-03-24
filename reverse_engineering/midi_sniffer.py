#!/usr/bin/env python3
"""
MIDI SysEx Sniffer for Teenage Engineering TP-7
Captures all MIDI traffic using mido + python-rtmidi.
"""

import mido
import sys
import signal
from datetime import datetime

message_count = 0
log_file = open('sysex_capture.log', 'w')

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def handle_message(msg, port_name):
    global message_count

    if msg.type == 'sysex':
        message_count += 1
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        data = msg.data  # tuple of bytes (without F0/F7 framing)
        full = bytes([0xF0] + list(data) + [0xF7])

        lines = []
        lines.append(f"\n{'='*60}")
        lines.append(f"SysEx #{message_count} [{timestamp}] from: {port_name}")
        lines.append(f"{'='*60}")
        lines.append(f"Full ({len(full)} bytes): {hex_string(full)}")

        if len(data) >= 3 and data[0] == 0x00 and data[1] == 0x20 and data[2] == 0x76:
            lines.append("Manufacturer: Teenage Engineering (00 20 76)")
            payload = data[3:]
            if payload:
                lines.append(f"TE Payload ({len(payload)} bytes): {hex_string(payload)}")
                ascii_part = ''.join(chr(b) if 32 <= b < 127 else '.' for b in payload)
                lines.append(f"  ASCII: {ascii_part}")
        elif len(data) >= 1:
            lines.append(f"Manufacturer: {hex_string(data[:3])}")

        lines.append('=' * 60)
        output = '\n'.join(lines)
    else:
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        output = f"[{timestamp}] {port_name}: {msg}"

    print(output)
    sys.stdout.flush()
    log_file.write(output + '\n')
    log_file.flush()


def main():
    print("MIDI SysEx Sniffer for TP-7")
    print("=" * 60)

    # List all available ports
    inputs = mido.get_input_names()
    print(f"\nAvailable MIDI input ports ({len(inputs)}):")
    for name in inputs:
        print(f"  - {name}")

    outputs = mido.get_output_names()
    print(f"\nAvailable MIDI output ports ({len(outputs)}):")
    for name in outputs:
        print(f"  - {name}")

    if not inputs:
        print("\nERROR: No MIDI input ports found. Is the TP-7 connected?")
        sys.exit(1)

    # Open all input ports
    ports = []
    for name in inputs:
        try:
            port = mido.open_input(name)
            ports.append((name, port))
            print(f"\n  Listening on: {name}")
        except Exception as e:
            print(f"\n  Could not open {name}: {e}")

    print(f"\n{'='*60}")
    print("Listening... Open Field Kit and switch TP-7 to MTP mode.")
    print("Press Ctrl+C to stop.")
    print(f"{'='*60}\n")
    sys.stdout.flush()

    def cleanup(sig=None, frame=None):
        print(f"\n\nCaptured {message_count} SysEx message(s).")
        for name, port in ports:
            port.close()
        log_file.close()
        print("Saved to sysex_capture.log")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)

    # Poll all ports for messages
    while True:
        for name, port in ports:
            for msg in port.iter_pending():
                handle_message(msg, name)

if __name__ == '__main__':
    main()
