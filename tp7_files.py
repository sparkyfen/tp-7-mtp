#!/usr/bin/env python3
"""
TP-7 MTP File Browser/Downloader
Lists and downloads files from TP-7 when in MTP mode.

Usage:
    sudo python3 tp7_files.py                    # List all files
    sudo python3 tp7_files.py --download ./out    # Download all recordings
"""

import usb.core
import usb.util
import struct
import sys
import os
import argparse

TE_VENDOR = 0x2367
TP7_PRODUCT = 0x0019
EP_OUT = 0x02
EP_IN = 0x81
EP_INT = 0x83


def mtp_command(dev, code, transaction_id, params=None):
    """Send MTP/PTP command and return (response_code, data)."""
    if params is None:
        params = []
    length = 12 + len(params) * 4
    pkt = struct.pack('<IHHI', length, 1, code, transaction_id)
    for p in params:
        pkt += struct.pack('<I', p)
    dev.write(EP_OUT, pkt)

    all_data = b''
    while True:
        try:
            raw = bytes(dev.read(EP_IN, 65536, timeout=5000))
            rlen, rtype, rcode, rtid = struct.unpack('<IHHI', raw[:12])

            if rtype == 2:  # Data phase
                all_data = raw[12:]
                while len(all_data) + 12 < rlen:
                    more = bytes(dev.read(EP_IN, 65536, timeout=5000))
                    all_data += more
                continue
            elif rtype == 3:  # Response
                return rcode, all_data
        except usb.core.USBTimeoutError:
            return None, all_data


def mtp_get_string(data, offset):
    """Read a PTP string from data at offset. Returns (string, bytes_consumed)."""
    if offset >= len(data):
        return "", 0
    num_chars = data[offset]
    if num_chars == 0:
        return "", 1
    try:
        s = data[offset + 1:offset + 1 + num_chars * 2].decode('utf-16-le').rstrip('\x00')
    except:
        s = "?"
    return s, 1 + num_chars * 2


def list_files(dev, storage_id, parent_handle=0xFFFFFFFF, prefix="", tid_counter=None):
    """Recursively list files in MTP storage."""
    if tid_counter is None:
        tid_counter = [10]

    tid_counter[0] += 1
    code, data = mtp_command(dev, 0x1007, tid_counter[0],
                             [storage_id, 0x00000000, parent_handle])

    if not data or len(data) < 4:
        return []

    n = struct.unpack('<I', data[:4])[0]
    handles = [struct.unpack('<I', data[4 + i * 4:8 + i * 4])[0] for i in range(n)]

    files = []
    for h in handles:
        tid_counter[0] += 1
        code, info = mtp_command(dev, 0x1008, tid_counter[0], [h])
        if not info or len(info) < 53:
            continue

        obj_format = struct.unpack('<H', info[4:6])[0]
        obj_size = struct.unpack('<I', info[8:12])[0]

        # Filename is at offset 52
        filename, _ = mtp_get_string(info, 52)
        is_dir = (obj_format == 0x3001)
        path = prefix + "/" + filename

        files.append({
            'handle': h,
            'name': filename,
            'path': path,
            'size': obj_size,
            'is_dir': is_dir,
            'format': obj_format,
        })

        if is_dir:
            children = list_files(dev, storage_id, h, path, tid_counter)
            files.extend(children)

    return files


def download_file(dev, handle, size, dest_path, tid):
    """Download a file from MTP device."""
    code, data = mtp_command(dev, 0x1009, tid, [handle])
    if data:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        with open(dest_path, 'wb') as f:
            f.write(data)
        return True
    return False


def main():
    parser = argparse.ArgumentParser(description="TP-7 MTP File Browser")
    parser.add_argument("--download", metavar="DIR", help="Download all recordings to DIR")
    parser.add_argument("--list", action="store_true", default=True, help="List files")
    args = parser.parse_args()

    dev = usb.core.find(idVendor=TE_VENDOR, idProduct=TP7_PRODUCT)
    if not dev:
        print("TP-7 not found!")
        sys.exit(1)

    if "MTP" not in (dev.product or ""):
        print(f"TP-7 is in {dev.product} mode, not MTP. Run tp7_switch_mtp first.")
        sys.exit(1)

    print(f"Connected to {dev.product} (serial: {dev.serial_number})\n")

    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except:
        pass

    dev.set_configuration()
    usb.util.claim_interface(dev, 0)

    # Open session
    tid = 1
    code, _ = mtp_command(dev, 0x1002, tid, [1])
    if code == 0x2001:  # Session already open
        pass
    elif code != 0x2001 and code != 0x2002:
        print(f"OpenSession failed: 0x{code:04X}" if code else "OpenSession timeout")

    # Get storage IDs
    tid += 1
    code, data = mtp_command(dev, 0x1004, tid)
    if not data or len(data) < 4:
        print("No storage found")
        sys.exit(1)

    n_storages = struct.unpack('<I', data[:4])[0]
    storage_ids = [struct.unpack('<I', data[4 + i * 4:8 + i * 4])[0] for i in range(n_storages)]
    print(f"Storage(s): {', '.join(f'0x{s:08X}' for s in storage_ids)}\n")

    # List files
    all_files = []
    for sid in storage_ids:
        files = list_files(dev, sid, tid_counter=[tid])
        all_files.extend(files)

    print(f"{'Type':5s} {'Size':>10s}  Path")
    print("-" * 50)
    for f in all_files:
        kind = "DIR" if f['is_dir'] else "FILE"
        size = "" if f['is_dir'] else f"{f['size']:,}"
        print(f"{kind:5s} {size:>10s}  {f['path']}")

    print(f"\nTotal: {len(all_files)} items")

    # Download
    if args.download:
        recordings = [f for f in all_files if not f['is_dir'] and '/recordings' in f['path']]
        if not recordings:
            print("\nNo recordings to download.")
            return

        print(f"\nDownloading {len(recordings)} recording(s) to {args.download}/...")
        dl_tid = 100
        for f in recordings:
            dest = os.path.join(args.download, f['name'])
            print(f"  {f['name']} ({f['size']:,} bytes)...", end=" ", flush=True)
            dl_tid += 1
            if download_file(dev, f['handle'], f['size'], dest, dl_tid):
                print("OK")
            else:
                print("FAILED")

    usb.util.release_interface(dev, 0)


if __name__ == '__main__':
    main()
