#!/usr/bin/env python3
"""
TP-7 SysEx Probe - Send commands and capture responses.
Used to discover the exact request format.
"""

import mido
import sys
import time
from datetime import datetime

TE_MFR = [0x00, 0x20, 0x76]
TP7_PRODUCT = 0x19
PROTO_CONST = 0x21

CMD_GREET = 0x01
CMD_ECHO = 0x02
CMD_DFU = 0x03
CMD_MODE = 0x04

FLAG_REQUEST = 0x00
FLAG_RESPONSE = 0x40

def hex_string(data):
    return ' '.join(f'{b:02X}' for b in data)

def midi7_encode(data):
    """Encode 8-bit data to MIDI 7-bit format (MSB carrier every 8 bytes)."""
    encoded = []
    for i in range(0, len(data), 7):
        chunk = data[i:i+7]
        msb = 0
        for j, byte in enumerate(chunk):
            if byte & 0x80:
                msb |= (1 << j)
            encoded.append(msb if j == 0 else 0)  # placeholder
        # Actually, MSB carrier comes first, then the 7 low bytes
        msb = 0
        for j, byte in enumerate(chunk):
            if byte & 0x80:
                msb |= (1 << j)
        encoded_chunk = [msb] + [b & 0x7F for b in chunk]
        # Replace the placeholder
        encoded = encoded[:len(encoded)-len(chunk)-1] + encoded_chunk
    return encoded

def midi7_encode_simple(data):
    """Encode 8-bit data to MIDI 7-bit: [msb_carrier] [d0&0x7F] [d1&0x7F] ... per 7-byte group."""
    encoded = []
    for i in range(0, len(data), 7):
        chunk = data[i:i+7]
        msb = 0
        for j, byte in enumerate(chunk):
            if byte & 0x80:
                msb |= (1 << j)
        encoded.append(msb)
        encoded.extend([b & 0x7F for b in chunk])
    return encoded

def build_sysex(command, request_id, payload_str=None):
    """Build a TE SysEx request message."""
    header = TE_MFR + [TP7_PRODUCT, FLAG_REQUEST, PROTO_CONST, request_id, command]
    if payload_str:
        payload_bytes = payload_str.encode('ascii')
        encoded = midi7_encode_simple(payload_bytes)
        return header + encoded
    return header

def send_and_receive(port_in, port_out, sysex_data, timeout=3.0):
    """Send SysEx and wait for response."""
    msg = mido.Message('sysex', data=sysex_data)

    # Drain any pending messages
    for _ in port_in.iter_pending():
        pass

    timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
    print(f"\n[{timestamp}] SENDING ({len(sysex_data)+2} bytes):")
    full_send = [0xF0] + list(sysex_data) + [0xF7]
    print(f"  {hex_string(full_send)}")
    sys.stdout.flush()

    port_out.send(msg)

    # Wait for response
    start = time.time()
    while time.time() - start < timeout:
        for resp in port_in.iter_pending():
            if resp.type == 'sysex':
                full_recv = [0xF0] + list(resp.data) + [0xF7]
                timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]
                print(f"[{timestamp}] RECEIVED ({len(full_recv)} bytes):")
                print(f"  {hex_string(full_recv)}")

                # Decode if TE message
                d = resp.data
                if len(d) >= 7 and d[0]==0x00 and d[1]==0x20 and d[2]==0x76:
                    flags = d[4]
                    req_id = d[6]
                    cmd = d[7] if len(d) > 7 else None
                    status = d[8] if len(d) > 8 else None
                    print(f"  Product: 0x{d[3]:02X}, Flags: 0x{flags:02X} ({'response' if flags & 0x40 else 'request'})")
                    print(f"  ReqID: 0x{req_id:02X}, Command: {cmd}, Status: {status}")

                    # Decode payload if present
                    if len(d) > 9:
                        raw_payload = list(d[9:])
                        # Decode 7-bit encoding
                        decoded = []
                        i = 0
                        while i < len(raw_payload):
                            msb = raw_payload[i]
                            i += 1
                            for j in range(7):
                                if i >= len(raw_payload):
                                    break
                                byte = raw_payload[i]
                                if msb & (1 << j):
                                    byte |= 0x80
                                decoded.append(byte)
                                i += 1
                        ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in decoded)
                        print(f"  Payload: {ascii_str}")

                sys.stdout.flush()
                return resp
        time.sleep(0.01)

    print(f"  (no response after {timeout}s)")
    sys.stdout.flush()
    return None


def main():
    inputs = mido.get_input_names()
    outputs = mido.get_output_names()

    tp7_in = None
    tp7_out = None
    for name in inputs:
        if 'TP-7' in name:
            tp7_in = name
    for name in outputs:
        if 'TP-7' in name:
            tp7_out = name

    if not tp7_in or not tp7_out:
        print(f"TP-7 not found. Inputs: {inputs}, Outputs: {outputs}")
        sys.exit(1)

    port_in = mido.open_input(tp7_in)
    port_out = mido.open_output(tp7_out)
    print(f"Connected to {tp7_in}")
    print("=" * 60)

    req_id = 0x01

    # Test 1: Send greet (no payload)
    print("\n--- Test 1: Greet (no payload) ---")
    sysex = build_sysex(CMD_GREET, req_id)
    send_and_receive(port_in, port_out, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 2: Send greet with payload
    print("\n--- Test 2: Greet (with OS payload) ---")
    sysex = build_sysex(CMD_GREET, req_id, "os:linux")
    send_and_receive(port_in, port_out, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 3: Echo
    print("\n--- Test 3: Echo ---")
    sysex = build_sysex(CMD_ECHO, req_id)
    send_and_receive(port_in, port_out, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 4: Mode query (no payload - maybe returns current mode?)
    print("\n--- Test 4: Mode (no payload) ---")
    sysex = build_sysex(CMD_MODE, req_id)
    send_and_receive(port_in, port_out, sysex)
    req_id += 1
    time.sleep(0.5)

    # Test 5: Mode switch to MTP with string payload
    print("\n--- Test 5: Mode 'mtp' (string payload) ---")
    sysex = build_sysex(CMD_MODE, req_id, "mtp")
    resp = send_and_receive(port_in, port_out, sysex)
    req_id += 1

    if resp:
        print("\n*** TP-7 responded to mode switch! Check if it re-enumerates as MTP. ***")

    port_in.close()
    port_out.close()
    print("\nDone.")


if __name__ == '__main__':
    main()
