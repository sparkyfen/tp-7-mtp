/*
 * TP-7 Mode Switch via native CoreMIDI MIDISendSysex.
 * This replicates exactly how Field Kit sends the mode command.
 *
 * Build: clang -o tp7_native_midi tp7_native_midi.c -framework CoreMIDI -framework CoreFoundation
 * Usage: ./tp7_native_midi
 */

#include <CoreMIDI/CoreMIDI.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

// Field Kit's responses had b6=0x21. Try that format.
// Format: F0 00 20 76 19 40 [b6] [reqId] [cmd] [payload] F7

// Test all b6 candidates for greet first, then use the working one for mode
static UInt8 greet_b6_40[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_21[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x21, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_00[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x00, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_01[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x01, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_20[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x20, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_41[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x41, 0x01, 0x01, 0xF7 };
static UInt8 greet_b6_61[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x01, 0x01, 0xF7 };

// Mode messages with b6=0x21 (matching Field Kit's response pattern)
static UInt8 mode_b6_21[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x21, 0x02, 0x04, 0xF7 };
static UInt8 mode_b6_21_payload[] = {
    0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x21, 0x03, 0x04,
    0x00, 0x6D, 0x74, 0x70, 0xF7
};

// Also try with b6=0x40 for reference
static UInt8 mode_b6_40[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x04, 0x04, 0xF7 };

// Placeholder for old API compatibility
#define greet_msg greet_b6_40
#define mode_mtp_msg mode_b6_40
static UInt8 mode_mtp_with_payload[] = {
    0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x40, 0x03, 0x04,
    0x00, 0x6D, 0x74, 0x70, 0xF7
};

// Response buffer
static volatile int got_response = 0;
static UInt8 response_buf[512];
static int response_len = 0;

static void print_hex(const char *label, const UInt8 *data, int len) {
    printf("%s (%d bytes):", label, len);
    for (int i = 0; i < len; i++) printf(" %02X", data[i]);
    printf("\n");
}

// MIDI input callback - receives responses
static void midi_read_proc(const MIDIPacketList *pktList, void *readProcRefCon, void *srcConnRefCon) {
    const MIDIPacket *pkt = &pktList->packet[0];
    for (UInt32 i = 0; i < pktList->numPackets; i++) {
        if (pkt->length > 0) {
            print_hex("  RX", pkt->data, pkt->length);

            // Accumulate SysEx
            for (int j = 0; j < pkt->length; j++) {
                if (pkt->data[j] == 0xF0) {
                    response_len = 0;
                }
                if (response_len < sizeof(response_buf)) {
                    response_buf[response_len++] = pkt->data[j];
                }
                if (pkt->data[j] == 0xF7) {
                    print_hex("  Full SysEx response", response_buf, response_len);
                    if (response_len > 9) {
                        printf("  Command: 0x%02X, Status: %d\n",
                               response_buf[8], response_buf[9]);
                    }
                    got_response = 1;
                }
            }
        }
        pkt = MIDIPacketNext(pkt);
    }
}

// Completion callback for MIDISendSysex
static void sysex_complete(MIDISysexSendRequest *request) {
    printf("  SysEx send complete (result: %d)\n", (int)request->complete);
}

static MIDIEndpointRef find_tp7_source(void) {
    ItemCount n = MIDIGetNumberOfSources();
    for (ItemCount i = 0; i < n; i++) {
        MIDIEndpointRef src = MIDIGetSource(i);
        CFStringRef name = NULL;
        MIDIObjectGetStringProperty(src, kMIDIPropertyName, &name);
        if (name) {
            char buf[256];
            CFStringGetCString(name, buf, sizeof(buf), kCFStringEncodingUTF8);
            CFRelease(name);
            if (strstr(buf, "TP-7")) {
                printf("Found TP-7 source: [%lu] %s\n", (unsigned long)i, buf);
                return src;
            }
        }
    }
    return 0;
}

static MIDIEndpointRef find_tp7_dest(void) {
    ItemCount n = MIDIGetNumberOfDestinations();
    for (ItemCount i = 0; i < n; i++) {
        MIDIEndpointRef dest = MIDIGetDestination(i);
        CFStringRef name = NULL;
        MIDIObjectGetStringProperty(dest, kMIDIPropertyName, &name);
        if (name) {
            char buf[256];
            CFStringGetCString(name, buf, sizeof(buf), kCFStringEncodingUTF8);
            CFRelease(name);
            if (strstr(buf, "TP-7")) {
                printf("Found TP-7 destination: [%lu] %s\n", (unsigned long)i, buf);
                return dest;
            }
        }
    }
    return 0;
}

static int send_sysex_and_wait(MIDIEndpointRef dest, UInt8 *data, int len, const char *label) {
    printf("\n--- %s ---\n", label);
    print_hex("  TX", data, len);

    got_response = 0;

    MIDISysexSendRequest req;
    memset(&req, 0, sizeof(req));
    req.destination = dest;
    req.data = data;
    req.bytesToSend = len;
    req.complete = false;
    req.completionProc = sysex_complete;
    req.completionRefCon = NULL;

    OSStatus status = MIDISendSysex(&req);
    if (status != noErr) {
        printf("  MIDISendSysex failed: %d\n", (int)status);
        return -1;
    }

    // Wait for send completion
    for (int i = 0; i < 100 && !req.complete; i++) {
        usleep(10000); // 10ms
    }

    // Wait for response
    for (int i = 0; i < 200 && !got_response; i++) {
        usleep(10000); // 10ms
    }

    if (!got_response) {
        printf("  (no response after 2s)\n");
        return -2;
    }

    int resp_status = (response_len > 9) ? response_buf[9] : -1;
    return resp_status;
}

int main(int argc, char *argv[]) {
    printf("=== TP-7 Native CoreMIDI Mode Switch ===\n\n");

    // Create MIDI client
    MIDIClientRef client;
    OSStatus err = MIDIClientCreate(CFSTR("TP7Switch"), NULL, NULL, &client);
    if (err != noErr) {
        printf("ERROR: MIDIClientCreate failed: %d\n", (int)err);
        return 1;
    }

    // Create input port for responses
    MIDIPortRef inPort;
    err = MIDIInputPortCreate(client, CFSTR("TP7In"), midi_read_proc, NULL, &inPort);
    if (err != noErr) {
        printf("ERROR: MIDIInputPortCreate failed: %d\n", (int)err);
        return 1;
    }

    // Find TP-7
    MIDIEndpointRef tp7_src = find_tp7_source();
    MIDIEndpointRef tp7_dest = find_tp7_dest();

    if (!tp7_src || !tp7_dest) {
        printf("ERROR: TP-7 not found!\n");
        return 1;
    }

    // Connect to source (to receive responses)
    err = MIDIPortConnectSource(inPort, tp7_src, NULL);
    if (err != noErr) {
        printf("ERROR: MIDIPortConnectSource failed: %d\n", (int)err);
        return 1;
    }

    printf("\nConnected to TP-7.\n");

    // Step 1: Test different b6 values for greet via CoreMIDI
    printf("\n=== Testing b6 values for greet via native CoreMIDI ===\n");

    struct { const char *name; UInt8 *data; int len; } greet_tests[] = {
        {"b6=0x21", greet_b6_21, sizeof(greet_b6_21)},
        {"b6=0x00", greet_b6_00, sizeof(greet_b6_00)},
        {"b6=0x01", greet_b6_01, sizeof(greet_b6_01)},
        {"b6=0x20", greet_b6_20, sizeof(greet_b6_20)},
        {"b6=0x40", greet_b6_40, sizeof(greet_b6_40)},
        {"b6=0x41", greet_b6_41, sizeof(greet_b6_41)},
        {"b6=0x61", greet_b6_61, sizeof(greet_b6_61)},
    };

    int working_b6 = -1;
    for (int i = 0; i < sizeof(greet_tests)/sizeof(greet_tests[0]); i++) {
        int status = send_sysex_and_wait(tp7_dest, greet_tests[i].data,
                                          greet_tests[i].len, greet_tests[i].name);
        const char *result = (status == 0) ? "OK" : (status == -2) ? "timeout" : "fail";
        printf("  %s greet: %s (status=%d)\n", greet_tests[i].name, result, status);

        if (status == 0 && working_b6 == -1) {
            // Check response b6 value
            printf("  Response b6=0x%02X b7=0x%02X\n", response_buf[6], response_buf[7]);
            if (response_buf[6] != 0x00) {
                printf("  *** NON-ZERO b6 in response! This might be the right format! ***\n");
                working_b6 = greet_tests[i].data[6];  // the b6 we sent
            }
        }
        usleep(300000);
    }

    // Step 2: Try mode with b6=0x21
    printf("\n=== Mode switch attempts ===\n");

    struct { const char *name; UInt8 *data; int len; } mode_tests[] = {
        {"mode b6=0x21 (no payload)", mode_b6_21, sizeof(mode_b6_21)},
        {"mode b6=0x21 (mtp payload)", mode_b6_21_payload, sizeof(mode_b6_21_payload)},
        {"mode b6=0x40 (no payload)", mode_b6_40, sizeof(mode_b6_40)},
    };

    for (int i = 0; i < sizeof(mode_tests)/sizeof(mode_tests[0]); i++) {
        int status = send_sysex_and_wait(tp7_dest, mode_tests[i].data,
                                          mode_tests[i].len, mode_tests[i].name);
        const char *result = (status == 0) ? "SUCCESS!" :
                            (status == 1) ? "error" :
                            (status == -2) ? "TIMEOUT (maybe switched!)" : "other";
        printf("  %s: %s (status=%d)\n", mode_tests[i].name, result, status);

        if (status == 0 || status == -2) {
            printf("\n*** Mode switch may have succeeded! ***\n");
            break;
        }
        usleep(500000);
    }

    // Step 3: Brute force ALL b6 values for mode via CoreMIDI
    printf("\n=== Brute force b6 for mode via CoreMIDI ===\n");
    UInt8 mode_buf[] = { 0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x00, 0x10, 0x04, 0xF7 };
    for (int b6 = 0; b6 < 0x80; b6++) {
        mode_buf[6] = b6;
        mode_buf[7] = (b6 + 0x10) & 0x7F;  // varying reqId

        got_response = 0;
        MIDISysexSendRequest req;
        memset(&req, 0, sizeof(req));
        req.destination = tp7_dest;
        req.data = mode_buf;
        req.bytesToSend = sizeof(mode_buf);
        req.complete = false;
        req.completionProc = sysex_complete;
        req.completionRefCon = NULL;

        OSStatus err = MIDISendSysex(&req);
        if (err != noErr) continue;

        // Wait for completion + response
        for (int w = 0; w < 50 && !req.complete; w++) usleep(10000);
        for (int w = 0; w < 80 && !got_response; w++) usleep(10000);

        if (got_response && response_len > 9) {
            int st = response_buf[9];
            if (st == 0) {
                printf("  b6=0x%02X -> SUCCESS! status=0\n", b6);
                print_hex("    RX", response_buf, response_len);
                break;
            }
            // Don't print errors to reduce noise
        } else if (!got_response) {
            // Timeout could mean device switched!
            printf("  b6=0x%02X -> TIMEOUT\n", b6);
        }

        if (b6 % 32 == 31) {
            printf("  ...tried 0x00-0x%02X\n", b6);
        }
        usleep(30000);
    }

    printf("\nDone.\n");

    MIDIPortDispose(inPort);

    return 0;
}
