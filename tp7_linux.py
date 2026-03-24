#!/usr/bin/env python3
"""
TP-7 Linux File Transfer Tool

Switches a Teenage Engineering TP-7 from MIDI mode to MTP mode
and optionally mounts it for file access.

Requirements:
    sudo apt install python3-usb libmtp-dev jmtpfs
    pip3 install pyusb

Usage:
    sudo python3 tp7_linux.py [--mount /mnt/tp7] [--copy-to ./recordings]
    sudo python3 tp7_linux.py --disconnect   # Switch back to MIDI mode
"""

import usb.core
import usb.util
import struct
import sys
import time
import argparse
import subprocess
import os

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019
MIDI_INTERFACE = 3
EP_OUT = 0x02
EP_IN = 0x81

# TE SysEx protocol constants
TE_MFR = [0x00, 0x20, 0x76]
TP7_PRODUCT_ID = 0x19
REQUEST_FLAG = 0x60
DEVICE_CONSTANT = 0x40

CMD_GREET = 0x01
CMD_MODE = 0x04

# The mode switch payload: switches TP-7 to MTP mode
MTP_MODE_PAYLOAD = [0x00, 0x01, 0x03]


def sysex_to_usb_midi(sysex_bytes):
    """Convert SysEx message to USB MIDI class packets (4-byte framing)."""
    packets = []
    data = list(sysex_bytes)
    i = 0
    while i < len(data):
        remaining = len(data) - i
        if remaining >= 3:
            cin = 0x07 if data[i + 2] == 0xF7 else 0x04
            packets.extend([cin, data[i], data[i + 1], data[i + 2]])
            i += 3
        elif remaining == 2:
            packets.extend([0x06, data[i], data[i + 1], 0x00])
            i += 2
        elif remaining == 1:
            packets.extend([0x05, data[i], 0x00, 0x00])
            i += 1
    return bytes(packets)


def usb_midi_to_sysex(usb_data):
    """Parse USB MIDI class packets back to raw MIDI bytes."""
    midi = []
    for i in range(0, len(usb_data), 4):
        if i + 3 >= len(usb_data):
            break
        cin = usb_data[i] & 0x0F
        if cin == 0x04:
            midi.extend([usb_data[i + 1], usb_data[i + 2], usb_data[i + 3]])
        elif cin == 0x07:
            midi.extend([usb_data[i + 1], usb_data[i + 2], usb_data[i + 3]])
        elif cin == 0x06:
            midi.extend([usb_data[i + 1], usb_data[i + 2]])
        elif cin == 0x05:
            midi.append(usb_data[i + 1])
    return bytes(midi)


def build_sysex(command, request_id, payload=None):
    """Build a TE SysEx request message."""
    msg = [0xF0] + TE_MFR + [TP7_PRODUCT_ID, DEVICE_CONSTANT, REQUEST_FLAG, request_id, command]
    if payload:
        msg.extend(payload)
    msg.append(0xF7)
    return bytes(msg)


def send_sysex(dev, sysex, timeout=3000):
    """Send SysEx over USB bulk and return (status, response_bytes)."""
    usb_pkt = sysex_to_usb_midi(sysex)

    # Drain any pending data
    try:
        while True:
            dev.read(EP_IN, 512, timeout=50)
    except:
        pass

    dev.write(EP_OUT, usb_pkt, timeout=timeout)

    # Read response
    all_data = bytearray()
    start = time.time()
    while time.time() - start < (timeout / 1000.0):
        try:
            data = dev.read(EP_IN, 512, timeout=1000)
            if data:
                all_data.extend(data)
                midi = usb_midi_to_sysex(all_data)
                if midi and midi[-1] == 0xF7:
                    status = midi[9] if len(midi) > 9 else -1
                    return status, midi
        except usb.core.USBTimeoutError:
            break
        except usb.core.USBError:
            break

    return -2, None


def find_tp7():
    """Find TP-7 on USB bus."""
    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        return None, None

    product = dev.product or ""
    if "MTP" in product:
        return dev, "mtp"
    else:
        return dev, "midi"


def switch_to_mtp(dev):
    """Switch TP-7 from MIDI mode to MTP mode."""
    # Detach kernel driver from MIDI interface
    try:
        if dev.is_kernel_driver_active(MIDI_INTERFACE):
            dev.detach_kernel_driver(MIDI_INTERFACE)
    except (usb.core.USBError, NotImplementedError):
        pass

    # Claim the MIDI interface
    usb.util.claim_interface(dev, MIDI_INTERFACE)

    try:
        # Step 1: Greet
        print("Sending greet...")
        greet = build_sysex(CMD_GREET, 0x01)
        status, resp = send_sysex(dev, greet)
        if status != 0:
            print(f"Greet failed (status={status})")
            return False

        # Decode greet response payload
        if resp and len(resp) > 10:
            # 7-bit decode payload
            raw = list(resp[10:-1]) if resp[-1] == 0xF7 else list(resp[10:])
            decoded = []
            i = 0
            while i < len(raw):
                msb = raw[i]
                i += 1
                for j in range(7):
                    if i >= len(raw):
                        break
                    b = raw[i]
                    if msb & (1 << j):
                        b |= 0x80
                    decoded.append(b)
                    i += 1
            info = ''.join(chr(b) for b in decoded if 32 <= b < 127)
            print(f"Device info: {info}")

        time.sleep(0.3)

        # Step 2: Mode switch to MTP
        print("Switching to MTP mode...")
        mode = build_sysex(CMD_MODE, 0x02, MTP_MODE_PAYLOAD)
        status, resp = send_sysex(dev, mode)

        if status == 0:
            print("Mode switch accepted!")
            return True
        elif status == -2:
            print("Device re-enumerating (mode switch likely succeeded)...")
            return True
        else:
            print(f"Mode switch failed (status={status})")
            return False
    finally:
        try:
            usb.util.release_interface(dev, MIDI_INTERFACE)
        except:
            pass


def switch_to_midi(dev):
    """Switch TP-7 from MTP mode back to MIDI mode."""
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (usb.core.USBError, NotImplementedError):
        pass

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)

    EP_OUT_MTP = 0x02
    EP_IN_MTP = 0x81

    def mtp_cmd(code, tid, params=None):
        if params is None:
            params = []
        length = 12 + len(params) * 4
        pkt = struct.pack('<IHHI', length, 1, code, tid)
        for p in params:
            pkt += struct.pack('<I', p)
        dev.write(EP_OUT_MTP, pkt)
        try:
            raw = bytes(dev.read(EP_IN_MTP, 512, timeout=3000))
            rlen, rtype, rcode, rtid = struct.unpack('<IHHI', raw[:12])
            if rtype == 2:  # data phase, read response after
                raw2 = bytes(dev.read(EP_IN_MTP, 512, timeout=3000))
                return struct.unpack('<IHHI', raw2[:12])[2]
            return rcode
        except:
            return None

    # Open session (required — reset only works after a proper session cycle)
    print("Opening MTP session...")
    mtp_cmd(0x1002, 1, [1])

    # Close MTP session
    print("Closing MTP session...")
    mtp_cmd(0x1003, 2)

    # Reset device (MTP command 0x0010) — returns to MIDI mode
    print("Resetting device...")
    mtp_cmd(0x0010, 3)

    try:
        usb.util.release_interface(dev, 0)
    except:
        pass

    return True


def wait_for_midi(timeout=10):
    """Wait for TP-7 to re-enumerate as MIDI device."""
    print(f"Waiting for MIDI device (up to {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        dev, mode = find_tp7()
        if dev and mode == "midi":
            print("TP-7 MIDI device found!")
            return True
        time.sleep(1)
    print("Timeout waiting for MIDI device.")
    return False


def wait_for_mtp(timeout=10):
    """Wait for TP-7 to re-enumerate as MTP device."""
    print(f"Waiting for MTP device (up to {timeout}s)...")
    start = time.time()
    while time.time() - start < timeout:
        dev, mode = find_tp7()
        if dev and mode == "mtp":
            print("TP-7 MTP device found!")
            return True
        time.sleep(1)
    print("Timeout waiting for MTP device.")
    return False


def find_gvfs_mount():
    """Find GVFS MTP mount for the TP-7, if any."""
    try:
        import glob
        uid = os.getuid()
        pattern = f"/run/user/{uid}/gvfs/mtp:host=*teenage_engineering*TP*7*"
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    except Exception:
        pass
    return None


def unmount_gvfs():
    """Unmount TP-7 GVFS/MTP mount if present."""
    gvfs_path = find_gvfs_mount()
    if not gvfs_path:
        return False
    try:
        host = gvfs_path.split("mtp:host=")[-1]
        uri = f"mtp://{host}/"
        result = subprocess.run(
            ["gio", "mount", "-u", uri],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print("Unmounted GVFS MTP mount.")
            return True
        else:
            print(f"GVFS unmount failed: {result.stderr.strip()}")
    except FileNotFoundError:
        pass  # gio not available
    return False


def mount_mtp(mountpoint):
    """Mount TP-7 MTP storage using jmtpfs."""
    os.makedirs(mountpoint, exist_ok=True)
    try:
        subprocess.run(["jmtpfs", mountpoint], check=True)
        print(f"Mounted at {mountpoint}")
        return True
    except FileNotFoundError:
        print("jmtpfs not found. Install with: sudo apt install jmtpfs")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Mount failed: {e}")
        return False


def copy_recordings(mountpoint, destination):
    """Copy recordings from mounted TP-7."""
    src = os.path.join(mountpoint, "recordings")
    if not os.path.isdir(src):
        print(f"No recordings directory at {src}")
        return

    os.makedirs(destination, exist_ok=True)
    files = os.listdir(src)
    print(f"Found {len(files)} items in recordings/")

    for f in files:
        src_path = os.path.join(src, f)
        dst_path = os.path.join(destination, f)
        if os.path.isfile(src_path):
            print(f"  Copying {f}...")
            subprocess.run(["cp", src_path, dst_path])

    print("Done copying.")


def main():
    parser = argparse.ArgumentParser(description="TP-7 Linux File Transfer Tool")
    parser.add_argument("--mount", help="Mount point for MTP filesystem (requires jmtpfs)")
    parser.add_argument("--copy-to", help="Copy recordings to this directory")
    parser.add_argument("--switch-only", action="store_true", help="Only switch to MTP mode, don't mount")
    parser.add_argument("--disconnect", action="store_true", help="Switch back from MTP to MIDI mode")
    args = parser.parse_args()

    print("=== TP-7 Linux File Transfer Tool ===\n")

    # Find device
    dev, mode = find_tp7()
    if not dev:
        print("TP-7 not found! Make sure it's connected via USB.")
        sys.exit(1)

    print(f"Found TP-7 (serial: {dev.serial_number}, mode: {mode})")

    # Handle disconnect
    if args.disconnect:
        if mode != "mtp":
            print("Already in MIDI mode, nothing to do.")
            return
        # Try GVFS unmount first — this often triggers the device to
        # switch back to MIDI mode on its own
        if unmount_gvfs():
            time.sleep(2)
            dev2, mode2 = find_tp7()
            if mode2 == "midi" or not dev2:
                print("TP-7 is back in MIDI mode.")
                return
            print("Device still in MTP mode, sending USB reset...")
        if switch_to_midi(dev):
            time.sleep(2)
            wait_for_midi()
            print("TP-7 is back in MIDI mode.")
        else:
            print("Disconnect failed.")
        return

    if mode == "mtp":
        print("Already in MTP mode!")
    else:
        # Switch to MTP
        if not switch_to_mtp(dev):
            print("Failed to switch to MTP mode.")
            sys.exit(1)

        # Wait for re-enumeration
        time.sleep(2)
        if not wait_for_mtp():
            sys.exit(1)

    if args.switch_only:
        print("\nTP-7 is now in MTP mode.")
        print("Use 'jmtpfs /mnt/tp7' to mount, or any MTP client to access files.")
        return

    # Check if GVFS already mounted the device
    gvfs_path = find_gvfs_mount()
    if gvfs_path:
        # Find the storage subdirectory (e.g. "TP-7 MTP Device")
        try:
            subdirs = os.listdir(gvfs_path)
            if subdirs:
                mountpoint = os.path.join(gvfs_path, subdirs[0])
            else:
                mountpoint = gvfs_path
        except OSError:
            mountpoint = gvfs_path
        print(f"\nTP-7 already mounted by GVFS at: {mountpoint}")
        if args.copy_to:
            copy_recordings(mountpoint, args.copy_to)
        else:
            print(f"  Recordings: {mountpoint}/recordings/")
            print(f"  Library:    {mountpoint}/library/")
            print(f"\nRun 'gio mount -u mtp://<host>/' or use --disconnect to unmount.")
        return

    # Mount via jmtpfs
    mountpoint = args.mount or "/tmp/tp7_mtp"
    if mount_mtp(mountpoint):
        if args.copy_to:
            copy_recordings(mountpoint, args.copy_to)
        else:
            print(f"\nTP-7 mounted at: {mountpoint}")
            print(f"  Recordings: {mountpoint}/recordings/")
            print(f"  Library:    {mountpoint}/library/")
            print("\nRun 'fusermount -u " + mountpoint + "' to unmount.")


if __name__ == "__main__":
    main()
