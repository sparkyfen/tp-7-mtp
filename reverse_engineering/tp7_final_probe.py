#!/usr/bin/env python3
"""
TP-7 Final Probe - Try everything we haven't tried yet:
1. All command bytes (0x00-0x7F) to find which ones exist
2. Mode command after claiming ALL interfaces
3. Mode command with different cable numbers in USB MIDI framing
4. Mode command after releasing the interface (send without claim)
"""

import usb.core
import usb.util
import sys
import time

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def sysex_to_usb(sysex, cable=0):
    pkts = []
    data = list(sysex)
    i = 0
    while i < len(data):
        rem = len(data) - i
        if rem >= 3:
            cin = 0x07 if data[i+2] == 0xF7 else 0x04
            pkts.extend([(cable << 4) | cin, data[i], data[i+1], data[i+2]])
            i += 3
        elif rem == 2:
            pkts.extend([(cable << 4) | 0x06, data[i], data[i+1], 0x00])
            i += 2
        elif rem == 1:
            pkts.extend([(cable << 4) | 0x05, data[i], 0x00, 0x00])
            i += 1
    return bytes(pkts)

def usb_to_midi(usb_data):
    r = []
    for i in range(0, len(usb_data), 4):
        cin = usb_data[i] & 0x0F
        if cin == 0x04: r.extend([usb_data[i+1], usb_data[i+2], usb_data[i+3]])
        elif cin == 0x07: r.extend([usb_data[i+1], usb_data[i+2], usb_data[i+3]])
        elif cin == 0x06: r.extend([usb_data[i+1], usb_data[i+2]])
        elif cin == 0x05: r.append(usb_data[i+1])
    return bytes(r)

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

EP_OUT = 0x02
EP_IN = 0x81
MIDI_INTF = 3

def send_cmd(dev, cmd, req_id=0x10, payload=None, timeout=500):
    """Send TE SysEx and return (status, response_bytes) or (None, None)."""
    header = [0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, req_id, cmd]
    if payload:
        header.extend(payload)
    header.append(0xF7)
    sysex = bytes(header)
    usb_pkt = sysex_to_usb(sysex)

    # Drain
    try:
        while True: dev.read(EP_IN, 512, timeout=50)
    except: pass

    try:
        dev.write(EP_OUT, usb_pkt, timeout=1000)
    except usb.core.USBError:
        return None, None

    try:
        data = dev.read(EP_IN, 512, timeout=timeout)
        midi = usb_to_midi(data)
        status = midi[9] if len(midi) > 9 else -1
        return status, midi
    except usb.core.USBTimeoutError:
        return -2, None  # timeout - might mean device switched
    except usb.core.USBError:
        return None, None


def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!"); sys.exit(1)
    print(f"Product: {dev.product}")

    try:
        if dev.is_kernel_driver_active(MIDI_INTF):
            dev.detach_kernel_driver(MIDI_INTF)
    except: pass
    try:
        usb.util.claim_interface(dev, MIDI_INTF)
    except: pass

    status_names = {0: "ok", 1: "error", 2: "cmdNotFound", 3: "badRequest"}

    # ========================================
    # Test 1: Scan ALL command bytes to map the command space
    # ========================================
    print("\n=== Test 1: Command byte scan (0x00-0x20) ===")
    for cmd in range(0x21):
        status, resp = send_cmd(dev, cmd, timeout=400)
        sname = status_names.get(status, f"unk({status})")
        if status is not None and status != -2:
            resp_cmd = resp[8] if resp and len(resp) > 8 else '?'
            if status != 2:  # Skip cmdNotFound, only show recognized commands
                print(f"  cmd=0x{cmd:02X} -> status={sname} resp_cmd={resp_cmd}")
        elif status == -2:
            print(f"  cmd=0x{cmd:02X} -> TIMEOUT (device may have switched!)")
            time.sleep(2)
            dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev2:
                print(f"    Device: {dev2.product}")
            break
        time.sleep(0.05)

    # ========================================
    # Test 2: Try mode (0x04) with different cable numbers
    # ========================================
    print("\n=== Test 2: Mode cmd with different USB MIDI cable numbers ===")
    for cable in range(1, 4):
        sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x30, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7])
        usb_pkt = sysex_to_usb(sysex, cable=cable)

        try:
            while True: dev.read(EP_IN, 512, timeout=50)
        except: pass

        try:
            dev.write(EP_OUT, usb_pkt, timeout=500)
            data = dev.read(EP_IN, 512, timeout=500)
            midi = usb_to_midi(data)
            status = midi[9] if len(midi) > 9 else -1
            print(f"  cable={cable} -> status={status_names.get(status, status)}")
        except usb.core.USBTimeoutError:
            print(f"  cable={cable} -> timeout")
        except usb.core.USBError as e:
            print(f"  cable={cable} -> error: {e}")

    # ========================================
    # Test 3: Claim ALL interfaces, then send mode
    # ========================================
    print("\n=== Test 3: Claim all interfaces, then mode ===")
    for intf_num in [0, 1, 2]:
        try:
            if dev.is_kernel_driver_active(intf_num):
                dev.detach_kernel_driver(intf_num)
            usb.util.claim_interface(dev, intf_num)
            print(f"  Claimed interface {intf_num}")
        except usb.core.USBError as e:
            print(f"  Could not claim interface {intf_num}: {e}")

    status, resp = send_cmd(dev, 0x04, req_id=0x40, payload=[0x00, 0x6D, 0x74, 0x70])
    print(f"  Mode after claiming all: status={status_names.get(status, status)}")

    # Release extra interfaces
    for intf_num in [0, 1, 2]:
        try: usb.util.release_interface(dev, intf_num)
        except: pass

    # ========================================
    # Test 4: Try mode with raw bytes WITHOUT USB MIDI framing
    # (send raw SysEx directly to bulk endpoint)
    # ========================================
    print("\n=== Test 4: Raw SysEx (no USB MIDI framing) ===")
    raw_sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x50, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7])
    try:
        while True: dev.read(EP_IN, 512, timeout=50)
    except: pass
    try:
        dev.write(EP_OUT, raw_sysex, timeout=1000)
        data = dev.read(EP_IN, 512, timeout=1000)
        print(f"  Got response: {hex_string(data)}")
    except usb.core.USBTimeoutError:
        print(f"  Timeout (checking for re-enumeration...)")
        time.sleep(2)
        dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
        if dev2:
            print(f"    Device: {dev2.product}")
        else:
            print(f"    Device GONE!")
    except usb.core.USBError as e:
        print(f"  Error: {e}")

    # ========================================
    # Test 5: What if the mode VALUE goes in a header byte?
    # Try: header byte 7 (which we called reqId) as mode value
    # With cmd=0x04, put 0x02/0x03/etc in byte 7
    # ========================================
    print("\n=== Test 5: Mode value in header byte 7 ===")
    for mode_in_b7 in [0x00, 0x01, 0x02, 0x03, 0x04, 0x05]:
        sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, mode_in_b7, 0x04, 0xF7])
        usb_pkt = sysex_to_usb(sysex)
        try:
            while True: dev.read(EP_IN, 512, timeout=50)
        except: pass
        try:
            dev.write(EP_OUT, usb_pkt, timeout=500)
            data = dev.read(EP_IN, 512, timeout=500)
            midi = usb_to_midi(data)
            status = midi[9] if len(midi) > 9 else -1
            if status == 0:
                print(f"  b7=0x{mode_in_b7:02X} -> SUCCESS!")
                print(f"    RX: {hex_string(list(midi))}")
                break
            else:
                pass  # still error, don't print
        except usb.core.USBTimeoutError:
            print(f"  b7=0x{mode_in_b7:02X} -> TIMEOUT!")
            time.sleep(1)
            dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev2: print(f"    Device: {dev2.product}")
            break
        except: pass
    else:
        print("  All error")

    # ========================================
    # Test 6: Maybe Field Kit uses IOKit's DeviceRequest (control transfer)
    # to send the MIDI data, not bulk at all.
    # Try sending the SysEx as data in a vendor control transfer.
    # ========================================
    print("\n=== Test 6: SysEx via vendor control transfer ===")
    sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x60, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7])
    usb_midi_pkt = sysex_to_usb(sysex)

    for bmReqType in [0x21, 0x41]:  # class/vendor, interface
        for bReq in [0x01, 0x09]:
            try:
                ret = dev.ctrl_transfer(bmReqType, bReq, 0, MIDI_INTF, usb_midi_pkt, timeout=500)
                print(f"  type=0x{bmReqType:02X} req=0x{bReq:02X} -> sent {ret} bytes")
                # Try reading response
                try:
                    data = dev.read(EP_IN, 512, timeout=1000)
                    midi = usb_to_midi(data)
                    print(f"    Response: {hex_string(list(midi))}")
                except: pass
            except usb.core.USBError:
                pass

    print("  (control transfer test done)")

    # Cleanup
    try: usb.util.release_interface(dev, MIDI_INTF)
    except: pass

    print("\nDone.")


if __name__ == '__main__':
    main()
