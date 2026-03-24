#!/usr/bin/env python3
"""
TP-7 Mode Switch - Try different payload formats for the mode command.
We know: header=F0 00 20 76 19 40 40 [reqId] 04 [payload] F7
Status 0=ok, 1=error
"""

import usb.core
import usb.util
import sys
import time

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019
MIDI_INTERFACE = 3
EP_OUT = 0x02
EP_IN = 0x81

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def sysex_to_usb_midi(sysex_bytes):
    packets = []
    data = list(sysex_bytes)
    i = 0
    while i < len(data):
        remaining = len(data) - i
        if remaining >= 3:
            chunk = data[i:i+3]
            cin = 0x07 if chunk[2] == 0xF7 else 0x04
            packets.extend([cin, chunk[0], chunk[1], chunk[2]])
            i += 3
        elif remaining == 2:
            packets.extend([0x06, data[i], data[i+1], 0x00])
            i += 2
        elif remaining == 1:
            packets.extend([0x05, data[i], 0x00, 0x00])
            i += 1
    return bytes(packets)

def usb_midi_to_sysex(usb_data):
    midi_bytes = []
    for i in range(0, len(usb_data), 4):
        if i + 3 >= len(usb_data): break
        cin = usb_data[i] & 0x0F
        if cin == 0x04: midi_bytes.extend([usb_data[i+1], usb_data[i+2], usb_data[i+3]])
        elif cin == 0x07: midi_bytes.extend([usb_data[i+1], usb_data[i+2], usb_data[i+3]])
        elif cin == 0x06: midi_bytes.extend([usb_data[i+1], usb_data[i+2]])
        elif cin == 0x05: midi_bytes.append(usb_data[i+1])
    return bytes(midi_bytes)

def midi7_encode(data_bytes):
    encoded = []
    for i in range(0, len(data_bytes), 7):
        chunk = data_bytes[i:i+7]
        msb = 0
        for j, b in enumerate(chunk):
            if b & 0x80: msb |= (1 << j)
        encoded.append(msb)
        encoded.extend([b & 0x7F for b in chunk])
    return encoded

def try_mode(dev, payload_bytes, label, req_id):
    """Send mode command with given raw payload bytes (already in final SysEx form)."""
    header = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, req_id, 0x04]
    sysex = bytes(header + list(payload_bytes) + [0xF7])
    usb_packets = sysex_to_usb_midi(sysex)

    sys.stdout.write(f"  [{label}] TX: {hex_string(sysex)} ... ")
    sys.stdout.flush()

    # Drain
    try:
        while True: dev.read(EP_IN, 512, timeout=50)
    except: pass

    try:
        dev.write(EP_OUT, usb_packets, timeout=1000)
    except usb.core.USBError as e:
        print(f"WRITE ERR: {e}")
        return None

    try:
        data = dev.read(EP_IN, 512, timeout=1500)
        midi = usb_midi_to_sysex(data)
        status = midi[9] if len(midi) > 9 else -1
        status_str = {0: "OK!", 1: "error", 2: "cmdNotFound", 3: "badRequest"}.get(status, f"unknown({status})")
        print(f"status={status_str} RX: {hex_string(midi)}")
        if status == 0:
            print(f"  *** SUCCESS! Mode switch accepted! ***")
        return status
    except usb.core.USBTimeoutError:
        print("no response (maybe it switched and re-enumerated!)")
        return -2
    except usb.core.USBError as e:
        print(f"READ ERR: {e}")
        return None


def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!")
        sys.exit(1)
    print(f"Found TP-7 (serial: {dev.serial_number})")

    try:
        if dev.is_kernel_driver_active(MIDI_INTERFACE):
            dev.detach_kernel_driver(MIDI_INTERFACE)
    except: pass

    try:
        usb.util.claim_interface(dev, MIDI_INTERFACE)
    except usb.core.USBError as e:
        print(f"Claim warning: {e}")

    req_id = 0x10

    # First, verify greet still works
    print("\n=== Verify: Greet ===")
    header = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, req_id, 0x01, 0xF7]
    usb_packets = sysex_to_usb_midi(bytes(header))
    try:
        dev.write(EP_OUT, usb_packets, timeout=1000)
        data = dev.read(EP_IN, 512, timeout=1500)
        midi = usb_midi_to_sysex(data)
        print(f"  Greet OK: status={midi[9]}")
    except Exception as e:
        print(f"  Greet failed: {e}")
        return
    req_id += 1
    time.sleep(0.3)

    print("\n=== Trying mode command with different payloads ===\n")

    # Strategy: try various payload formats
    tests = [
        # No payload
        ("no-payload", []),

        # Raw single bytes (no 7-bit encoding)
        ("raw-0x00", [0x00]),
        ("raw-0x01", [0x01]),
        ("raw-0x02", [0x02]),
        ("raw-0x03", [0x03]),
        ("raw-0x04", [0x04]),

        # 7-bit encoded single bytes
        ("enc-0x00", [0x00, 0x00]),
        ("enc-0x01", [0x00, 0x01]),
        ("enc-0x02", [0x00, 0x02]),
        ("enc-0x03", [0x00, 0x03]),
        ("enc-0x04", [0x00, 0x04]),

        # 7-bit encoded strings
        ("enc-'mtp'", midi7_encode(b"mtp")),
        ("enc-'midi'", midi7_encode(b"midi")),
        ("enc-'mass_storage'", midi7_encode(b"mass_storage")),
        ("enc-'massStorage'", midi7_encode(b"massStorage")),
        ("enc-'mode:mtp'", midi7_encode(b"mode:mtp")),
        ("enc-'mode:midi'", midi7_encode(b"mode:midi")),
        ("enc-'usb_mode:mtp'", midi7_encode(b"usb_mode:mtp")),

        # Maybe it wants key:value format like the greet response
        ("enc-'mtp;'", midi7_encode(b"mtp;")),
        ("enc-'mode:mtp;'", midi7_encode(b"mode:mtp;")),

        # Raw string bytes (no 7-bit encoding)
        ("raw-'mtp'", list(b"mtp")),
        ("raw-'midi'", list(b"midi")),
    ]

    for label, payload in tests:
        status = try_mode(dev, payload, label, req_id)
        req_id = (req_id + 1) & 0x7F
        if status == 0 or status == -2:
            print("\n*** Found working format! ***")
            break
        time.sleep(0.2)

    try:
        usb.util.release_interface(dev, MIDI_INTERFACE)
    except: pass

    print("\nDone.")


if __name__ == '__main__':
    main()
