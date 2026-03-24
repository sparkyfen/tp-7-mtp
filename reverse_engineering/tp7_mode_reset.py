#!/usr/bin/env python3
"""
TP-7 Mode Switch - Send mode SysEx then trigger USB reset/re-enumerate.
Theory: the mode SysEx sets internal state, USB reset activates it.
"""

import usb.core
import usb.util
import sys
import time

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019
MIDI_INTF = 3
EP_OUT = 0x02
EP_IN = 0x81

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

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def send_sysex(dev, sysex):
    usb_pkt = sysex_to_usb(sysex)
    try:
        while True: dev.read(EP_IN, 512, timeout=50)
    except: pass
    dev.write(EP_OUT, usb_pkt, timeout=1000)
    try:
        data = dev.read(EP_IN, 512, timeout=1000)
        midi = usb_to_midi(data)
        status = midi[9] if len(midi) > 9 else -1
        return status, midi
    except usb.core.USBTimeoutError:
        return -2, None


def main():
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!"); sys.exit(1)
    print(f"Found: {dev.product} (configs={dev.bNumConfigurations})")

    # Detach kernel drivers from ALL interfaces
    for intf in range(4):
        try:
            if dev.is_kernel_driver_active(intf):
                dev.detach_kernel_driver(intf)
                print(f"  Detached kernel driver from interface {intf}")
        except: pass

    # Claim MIDI interface
    try:
        usb.util.claim_interface(dev, MIDI_INTF)
    except: pass

    # Step 1: Greet
    print("\n--- Step 1: Greet ---")
    greet = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x01, 0x01, 0xF7])
    status, resp = send_sysex(dev, greet)
    print(f"  Greet status: {status}")

    # Step 2: Send mode command (even though it returns "error")
    print("\n--- Step 2: Mode 'mtp' ---")
    mode_mtp = bytes([0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x02, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7])
    status, resp = send_sysex(dev, mode_mtp)
    print(f"  Mode status: {status}")

    # Release interface before reset
    try:
        usb.util.release_interface(dev, MIDI_INTF)
    except: pass

    # Step 3: USB device reset
    print("\n--- Step 3: USB device reset ---")
    try:
        dev.reset()
        print("  Reset sent!")
    except usb.core.USBError as e:
        print(f"  Reset error: {e}")

    # Wait for re-enumeration
    print("  Waiting for device...")
    time.sleep(3)

    dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if dev2:
        print(f"  Device: {dev2.product} (configs={dev2.bNumConfigurations})")
        if 'MTP' in (dev2.product or ''):
            print("  *** SUCCESS: TP-7 is in MTP mode! ***")
        else:
            print("  Still in MIDI mode. Trying more approaches...")

            # Approach B: Send mode, then do SET_CONFIGURATION to 0
            # (unconfigured state, may trigger firmware mode switch)
            print("\n--- Approach B: Mode + SET_CONFIGURATION(0) ---")
            try:
                if dev2.is_kernel_driver_active(MIDI_INTF):
                    dev2.detach_kernel_driver(MIDI_INTF)
                usb.util.claim_interface(dev2, MIDI_INTF)
            except: pass

            status, _ = send_sysex(dev2, mode_mtp)
            print(f"  Mode status: {status}")

            try: usb.util.release_interface(dev2, MIDI_INTF)
            except: pass

            # Set config to 0 (unconfigured)
            try:
                dev2.ctrl_transfer(0x00, 0x09, 0, 0, b'')
                print("  SET_CONFIGURATION(0) sent")
            except: print("  SET_CONFIGURATION(0) failed")

            time.sleep(3)
            dev3 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev3:
                print(f"  Device: {dev3.product}")
            else:
                print("  Device gone! Waiting...")
                time.sleep(3)
                dev3 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
                if dev3: print(f"  Came back as: {dev3.product}")

            # Approach C: Maybe mode command works WITHOUT claiming the interface
            # (like how Field Kit uses IOKit direct access)
            print("\n--- Approach C: Bulk write without claiming interface ---")
            dev4 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
            if dev4:
                # Detach kernel driver but don't claim
                for intf in range(4):
                    try:
                        if dev4.is_kernel_driver_active(intf):
                            dev4.detach_kernel_driver(intf)
                    except: pass

                dev4.set_configuration()

                # Direct bulk write
                mode_pkt = sysex_to_usb(mode_mtp)
                try:
                    dev4.write(EP_OUT, mode_pkt, timeout=1000)
                    print("  Sent mode command")
                    try:
                        data = dev4.read(EP_IN, 512, timeout=1000)
                        midi = usb_to_midi(data)
                        status = midi[9] if len(midi) > 9 else -1
                        print(f"  Status: {status}")
                    except: print("  No response")
                except usb.core.USBError as e:
                    print(f"  Error: {e}")

                # Now try re-enumerate via control transfer
                # USB_REQ_SET_FEATURE with USB_DEVICE_REMOTE_WAKEUP
                # or just a port reset
                print("\n  Trying port power cycle...")
                try:
                    dev4.reset()
                except: pass
                time.sleep(3)
                dev5 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
                if dev5:
                    print(f"  Device: {dev5.product}")
    else:
        print("  Device not found! Waiting longer...")
        time.sleep(5)
        dev2 = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
        if dev2:
            print(f"  Came back as: {dev2.product}")
            if 'MTP' in (dev2.product or ''):
                print("  *** SUCCESS! ***")
        else:
            print("  Still gone.")

    print("\nDone.")

if __name__ == '__main__':
    main()
