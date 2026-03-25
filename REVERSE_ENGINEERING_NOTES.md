# Field Kit Reverse Engineering Notes

> **Goal:** Replicate the Teenage Engineering "Field Kit" macOS app's ability to switch the TP-7 into MTP mode and copy files — on Linux.

## App Overview

- **App:** `/Applications/FieldKit.app` (v1.1.13, build 118)
- **Bundle ID:** `engineering.teenage.fieldkit`
- **Binary:** Native Mach-O universal (x86_64 + arm64), written in Swift
- **Entitlements:** USB access (`com.apple.security.device.usb`), network client+server (for local NFS)

## TP-7 USB Identity

### MIDI Mode (default)
| Field | Value |
|-------|-------|
| Vendor ID | `0x2367` (9063) — "teenage engineering" |
| Product ID | `0x0019` (25) |
| Product Name | `TP-7` |
| Speed | USB 2.0 High Speed (480 Mb/s) |
| Configurations | **3** (all identical layout: Audio + MIDI) |
| Interface 0 | Audio Control (Class 1, SubClass 1) |
| Interface 1 | Audio Streaming IN (Class 1, SubClass 2) |
| Interface 2 | Audio Streaming OUT (Class 1, SubClass 2) |
| Interface 3 | **MIDI Streaming** (Class 1, SubClass 3) |
| MIDI EP OUT | `0x02` (Bulk, 512 bytes) |
| MIDI EP IN | `0x81` (Bulk, 512 bytes) |
| MIDI Jack IDs | IN Embedded=0x15, IN External=0x16, OUT Embedded=0x17, OUT External=0x18 |

### MTP Mode (after switch)
| Field | Value |
|-------|-------|
| Product Name | `TP-7 MTP Device` |
| Configurations | **1** |
| Interface 0 | Vendor-specific (Class 255, SubClass 1, Protocol 1) — standard MTP |
| EP OUT | `0x02` (Bulk, 512 bytes) |
| EP IN | `0x81` (Bulk, 512 bytes) |
| EP INT IN | `0x83` (Interrupt, 16 bytes) |
| Storage | 1 storage (ID `0x00010001`) |
| Root dirs | `recordings/`, `library/` |

### MIDI Identity Response
Sending standard MIDI Identity Request (`F0 7E 7F 06 01 F7`) returns:
```
F0 7E 19 06 02 00 20 76 19 00 01 00 00 00 00 00 F7
       ^^          ^^^^^^^^ ^^    ^^
       ch=0x19     TE mfr   prod  fw_ver=0x0001
```

---

## SysEx Protocol (CONFIRMED)

### Request Format
```
F0 00 20 76 19 40 40 [reqId] [cmd] [7-bit-encoded-payload] F7
^  ^^^^^^^^ ^^ ^^ ^^  ^^      ^^
|  TE mfr   |  |  |   |       +-- Command byte
|           |  |  |   +---------- Request ID (any 7-bit value)
|           |  |  +-------------- 0x40 = required for requests
|           |  +----------------- 0x40 = required for requests
|           +-------------------- 0x19 = TP-7 product ID
+-------------------------------- SysEx start
```

### Response Format
```
F0 00 20 76 19 40 [b6] [b7] [cmd] [status] [7-bit-encoded-payload] F7
                       ^^    ^^     ^^       ^^
                       |     |      |        +-- 0=ok, 1=error, 2=cmdNotFound, 3=badRequest
                       |     |      +----------- Echoed command byte
                       |     +------------------ Varies (0x00 from our requests, different from Field Kit)
                       +------------------------ Varies (0x00 from our requests, 0x21 from Field Kit)
```

### Commands (CONFIRMED via probing)
| Byte | Command | Status from our requests | Notes |
|------|---------|------------------------|-------|
| `0x01` | greet | **0 (ok)** | Returns device info payload |
| `0x02` | echo | **0 (ok)** | Empty response |
| `0x03` | dfu | **3 (badRequest)** | Needs specific payload |
| `0x04` | mode | **1 (error)** | Recognized but ALWAYS rejected from us |
| `0x05`-`0x7F` | — | **2 (cmdNotFound)** | Not valid commands |

### 7-bit MIDI Encoding
Payloads use standard MIDI 7-bit encoding: every 8 bytes consist of 1 MSB carrier byte followed by 7 data bytes with bit 7 stripped. The MSB carrier's bit N holds bit 7 of data byte N.

### Greet Response Payload (decoded)
```
mode:normal;product:TP-7;sw_version:1.1.10;os_version:1.1.10;
serial:TPXXX00X;sku:TE025AXXXX;base_sku:TE025AXXXX
```

---

## The Mode Switch Problem

### What Works
- Greet command → **OK** (both raw USB and CoreMIDI)
- Echo command → **OK**
- MTP file access → **CONFIRMED WORKING** (standard PTP/MTP protocol)
- Field Kit can switch modes successfully

### What Doesn't Work
The mode command (`0x04`) returns `status=1 (error)` regardless of:
- Payload content (strings, numbers, empty, encoded, raw) — ALL tried
- Header byte variations (all 128 values of b6 brute-forced)
- Transport method (raw USB bulk via pyusb, CoreMIDI via mido)
- USB cable number (0-3)
- Interface claim state (claimed/unclaimed, all interfaces, MIDI only)
- USB configuration (1, 2, 3)
- USB control transfers (vendor-specific, class-specific)
- USB device reset after mode command
- Detaching all kernel drivers

### Critical Clue from macOS `log stream` Capture

Field Kit's actual flow (captured 2026-03-24):
```
00:01:52.250  USBDeviceMonitor: Start monitoring
00:01:52.253  USBProber: Has MIDI interface
00:01:52.253  USBDeviceManager: add(device: TPXXX00X), mode: 1
00:01:52.253  MIDIClient.send(request: greet, device: 34603008)
00:01:52.254  MIDIClient.send(request: greet, device: 34603008) exclusive usb access, trying Core MIDI
00:01:52.604  MIDIClient.send(request: greet, device: 34603008) finished with Core MIDI
00:01:52.604  add(device: 4309917556) greet os_version: <private>
00:01:57.050  updateModeChangePending: true
00:01:57.050  MIDIClient.send(request: mode, device: 34603008)
00:01:57.052  MIDIClient.send(request: mode, device: 34603008) exclusive usb access, trying Core MIDI
00:01:57.055  MIDIClient.send(request: mode, device: 34603008) finished with Core MIDI
00:01:57.055  Connected to MTP
00:01:57.358  deviceDisconnected (USB re-enumeration)
00:01:58.077  USBProber: Has MTP interface
00:01:58.077  add(device: TPXXX00X), mode: 0
00:01:58.083  NFSFileSystem: mount
00:01:58.092  MTPService: open(serialNumber: TPXXX00X) succeeded
00:01:58.112  NFSFileSystem: mounted 0
```

**Key findings:**
1. Field Kit tries IOKit first for exclusive USB access — **it FAILS**
2. Falls back to **CoreMIDI** (`MIDISendSysex`) — **this succeeds**
3. The `device: 34603008` = `0x02100000` = the USB **locationID**
4. Mode switch takes ~3ms via CoreMIDI
5. Device re-enumerates ~300ms after mode switch
6. The greet response's `b6=0x21, b7=varies` vs our `b6=0x00, b7=0x00` suggests Field Kit's CoreMIDI path produces different framing than our approach

### What's Different About Field Kit's CoreMIDI

Field Kit uses the **native CoreMIDI C API** (`MIDISendSysex`), which:
- Goes through the macOS MIDI server process
- Uses `MIDIObjectRef` handles tied to specific MIDI endpoints
- May add routing/framing that differs from raw USB bulk or python-rtmidi
- The `device: 34603008` (locationID) is used to find the correct MIDI entity

Our mido/python-rtmidi also uses CoreMIDI, but there may be subtle differences in:
- How the SysEx is framed for USB transmission
- Port/endpoint selection
- Timing or packet segmentation

### SOLVED: The Mode Switch Command

**Captured via lldb attached to Field Kit:**

```
Greet:  F0 00 20 76 19 40 60 [reqId] 01 F7
Mode:   F0 00 20 76 19 40 60 [reqId] 04 00 01 03 F7
```

The two things we were missing:
1. **`b6=0x60`** — the correct request flag byte (not 0x40 which only partially worked)
2. **Payload `00 01 03`** — the MTP mode identifier (7-bit encoded: MSB=0x00, data=[0x01, 0x03])

The payload likely means: target_mode=0x01 (MTP), variant=0x03 (USB config 3). This could never have been guessed — it required capturing the actual bytes from Field Kit via debugger.

---

## Architecture: How Field Kit Works

### Core Components (Swift classes)

| Class | Purpose |
|-------|---------|
| `USBProber` | Detect and identify USB devices |
| `USBDeviceMonitor` | Monitor connect/disconnect events |
| `USBDeviceManager` | Manage device lifecycle |
| `MIDIClient` | Send/receive MIDI SysEx (IOKit primary, CoreMIDI fallback) |
| `SysExContext` | SysEx message construction |
| `MTPService` | File operations via libmtp |
| `NFSFileSystem` / `NFSFileSystemManager` | Local NFS v3 server (KFS framework) |

### NFS Bridge — KFS Framework
Custom **userspace NFS v3 server** that:
- Binds to `127.0.0.1` on a local TCP port
- Translates NFS operations to libmtp calls
- macOS Finder mounts this as a network volume
- **Not needed on Linux** — use libmtp directly or FUSE mount

### Bundled Libraries
| Library | Purpose |
|---------|---------|
| `libmtp.dylib` | MTP protocol (open source) |
| `libusb.dylib` | Low-level USB (open source, used by libmtp) |
| `KFS.framework` | Userspace NFS v3 server |
| `Sentry.framework` | Crash reporting (ignore) |

---

## MTP File Access (CONFIRMED WORKING)

Standard PTP/MTP over USB works perfectly once in MTP mode:
```python
# Open session: MTP command 0x1002, session_id=1
# Get storage IDs: MTP command 0x1004 → [0x00010001]
# Get object handles: MTP command 0x1007
# Get object info: MTP command 0x1008
# Get file: MTP command 0x1009 (or LIBMTP_Get_File_To_File)
```

On Linux, once MTP mode is active:
```bash
sudo apt install jmtpfs
mkdir /mnt/tp7
jmtpfs /mnt/tp7
# Files accessible at /mnt/tp7/recordings/ and /mnt/tp7/library/
```

---

## Next Steps

### Immediate: Solve the Mode Switch
1. **Try native CoreMIDI C API** — Write a minimal C program using `MIDISendSysex` directly (not through python-rtmidi) to see if native CoreMIDI works where mido doesn't
2. **Disassemble with Ghidra** — Load the FieldKit binary and trace the SysExContext message construction to see the exact bytes for the mode command
3. **Capture raw USB packets** — Install a USB hardware analyzer or find a way to enable macOS kernel USB tracing with packet data (not just log messages)
4. **Compare CoreMIDI implementations** — Diff what `MIDISendSysex` vs python-rtmidi actually sends at the USB level

### Once Mode Switch Works on macOS
5. Port the working SysEx to Linux using ALSA MIDI or raw USB
6. Write the complete Linux tool (Python script ~100 lines)
7. Create udev rules for permissions
8. Test FUSE mount with jmtpfs

### Linux udev Rule
```bash
# /etc/udev/rules.d/69-teenage-engineering.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="2367", ATTR{idProduct}=="0019", MODE="0666", GROUP="plugdev"
```

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `REVERSE_ENGINEERING_NOTES.md` | This file |
| `midi_sniffer.py` | CoreMIDI SysEx capture tool (mido-based) |
| `tp7_probe.py` | First probe attempt via mido (didn't work — wrong header) |
| `tp7_usb_probe.py` | Raw USB bulk probe (found correct header `19 40 40`) |
| `tp7_usb_probe2.py` | Brute-force header scan (found `b5=0x40 b6=0x40` works) |
| `tp7_usb_probe3.py` | Confirmed greet/echo work, mode returns error |
| `tp7_mode_switch.py` | Exhaustive mode payload testing (all return error) |
| `tp7_config_switch.py` | USB config switch + full b6 brute force (all fail) |
| `tp7_final_probe.py` | Command scan, cable numbers, control transfers |
| `tp7_mode_reset.py` | Mode + USB reset (didn't trigger switch) |
| `tp7_coremidi_mode.py` | Mode via CoreMIDI/mido (still error) |
| `libusb_shim.c` | libusb interposition library |
| `libusb_wrapper.c` | Full libusb wrapper for traffic capture |
| `capture_usb.sh` | macOS USB log capture script |
| `sysex_capture.log` | Captured SysEx responses from MIDI sniffer |
| `FieldKit_local.app/` | Local copy of Field Kit (unsigned, for testing) |

## Other TE Devices

Field Kit supports multiple devices. Known/suspected product IDs:
- TP-7 → **`0x0019`** (confirmed)
- Others in binary: `0x001d`, `0x001c`, `0x0021` (likely OP-1 Field, TX-6, CM-15, etc.)

## References

- https://teenage.engineering/guides/tp-7
- https://teenage.engineering/guides/fieldkit
- libmtp: https://github.com/libmtp/libmtp
- libusb: https://github.com/libusb/libusb
- USB MIDI spec: https://www.usb.org/sites/default/files/midi10.pdf
