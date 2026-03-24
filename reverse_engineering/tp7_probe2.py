#!/usr/bin/env python3
"""
TP-7 SysEx Probe v2 - Try various header formats.
"""

import mido
import sys
import time
from datetime import datetime

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def send_and_receive(port_in, port_out, sysex_data, label, timeout=2.0):
    msg = mido.Message('sysex', data=sysex_data)

    for _ in port_in.iter_pending():
        pass

    full = [0xF0] + list(sysex_data) + [0xF7]
    print(f"\n  [{label}] SEND: {hex_string(full)}")
    sys.stdout.flush()

    port_out.send(msg)

    start = time.time()
    while time.time() - start < timeout:
        for resp in port_in.iter_pending():
            if resp.type == 'sysex':
                full_recv = [0xF0] + list(resp.data) + [0xF7]
                print(f"  [{label}] RECV: {hex_string(full_recv)}")
                # Decode payload
                d = list(resp.data)
                if len(d) > 9:
                    raw = d[9:]
                    decoded = []
                    i = 0
                    while i < len(raw):
                        msb = raw[i]; i += 1
                        for j in range(7):
                            if i >= len(raw): break
                            b = raw[i]
                            if msb & (1 << j): b |= 0x80
                            decoded.append(b); i += 1
                    print(f"  [{label}] Decoded: {''.join(chr(b) if 32<=b<127 else '.' for b in decoded)}")
                sys.stdout.flush()
                return True
        time.sleep(0.01)
    print(f"  [{label}] (no response)")
    sys.stdout.flush()
    return False


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
    print(f"Connected to {tp7_in[0]}")

    # The response header is: 00 20 76 19 40 21 [reqId] [cmd] [status]
    # Let's try different request formats

    TE = [0x00, 0x20, 0x76]
    greet_cmd = 0x01

    print("\n=== Round 1: Vary the flags byte (pos 4, after product ID) ===")
    # Try with 0x40 (same as response), 0x00, 0x20, 0x60
    for flags in [0x00, 0x40, 0x20, 0x60, 0x80]:
        if flags > 0x7F:
            continue  # invalid for MIDI
        data = TE + [0x19, flags, 0x21, 0x10, greet_cmd]
        send_and_receive(port_in, port_out, data, f"flags=0x{flags:02X}")
        time.sleep(0.2)

    print("\n=== Round 2: Maybe product ID is not in header - try without it ===")
    # Maybe: [mfr] [cmd] [reqId] [payload]
    for variant_name, variant in [
        ("no-product", TE + [0x21, 0x10, greet_cmd]),
        ("no-product-no-21", TE + [0x10, greet_cmd]),
        ("just-cmd", TE + [greet_cmd]),
        ("product-cmd-only", TE + [0x19, greet_cmd]),
    ]:
        send_and_receive(port_in, port_out, variant, variant_name)
        time.sleep(0.2)

    print("\n=== Round 3: Maybe byte 6 (0x21) is not constant - try other values ===")
    for const in [0x00, 0x01, 0x10, 0x20, 0x21, 0x41, 0x61]:
        data = TE + [0x19, 0x00, const, 0x10, greet_cmd]
        send_and_receive(port_in, port_out, data, f"const=0x{const:02X}")
        time.sleep(0.2)

    print("\n=== Round 4: Maybe requests don't include status byte ===")
    # Response: [product=19] [flags=40] [const=21] [reqId] [cmd] [status] [payload]
    # Request might be: [product=19] [flags=00] [const=21] [reqId] [cmd] [payload]
    # But we tried that. Maybe the issue is the cmd values are wrong.
    # Let's try all single-byte commands 0x00-0x0F
    print("  Trying all commands 0x00-0x0F with header 19 00 21...")
    for cmd in range(0x10):
        data = TE + [0x19, 0x00, 0x21, 0x10, cmd]
        if send_and_receive(port_in, port_out, data, f"cmd=0x{cmd:02X}", timeout=0.5):
            break
        time.sleep(0.1)

    print("\n=== Round 5: Try matching response format exactly (with 0x40) and greet payload ===")
    # Maybe we need to send with the same flag as response
    # and include some expected payload
    os_payload = list(b"os_version:15.0")
    # 7-bit encode
    encoded = []
    for i in range(0, len(os_payload), 7):
        chunk = os_payload[i:i+7]
        msb = 0
        for j, b in enumerate(chunk):
            if b & 0x80: msb |= (1 << j)
        encoded.append(msb)
        encoded.extend([b & 0x7F for b in chunk])

    data = TE + [0x19, 0x40, 0x21, 0x10, greet_cmd, 0x00] + encoded
    send_and_receive(port_in, port_out, data, "response-fmt+payload")

    print("\n=== Round 6: Maybe device address bytes are different ===")
    # What if 0x19 is NOT the product ID in the SysEx, and it uses
    # something else? Try without product byte.
    for header in [
        TE + [0x40, 0x21, 0x10, greet_cmd],         # no product, response flag
        TE + [0x00, 0x00, 0x10, greet_cmd],          # all zeros
        TE + [0x19, 0x00, 0x10, greet_cmd],          # no 0x21
        TE + [0x19, 0x21, 0x10, greet_cmd],          # no flags byte
    ]:
        send_and_receive(port_in, port_out, header, f"hdr={hex_string(header[3:])}")
        time.sleep(0.2)

    port_in.close()
    port_out.close()
    print("\n\nDone. If nothing responded, we may need Wireshark USB capture.")


if __name__ == '__main__':
    main()
