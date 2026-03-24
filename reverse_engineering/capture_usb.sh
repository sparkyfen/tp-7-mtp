#!/bin/bash
# Capture USB traffic for the TP-7 using macOS kernel tracing.
#
# Instructions:
#   1. Run this script with sudo
#   2. Open Field Kit and switch to MTP mode
#   3. Press Ctrl+C to stop capture
#   4. The log will be saved to /tmp/usb_trace.log

echo "=== TP-7 USB Traffic Capture ==="
echo "Starting USB trace. Now open Field Kit and switch to MTP mode."
echo "Press Ctrl+C when done."
echo ""

# Enable debug logging for USB subsystem
log config --mode "level:debug" --subsystem com.apple.iokit.IOUSBHostFamily 2>/dev/null
log config --mode "level:debug" --subsystem com.apple.usb 2>/dev/null

# Stream logs, filtering for our device (vendor 2367 or "TP-7" or bulk transfers)
log stream --level debug \
    --predicate 'subsystem == "com.apple.iokit.IOUSBHostFamily" OR subsystem == "com.apple.usb" OR (process == "FieldKit" AND category != "default")' \
    2>&1 | tee /tmp/usb_trace.log
