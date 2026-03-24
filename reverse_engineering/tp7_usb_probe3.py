#!/usr/bin/env python3
"""
TP-7 USB MIDI Probe v3 - Now we know the header!
Request header: F0 00 20 76 19 40 40 [reqId] [cmd] [payload] F7
"""

import usb.core
import usb.util
import sys
import time
from datetime import datetime

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019
MIDI_INTERFACE = 3
EP_OUT = 0x02
EP_IN = 0x81

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def sysex_to_usb_midi(sysex_bytes):
    cable = 0x00
    packets = []
    data = list(sysex_bytes)
    i = 0
    while i < len(data):
        remaining = len(data) - i
        if remaining >= 3:
            chunk = data[i:i+3]
            if chunk[2] == 0xF7:
                packets.extend([cable | 0x07, chunk[0], chunk[1], chunk[2]])
            else:
                packets.extend([cable | 0x04, chunk[0], chunk[1], chunk[2]])
            i += 3
        elif remaining == 2:
            packets.extend([cable | 0x06, data[i], data[i+1], 0x00])
            i += 2
        elif remaining == 1:
            packets.extend([cable | 0x05, data[i], 0x00, 0x00])
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
    """Encode raw bytes to MIDI 7-bit format."""
    encoded = []
    for i in range(0, len(data_bytes), 7):
        chunk = data_bytes[i:i+7]
        msb = 0
        for j, b in enumerate(chunk):
            if b & 0x80:
                msb |= (1 << j)
        encoded.append(msb)
        encoded.extend([b & 0x7F for b in chunk])
    return encoded

def midi7_decode(encoded):
    """Decode MIDI 7-bit encoded data back to raw bytes."""
    decoded = []
    i = 0
    while i < len(encoded):
        msb = encoded[i]
        i += 1
        for j in range(7):
            if i >= len(encoded):
                break
            b = encoded[i]
            if msb & (1 << j):
                b |= 0x80
            decoded.append(b)
            i += 1
    return decoded

def send_sysex(dev, sysex_bytes, label, timeout_ms=2000):
    usb_packets = sysex_to_usb_midi(sysex_bytes)
    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"\n[{timestamp}] [{label}] TX ({len(sysex_bytes)} bytes): {hex_string(sysex_bytes)}")
    sys.stdout.flush()

    try:
        dev.write(EP_OUT, usb_packets, timeout=1000)
    except usb.core.USBError as e:
        print(f"  WRITE ERR: {e}")
        return None

    # Read response(s) - may come in multiple USB packets
    all_usb_data = bytearray()
    start = time.time()
    while time.time() - start < (timeout_ms / 1000.0):
        try:
            data = dev.read(EP_IN, 512, timeout=500)
            if data:
                all_usb_data.extend(data)
                # Check if we have a complete SysEx (ends with F7)
                midi = usb_midi_to_sysex(all_usb_data)
                if midi and midi[-1] == 0xF7:
                    break
        except usb.core.USBTimeoutError:
            break
        except usb.core.USBError as e:
            print(f"  READ ERR: {e}")
            break

    if all_usb_data:
        midi = usb_midi_to_sysex(all_usb_data)
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        print(f"[{timestamp}] [{label}] RX ({len(midi)} bytes): {hex_string(midi)}")

        # Parse TE response
        if len(midi) >= 9 and midi[0] == 0xF0 and midi[1:4] == bytes([0x00, 0x20, 0x76]):
            product = midi[4]
            b5 = midi[5]
            b6 = midi[6]
            b7 = midi[7]
            cmd = midi[8]
            status = midi[9] if len(midi) > 9 else None
            print(f"  Header: product=0x{product:02X} b5=0x{b5:02X} b6=0x{b6:02X} b7=0x{b7:02X}")
            print(f"  Command: 0x{cmd:02X} Status: {status}")

            if len(midi) > 10:
                payload_enc = list(midi[10:-1] if midi[-1] == 0xF7 else midi[10:])
                payload = midi7_decode(payload_enc)
                ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in payload)
                print(f"  Payload decoded: {ascii_str}")

        return midi
    else:
        print(f"  (no response)")
        return None


def build_request(cmd, req_id, payload_str=None):
    """Build TE SysEx request with the discovered header format."""
    # Request: F0 00 20 76 19 40 40 [reqId] [cmd] [encoded payload] F7
    msg = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, req_id, cmd]
    if payload_str:
        encoded = midi7_encode(payload_str.encode('ascii'))
        msg.extend(encoded)
    msg.append(0xF7)
    return bytes(msg)


def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!")
        sys.exit(1)
    print(f"Found TP-7 (serial: {dev.serial_number})")

    try:
        if dev.is_kernel_driver_active(MIDI_INTERFACE):
            dev.detach_kernel_driver(MIDI_INTERFACE)
    except (usb.core.USBError, NotImplementedError):
        pass

    try:
        usb.util.claim_interface(dev, MIDI_INTERFACE)
        print(f"Claimed MIDI interface")
    except usb.core.USBError as e:
        print(f"Claim warning: {e}")

    # Drain pending
    try:
        while True:
            dev.read(EP_IN, 512, timeout=200)
    except:
        pass

    print("=" * 60)

    req_id = 0x01

    # ========================================
    # Test 1: Greet (no payload) - should work!
    # ========================================
    print("\n--- Test 1: Greet (no payload) ---")
    sysex = build_request(0x01, req_id)
    send_sysex(dev, sysex, "greet-bare")
    req_id += 1
    time.sleep(0.5)

    # ========================================
    # Test 2: Greet with OS info payload
    # ========================================
    print("\n--- Test 2: Greet (with OS info) ---")
    sysex = build_request(0x01, req_id, "os_version:Linux 6.1")
    send_sysex(dev, sysex, "greet-os")
    req_id += 1
    time.sleep(0.5)

    # ========================================
    # Test 3: Echo
    # ========================================
    print("\n--- Test 3: Echo ---")
    sysex = build_request(0x02, req_id)
    send_sysex(dev, sysex, "echo")
    req_id += 1
    time.sleep(0.5)

    # ========================================
    # Test 4: Mode with 'mtp' payload
    # ========================================
    print("\n--- Test 4: Mode 'mtp' ---")
    sysex = build_request(0x04, req_id, "mtp")
    resp = send_sysex(dev, sysex, "mode-mtp")
    req_id += 1

    if resp:
        print("\n*** Mode switch response received! ***")
        print("*** The TP-7 should now re-enumerate as MTP device ***")
        print("*** Check: system_profiler SPUSBDataType | grep -A5 TP-7 ***")
    else:
        # Try alternate payloads for mode command
        time.sleep(0.5)
        print("\n--- Test 4b: Mode (no payload) ---")
        sysex = build_request(0x04, req_id)
        send_sysex(dev, sysex, "mode-bare")
        req_id += 1
        time.sleep(0.5)

        print("\n--- Test 4c: Mode with numeric payload ---")
        # Try encoding a single byte 0x02 as the mode value
        for mode_val in [0x01, 0x02, 0x03, 0x04]:
            msg = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, req_id, 0x04, 0x00, mode_val, 0xF7]
            send_sysex(dev, bytes(msg), f"mode-val={mode_val}")
            req_id += 1
            time.sleep(0.3)

    # Cleanup
    try:
        usb.util.release_interface(dev, MIDI_INTERFACE)
    except:
        pass

    print("\nDone.")


if __name__ == '__main__':
    main()
