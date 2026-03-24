#!/usr/bin/env python3
"""
TP-7 Mode Switch - Try USB-level approaches:
1. SET_CONFIGURATION to switch between the 3 USB configs
2. Vendor-specific control transfers
3. SET_INTERFACE alt settings
"""

import usb.core
import usb.util
import sys
import time

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!")
        sys.exit(1)

    print(f"Product: {dev.product}")
    print(f"Configs: {dev.bNumConfigurations}")
    print(f"Active: {dev.get_active_configuration().bConfigurationValue}")

    # ========================================
    # Approach 1: Try vendor-specific control transfers
    # These go to the device directly, no interface claim needed
    # ========================================
    print("\n=== Approach 1: Vendor-specific control transfers ===")

    # Try host-to-device vendor requests that might trigger mode switch
    # bmRequestType: 0x40 = host-to-device, vendor, device
    for bRequest in range(0x10):
        for wValue in [0x0001, 0x0002, 0x0003, 0x0004]:
            try:
                ret = dev.ctrl_transfer(0x40, bRequest, wValue, 0, b'', timeout=500)
                print(f"  H2D bReq=0x{bRequest:02X} wVal=0x{wValue:04X} -> ret={ret}")
            except usb.core.USBError:
                pass
    print("  (vendor control scan done)")

    # Re-check if device changed
    time.sleep(1)
    dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if dev2:
        print(f"  Still here: {dev2.product}, configs={dev2.bNumConfigurations}")
    else:
        print("  Device disappeared! May have re-enumerated.")
        return

    # ========================================
    # Approach 2: Switch USB configuration
    # ========================================
    print("\n=== Approach 2: USB SET_CONFIGURATION ===")
    for config_val in [2, 3]:
        print(f"\n  Trying config {config_val}...")
        try:
            dev.set_configuration(config_val)
            time.sleep(1)
            active = dev.get_active_configuration()
            print(f"  Switched to config {active.bConfigurationValue}")
            # Check if device changed
            dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev2:
                print(f"  Product: {dev2.product}, configs={dev2.bNumConfigurations}")
            else:
                print("  Device disappeared! May have re-enumerated to MTP!")
                return
        except usb.core.USBError as e:
            print(f"  Error: {e}")

    # Switch back to config 1
    try:
        dev.set_configuration(1)
        print("\n  Switched back to config 1")
    except:
        pass

    # ========================================
    # Approach 3: Maybe the mode switch is via a specific
    # USB control transfer to the MIDI interface
    # ========================================
    print("\n=== Approach 3: Class-specific requests to MIDI interface ===")
    MIDI_INTF = 3

    try:
        if dev.is_kernel_driver_active(MIDI_INTF):
            dev.detach_kernel_driver(MIDI_INTF)
    except: pass

    # Audio class requests: SET_CUR=0x01, GET_CUR=0x81
    for bRequest in [0x01, 0x02, 0x03, 0x04, 0x05]:
        for wValue in [0x0000, 0x0001, 0x0100, 0x0200]:
            try:
                # Class request, interface recipient
                ret = dev.ctrl_transfer(0x21, bRequest, wValue, MIDI_INTF, b'\x01', timeout=500)
                print(f"  CLASS H2D bReq=0x{bRequest:02X} wVal=0x{wValue:04X} -> ret={ret}")
            except usb.core.USBError:
                pass

    print("  (class request scan done)")

    # ========================================
    # Approach 4: Send mode SysEx but try different byte 6 values
    # Our b6=0x40 works for greet but fails for mode.
    # Maybe mode needs a different b6.
    # Let's try ALL b6 values from 0x00 to 0x7F with mode command.
    # ========================================
    print("\n=== Approach 4: Brute force b6 for mode command ===")

    try:
        usb.util.claim_interface(dev, MIDI_INTF)
    except: pass

    EP_OUT = 0x02
    EP_IN = 0x81

    # Drain
    try:
        while True: dev.read(EP_IN, 512, timeout=100)
    except: pass

    def sysex_to_usb(sysex):
        pkts = []
        data = list(sysex)
        i = 0
        while i < len(data):
            rem = len(data) - i
            if rem >= 3:
                cin = 0x07 if data[i+2] == 0xF7 else 0x04
                pkts.extend([cin, data[i], data[i+1], data[i+2]])
                i += 3
            elif rem == 2:
                pkts.extend([0x06, data[i], data[i+1], 0x00])
                i += 2
            elif rem == 1:
                pkts.extend([0x05, data[i], 0x00, 0x00])
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

    found = False
    for b6 in range(0x00, 0x80):
        # Mode command = 0x04, with 7-bit encoded "mtp" payload
        sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, b6, 0x10, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7])
        usb_pkt = sysex_to_usb(sysex)

        try:
            dev.write(EP_OUT, usb_pkt, timeout=500)
        except: continue

        try:
            data = dev.read(EP_IN, 512, timeout=300)
            midi = usb_to_midi(data)
            status = midi[9] if len(midi) > 9 else -1
            if status == 0:
                print(f"  b6=0x{b6:02X} -> SUCCESS! status=0")
                print(f"    TX: {hex_string(list(sysex))}")
                print(f"    RX: {hex_string(list(midi))}")
                found = True
                break
            elif status != 1:
                print(f"  b6=0x{b6:02X} -> status={status}")
        except usb.core.USBTimeoutError:
            # No response - might mean the device switched!
            time.sleep(0.5)
            dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev2 and dev2.product and 'MTP' in dev2.product:
                print(f"  b6=0x{b6:02X} -> DEVICE RE-ENUMERATED AS MTP!")
                found = True
                break
            elif not dev2:
                print(f"  b6=0x{b6:02X} -> DEVICE GONE (re-enumerating?)")
                time.sleep(2)
                dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
                if dev2:
                    print(f"    Came back as: {dev2.product}")
                found = True
                break
        except usb.core.USBError:
            pass

        if b6 % 16 == 15:
            sys.stdout.write(f"  ...tried 0x00-0x{b6:02X}, all error\n")
            sys.stdout.flush()

    if not found:
        # Also try without payload
        print("\n  Trying all b6 values with NO payload...")
        for b6 in range(0x00, 0x80):
            sysex = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, b6, 0x10, 0x04, 0xF7])
            usb_pkt = sysex_to_usb(sysex)
            try:
                dev.write(EP_OUT, usb_pkt, timeout=500)
            except: continue
            try:
                data = dev.read(EP_IN, 512, timeout=300)
                midi = usb_to_midi(data)
                status = midi[9] if len(midi) > 9 else -1
                if status == 0:
                    print(f"  b6=0x{b6:02X} (no payload) -> SUCCESS!")
                    print(f"    TX: {hex_string(list(sysex))}")
                    found = True
                    break
            except usb.core.USBTimeoutError:
                time.sleep(0.3)
                dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
                if not dev2 or (dev2.product and 'MTP' in dev2.product):
                    print(f"  b6=0x{b6:02X} (no payload) -> DEVICE SWITCHED!")
                    found = True
                    break
            except: pass

            if b6 % 16 == 15:
                sys.stdout.write(f"  ...tried 0x00-0x{b6:02X}, all error\n")
                sys.stdout.flush()

    try:
        usb.util.release_interface(dev, MIDI_INTF)
    except: pass

    print("\nDone.")


if __name__ == '__main__':
    main()
