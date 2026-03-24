# TP-7 Linux File Transfer

Transfer recordings from a [Teenage Engineering TP-7](https://teenage.engineering/products/tp-7) tape recorder on Linux (and macOS) — without the official Field Kit app.

The TP-7 connects via USB as a MIDI/Audio device. To access files, it must be switched to MTP mode using a proprietary MIDI SysEx command. This tool handles the mode switch and file transfer.

## Quick Start

### Linux (Tray App)

```bash
# Install dependencies
sudo apt install python3-pip libusb-1.0-0-dev jmtpfs python3-gi \
    gir1.2-ayatanaappindicator3-0.1 python3-pyudev

# Set up venv with system packages (needed for GTK bindings)
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pyusb

# Set up udev rules (one-time, for non-root USB access)
sudo cp 69-teenage-engineering.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules

# Launch the system tray helper
.venv/bin/python3 tp7_tray.py &
```

The tray icon shows device status — click to connect (switch to MTP) or disconnect. On GNOME/MATE desktops, GVFS auto-mounts the TP-7 and the tray offers an "Open Files" option.

### Linux (CLI)

```bash
# Switch to MTP and mount
sudo python3 tp7_linux.py --mount /mnt/tp7

# Copy recordings
cp /mnt/tp7/recordings/*.wav ~/Music/

# Unmount when done
fusermount -u /mnt/tp7
```

### macOS

```bash
pip3 install pyusb

# Switch to MTP and list files
sudo python3 tp7_files.py

# Download all recordings
sudo python3 tp7_files.py --download ~/Desktop/tp7_recordings
```

Or use the native CoreMIDI tool (no dependencies):
```bash
# Build
clang -o tp7_switch_mtp tp7_switch_mtp.c -framework CoreMIDI -framework CoreFoundation

# Switch to MTP mode
./tp7_switch_mtp
```

## How It Works

1. **Detect** the TP-7 on USB (Vendor `0x2367`, Product `0x0019`)
2. **Send SysEx greet** to the MIDI interface:
   ```
   F0 00 20 76 19 40 60 [id] 01 F7
   ```
3. **Send SysEx mode switch** to enter MTP mode:
   ```
   F0 00 20 76 19 40 60 [id] 04 00 01 03 F7
   ```
4. Wait for USB re-enumeration (~1-2 seconds)
5. **Access files** via standard MTP protocol

## Files

| File | Description |
|------|-------------|
| `tp7_tray.py` | Linux system tray connect/disconnect helper |
| `tp7_linux.py` | Linux CLI tool (switch + mount + copy) |
| `tp7_files.py` | Cross-platform MTP file browser/downloader |
| `tp7_switch_mtp.c` | macOS native CoreMIDI mode switch |
| `69-teenage-engineering.rules` | Linux udev rules for USB permissions |
| `REVERSE_ENGINEERING_NOTES.md` | Detailed protocol documentation |

## SysEx Protocol

The TP-7 uses Teenage Engineering's proprietary MIDI SysEx protocol:

```
Request:  F0 00 20 76 19 40 60 [reqId] [cmd] [payload] F7
Response: F0 00 20 76 19 40 [b6] [reqId] [cmd] [status] [payload] F7

Commands: 0x01=greet, 0x02=echo, 0x03=dfu, 0x04=mode
Status:   0x00=ok, 0x01=error, 0x02=cmdNotFound, 0x03=badRequest
```

| Byte | Meaning |
|------|---------|
| `00 20 76` | TE MIDI manufacturer ID |
| `19` | TP-7 product ID |
| `40` | Device constant |
| `60` | Request flag (responses use `20` + lower bits) |
| `04` | Mode command |
| `00 01 03` | MTP mode payload |

## USB Device Info

| Mode | Product Name | Configs | Key Interface |
|------|-------------|---------|---------------|
| MIDI (default) | `TP-7` | 3 | Interface 3: MIDI (Bulk EP 0x02/0x81) |
| MTP | `TP-7 MTP Device` | 1 | Interface 0: Vendor (Bulk EP 0x02/0x81) |

## Requirements

- Python 3.6+
- `pyusb` (`pip3 install pyusb`)
- Linux: `libusb-1.0`, `jmtpfs` (for FUSE mount)
- Linux (tray app): `python3-gi`, `gir1.2-ayatanaappindicator3-0.1`, `python3-pyudev`
- macOS: Xcode Command Line Tools (for C tool)

## License

This is a reverse-engineering project for interoperability purposes. Use at your own risk.
