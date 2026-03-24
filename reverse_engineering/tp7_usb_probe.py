#!/usr/bin/env python3
"""
TP-7 USB MIDI Probe - Send SysEx via raw USB bulk endpoints.
USB MIDI class uses 4-byte packets: [CIN+Cable] [MIDI1] [MIDI2] [MIDI3]
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
    """
    Convert a SysEx message to USB MIDI class packets.
    USB MIDI packet = [Cable(4bit)|CIN(4bit)] [b1] [b2] [b3]

    CIN values for SysEx:
      0x4 = SysEx start or continue (3 bytes)
      0x5 = SysEx end with 1 byte (single 0xF7)
      0x6 = SysEx end with 2 bytes
      0x7 = SysEx end with 3 bytes
    """
    cable = 0x00  # Cable 0
    packets = []
    data = list(sysex_bytes)
    i = 0

    while i < len(data):
        remaining = len(data) - i

        if remaining >= 3:
            # Check if this 3-byte chunk contains the F7 end
            chunk = data[i:i+3]
            if chunk[2] == 0xF7:
                # SysEx ends with 3 bytes
                cin = 0x07
                packets.extend([cable | cin, chunk[0], chunk[1], chunk[2]])
                i += 3
            elif remaining == 2 and chunk[1] == 0xF7:
                # Won't happen here but safety
                cin = 0x06
                packets.extend([cable | cin, chunk[0], chunk[1], 0x00])
                i += 2
            else:
                # SysEx start or continue (3 bytes)
                cin = 0x04
                packets.extend([cable | cin, chunk[0], chunk[1], chunk[2]])
                i += 3
        elif remaining == 2:
            # SysEx end with 2 bytes
            cin = 0x06
            packets.extend([cable | cin, data[i], data[i+1], 0x00])
            i += 2
        elif remaining == 1:
            # SysEx end with 1 byte (just F7)
            cin = 0x05
            packets.extend([cable | cin, data[i], 0x00, 0x00])
            i += 1

    return bytes(packets)

def usb_midi_to_sysex(usb_data):
    """Parse USB MIDI packets back to raw MIDI bytes."""
    midi_bytes = []
    for i in range(0, len(usb_data), 4):
        if i + 3 >= len(usb_data):
            break
        cin = usb_data[i] & 0x0F
        b1 = usb_data[i+1]
        b2 = usb_data[i+2]
        b3 = usb_data[i+3]

        if cin == 0x04:  # SysEx start/continue - 3 bytes
            midi_bytes.extend([b1, b2, b3])
        elif cin == 0x07:  # SysEx end - 3 bytes
            midi_bytes.extend([b1, b2, b3])
        elif cin == 0x06:  # SysEx end - 2 bytes
            midi_bytes.extend([b1, b2])
        elif cin == 0x05:  # SysEx end - 1 byte
            midi_bytes.append(b1)
        elif cin == 0x0F:  # Single byte
            midi_bytes.append(b1)
        elif cin in (0x02, 0x03):  # 2 or 3 byte message
            if cin == 0x02:
                midi_bytes.extend([b1, b2])
            else:
                midi_bytes.extend([b1, b2, b3])

    return bytes(midi_bytes)

def send_sysex(dev, sysex_bytes, timeout=3000):
    """Send SysEx over USB bulk and read response."""
    usb_packets = sysex_to_usb_midi(sysex_bytes)

    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"\n[{timestamp}] SEND SysEx ({len(sysex_bytes)} bytes): {hex_string(sysex_bytes)}")
    print(f"  USB packets ({len(usb_packets)} bytes): {hex_string(usb_packets)}")
    sys.stdout.flush()

    # Send
    dev.write(EP_OUT, usb_packets, timeout=timeout)

    # Read response(s)
    responses = []
    start = time.time()
    while time.time() - start < (timeout / 1000.0):
        try:
            data = dev.read(EP_IN, 512, timeout=500)
            if data:
                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                print(f"[{timestamp}] RECV USB ({len(data)} bytes): {hex_string(data)}")
                midi = usb_midi_to_sysex(data)
                print(f"  MIDI ({len(midi)} bytes): {hex_string(midi)}")
                # Decode ASCII
                if len(midi) > 9:
                    raw = list(midi[9:len(midi)-1] if midi[-1] == 0xF7 else midi[9:])
                    decoded = []
                    i = 0
                    while i < len(raw):
                        msb = raw[i]; i += 1
                        for j in range(7):
                            if i >= len(raw): break
                            b = raw[i]
                            if msb & (1 << j): b |= 0x80
                            decoded.append(b); i += 1
                    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded)
                    print(f"  Payload: {ascii_str}")
                responses.append(midi)
                sys.stdout.flush()
                return responses
        except usb.core.USBTimeoutError:
            pass
        except usb.core.USBError as e:
            print(f"  USB read error: {e}")
            break

    if not responses:
        print(f"  (no response)")
    sys.stdout.flush()
    return responses


def build_sysex(command, request_id, payload_str=None):
    """Build TE SysEx: F0 00 20 76 [product] [flags] [const] [reqId] [cmd] [encoded payload] F7"""
    msg = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x00, 0x21, request_id, command]
    if payload_str:
        raw = payload_str.encode('ascii')
        for i in range(0, len(raw), 7):
            chunk = raw[i:i+7]
            msb = 0
            for j, b in enumerate(chunk):
                if b & 0x80: msb |= (1 << j)
            msg.append(msb)
            msg.extend([b & 0x7F for b in chunk])
    msg.append(0xF7)
    return bytes(msg)


def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!")
        sys.exit(1)

    print(f"Found TP-7 (serial: {dev.serial_number})")

    # Detach kernel driver if needed
    try:
        if dev.is_kernel_driver_active(MIDI_INTERFACE):
            print(f"Detaching kernel driver from interface {MIDI_INTERFACE}...")
            dev.detach_kernel_driver(MIDI_INTERFACE)
    except (usb.core.USBError, NotImplementedError):
        pass

    # Claim interface
    try:
        usb.util.claim_interface(dev, MIDI_INTERFACE)
        print(f"Claimed MIDI interface {MIDI_INTERFACE}")
    except usb.core.USBError as e:
        print(f"Warning: Could not claim interface: {e}")

    print("=" * 60)

    req_id = 0x01

    # Test 1: Greet with no payload
    print("\n--- Test 1: Greet (no payload) ---")
    sysex = build_sysex(0x01, req_id)
    send_sysex(dev, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 2: Greet with payload
    print("\n--- Test 2: Greet (with 'os:linux') ---")
    sysex = build_sysex(0x01, req_id, "os:linux")
    send_sysex(dev, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 3: Echo
    print("\n--- Test 3: Echo ---")
    sysex = build_sysex(0x02, req_id)
    send_sysex(dev, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 4: Try just reading - maybe the TP-7 sends greet proactively
    print("\n--- Test 4: Just read (no send) ---")
    try:
        data = dev.read(EP_IN, 512, timeout=2000)
        print(f"  Unsolicited data: {hex_string(data)}")
    except usb.core.USBTimeoutError:
        print("  (nothing pending)")
    except usb.core.USBError as e:
        print(f"  Error: {e}")

    # Cleanup
    try:
        usb.util.release_interface(dev, MIDI_INTERFACE)
    except:
        pass

    print("\nDone.")


if __name__ == '__main__':
    main()
