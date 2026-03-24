#!/bin/bash
# Capture Field Kit's USB MIDI traffic using lldb.
# This attaches to FieldKit and sets breakpoints on IOKit USB write functions.
# Usage:
#   1. Open Field Kit normally
#   2. Run: sudo bash capture_fieldkit.sh
#   3. Click MTP mode in Field Kit
#   4. The script will log the USB data being sent

FIELDKIT_PID=$(pgrep -x FieldKit)
if [ -z "$FIELDKIT_PID" ]; then
    echo "Field Kit is not running. Please open it first."
    exit 1
fi

echo "Found FieldKit PID: $FIELDKIT_PID"
echo "Attaching lldb... After attaching, click MTP in Field Kit."
echo ""

# Create lldb commands file
cat > /tmp/lldb_capture.txt << 'LLDBEOF'
# Break on IOKit WritePipe (bulk transfer)
# IOUSBInterfaceInterface methods are called through function pointers,
# but we can break on the actual implementation in IOKit

# Break on libusb bulk transfer (in case it uses that)
breakpoint set -n libusb_bulk_transfer
breakpoint set -n libusb_control_transfer

# Break on MIDISendSysex
breakpoint set -n MIDISendSysex

# Break on IOKit pipe write functions
# These are the actual USB write functions
breakpoint set -r WritePipe
breakpoint set -r DeviceRequest

# When we hit a breakpoint, dump relevant registers and memory
breakpoint command add 1 -o "register read" -o "memory read --size 1 --count 64 $rsi" -o "continue"
breakpoint command add 2 -o "register read" -o "memory read --size 1 --count 64 $rsi" -o "continue"
breakpoint command add 3 -o "register read" -o "bt 5" -o "continue"

continue
LLDBEOF

sudo lldb -p "$FIELDKIT_PID" -s /tmp/lldb_capture.txt
