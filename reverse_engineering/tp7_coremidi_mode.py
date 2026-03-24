#!/usr/bin/env python3
"""
TP-7 Mode Switch via CoreMIDI (mido).
Field Kit uses IOKit primary, CoreMIDI fallback.
Maybe the TP-7 only accepts mode switch from CoreMIDI?
"""

import mido
import sys
import time
from datetime import datetime

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def main():
    inputs = mido.get_input_names()
    outputs = mido.get_output_names()

    tp7_in = [n for n in inputs if 'TP-7' in n]
    tp7_out = [n for n in outputs if 'TP-7' in n]

    if not tp7_in or not tp7_out:
        print(f"TP-7 not found. In: {inputs}, Out: {outputs}")
        sys.exit(1)

    port_in = mido.open_input(tp7_in[0])
    port_out = mido.open_output(tp7_out[0])
    print(f"Connected: in={tp7_in[0]}, out={tp7_out[0]}")

    def send_and_wait(sysex_data, label, timeout=2.0):
        """Send SysEx via CoreMIDI, wait for response."""
        # mido sysex data doesn't include F0/F7
        msg = mido.Message('sysex', data=sysex_data)

        # Drain pending
        for _ in port_in.iter_pending():
            pass

        print(f"\n  [{label}] TX: F0 {hex_string(sysex_data)} F7")
        port_out.send(msg)

        start = time.time()
        while time.time() - start < timeout:
            for resp in port_in.iter_pending():
                if resp.type == 'sysex':
                    full = [0xF0] + list(resp.data) + [0xF7]
                    print(f"  [{label}] RX: {hex_string(full)}")
                    d = list(resp.data)
                    if len(d) > 6:
                        status = d[6] if len(d) > 6 else '?'
                        cmd = d[5] if len(d) > 5 else '?'
                        print(f"  [{label}] cmd={cmd} status={status}")
                    return resp
            time.sleep(0.01)
        print(f"  [{label}] (no response)")
        return None

    # TE header for requests: 00 20 76 19 40 40 [reqId] [cmd] [payload]
    TE = [0x00, 0x20, 0x76]

    # Test 1: Greet via CoreMIDI
    print("\n=== Test 1: Greet via CoreMIDI ===")
    sysex = TE + [0x19, 0x40, 0x40, 0x01, 0x01]
    send_and_wait(sysex, "greet")
    time.sleep(0.5)

    # Test 2: Echo via CoreMIDI
    print("\n=== Test 2: Echo via CoreMIDI ===")
    sysex = TE + [0x19, 0x40, 0x40, 0x02, 0x02]
    send_and_wait(sysex, "echo")
    time.sleep(0.5)

    # Test 3: Mode 'mtp' via CoreMIDI
    print("\n=== Test 3: Mode via CoreMIDI (with 'mtp' payload) ===")
    # 7-bit encode "mtp"
    payload = [0x00, 0x6D, 0x74, 0x70]  # MSB carrier + mtp
    sysex = TE + [0x19, 0x40, 0x40, 0x03, 0x04] + payload
    send_and_wait(sysex, "mode-mtp")
    time.sleep(0.5)

    # Test 4: Mode without payload
    print("\n=== Test 4: Mode via CoreMIDI (no payload) ===")
    sysex = TE + [0x19, 0x40, 0x40, 0x04, 0x04]
    send_and_wait(sysex, "mode-bare")
    time.sleep(0.5)

    # Test 5: Try different b5 values (maybe CoreMIDI needs different flags)
    print("\n=== Test 5: Mode with different b5 values via CoreMIDI ===")
    for b5 in [0x00, 0x01, 0x20, 0x21, 0x40, 0x41, 0x60, 0x61]:
        sysex = TE + [0x19, b5, 0x40, 0x05, 0x04]
        resp = send_and_wait(sysex, f"b5=0x{b5:02X}", timeout=0.5)
        if resp:
            d = list(resp.data)
            status = d[6] if len(d) > 6 else -1
            if status == 0:
                print(f"  *** SUCCESS with b5=0x{b5:02X}! ***")
                break
        time.sleep(0.1)

    port_in.close()
    port_out.close()
    print("\nDone.")

if __name__ == '__main__':
    main()
