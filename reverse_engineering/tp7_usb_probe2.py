#!/usr/bin/env python3
"""
TP-7 USB MIDI Probe v2 - Brute force header variations.
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

def try_send(dev, sysex_bytes, label, timeout_ms=800):
    usb_packets = sysex_to_usb_midi(sysex_bytes)
    sys.stdout.write(f"  [{label}] TX: {hex_string(sysex_bytes)} ... ")
    sys.stdout.flush()
    try:
        dev.write(EP_OUT, usb_packets, timeout=1000)
    except usb.core.USBError as e:
        print(f"WRITE ERR: {e}")
        return False

    try:
        data = dev.read(EP_IN, 512, timeout=timeout_ms)
        midi = usb_midi_to_sysex(data)
        print(f"GOT RESPONSE! ({len(midi)} bytes)")
        print(f"       RX: {hex_string(midi)}")
        # Decode payload
        if len(midi) > 9 and midi[0] == 0xF0:
            raw = list(midi[9:-1] if midi[-1] == 0xF7 else midi[9:])
            decoded = []
            i = 0
            while i < len(raw):
                msb = raw[i]; i += 1
                for j in range(7):
                    if i >= len(raw): break
                    b = raw[i]
                    if msb & (1 << j): b |= 0x80
                    decoded.append(b); i += 1
            print(f"       Payload: {''.join(chr(b) if 32<=b<127 else '.' for b in decoded)}")
        return True
    except usb.core.USBTimeoutError:
        print("no response")
        return False
    except usb.core.USBError as e:
        print(f"READ ERR: {e}")
        return False


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

    # Drain any pending data
    try:
        while True:
            data = dev.read(EP_IN, 512, timeout=200)
            print(f"  Drained: {hex_string(data)}")
    except:
        pass

    print("=" * 60)
    TE = [0x00, 0x20, 0x76]

    # ============================================================
    # Round 1: The response uses 19 40 21 - try request with SAME header
    # Maybe there's no request/response flag distinction
    # ============================================================
    print("\n=== Round 1: Same header as response (19 40 21) ===")
    for cmd in [0x01, 0x02, 0x04]:
        sysex = bytes([0xF0] + TE + [0x19, 0x40, 0x21, 0x10, cmd, 0xF7])
        if try_send(dev, sysex, f"40-21 cmd={cmd:02X}"):
            break
        time.sleep(0.1)

    # ============================================================
    # Round 2: Try without the "status" byte position
    # Maybe request = [product] [flags] [const] [reqId] [cmd] F7
    # and response = [product] [flags] [const] [reqId] [cmd] [status] [payload] F7
    # We already tried this with flags=0x00. Try with 0x40.
    # ============================================================
    print("\n=== Round 2: Header 19 40 21, no status byte ===")
    for cmd in [0x01, 0x02]:
        sysex = bytes([0xF0] + TE + [0x19, 0x40, 0x21, 0x10, cmd, 0xF7])
        if try_send(dev, sysex, f"40-21 cmd={cmd:02X} (no status)"):
            break
        time.sleep(0.1)

    # ============================================================
    # Round 3: What if bytes 4-5 are a 2-byte value and 0x21 is somewhere else?
    # Try: [mfr] [0x19] [cmd] [reqId] F7 (minimal)
    # ============================================================
    print("\n=== Round 3: Minimal formats ===")
    for variant_name, body in [
        ("19-cmd",           [0x19, 0x01, 0xF7]),
        ("19-01-reqid",      [0x19, 0x01, 0x10, 0xF7]),
        ("19-reqid-cmd",     [0x19, 0x10, 0x01, 0xF7]),
        ("cmd-only",         [0x01, 0xF7]),
        ("19-40-cmd",        [0x19, 0x40, 0x01, 0xF7]),
        ("19-21-cmd",        [0x19, 0x21, 0x01, 0xF7]),
        ("40-19-21-cmd",     [0x40, 0x19, 0x21, 0x01, 0xF7]),
    ]:
        sysex = bytes([0xF0] + TE + body)
        if try_send(dev, sysex, variant_name):
            break
        time.sleep(0.1)

    # ============================================================
    # Round 4: Maybe the TP-7 responds to USB control transfers
    # Try a vendor-specific control request
    # ============================================================
    print("\n=== Round 4: USB Control Transfers ===")
    for bRequest in [0x00, 0x01, 0x06, 0x09, 0x20, 0x21, 0x22, 0xFE]:
        for wValue in [0x0000, 0x0001, 0x0100]:
            try:
                # Device-to-host, vendor, device
                ret = dev.ctrl_transfer(0xC0, bRequest, wValue, 0, 64, timeout=500)
                if ret:
                    print(f"  CTRL bReq=0x{bRequest:02X} wVal=0x{wValue:04X} -> {hex_string(ret)}")
            except usb.core.USBError:
                pass
            try:
                # Device-to-host, vendor, interface
                ret = dev.ctrl_transfer(0xC1, bRequest, wValue, MIDI_INTERFACE, 64, timeout=500)
                if ret:
                    print(f"  CTRL(iface) bReq=0x{bRequest:02X} wVal=0x{wValue:04X} -> {hex_string(ret)}")
            except usb.core.USBError:
                pass
    print("  (control transfer scan done)")

    # ============================================================
    # Round 5: Maybe Field Kit doesn't use the TE SysEx at all for
    # the REQUEST - maybe it uses a standard MIDI message or
    # Universal SysEx (Identity Request)
    # ============================================================
    print("\n=== Round 5: Standard MIDI Identity Request ===")
    # Universal SysEx: Identity Request
    # F0 7E 7F 06 01 F7
    identity_req = bytes([0xF0, 0x7E, 0x7F, 0x06, 0x01, 0xF7])
    try_send(dev, identity_req, "Identity Request")
    time.sleep(0.2)

    # F0 7E 00 06 01 F7 (channel 0)
    identity_req2 = bytes([0xF0, 0x7E, 0x00, 0x06, 0x01, 0xF7])
    try_send(dev, identity_req2, "Identity Request ch0")
    time.sleep(0.2)

    # ============================================================
    # Round 6: Brute force the flag/const byte with greet command
    # Try ALL combinations of bytes 5 and 6
    # ============================================================
    print("\n=== Round 6: Brute force bytes 5-6 (sampled) ===")
    found = False
    for b5 in [0x00, 0x01, 0x10, 0x19, 0x20, 0x21, 0x40, 0x41, 0x60, 0x61]:
        if found: break
        for b6 in [0x00, 0x01, 0x10, 0x19, 0x20, 0x21, 0x40, 0x41, 0x60, 0x61]:
            sysex = bytes([0xF0] + TE + [0x19, b5, b6, 0x10, 0x01, 0xF7])
            if try_send(dev, sysex, f"b5=0x{b5:02X} b6=0x{b6:02X}", timeout_ms=300):
                found = True
                break
            time.sleep(0.05)

    # Cleanup
    try:
        usb.util.release_interface(dev, MIDI_INTERFACE)
    except:
        pass

    print("\nDone.")


if __name__ == '__main__':
    main()
