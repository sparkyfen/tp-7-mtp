/*
 * TP-7 MTP Mode Switch - THE WORKING VERSION
 *
 * Greet:  F0 00 20 76 19 40 60 [reqId] 01 F7
 * Mode:   F0 00 20 76 19 40 60 [reqId] 04 00 01 03 F7
 *
 * Build: xcrun clang -o tp7_switch_mtp tp7_switch_mtp.c -framework CoreMIDI -framework CoreFoundation
 * Usage: ./tp7_switch_mtp
 */

#include <CoreMIDI/CoreMIDI.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static volatile int got_response = 0;
static UInt8 resp[512];
static int resp_len = 0;

static void read_proc(const MIDIPacketList *pl, void *a, void *b) {
    const MIDIPacket *p = &pl->packet[0];
    for (UInt32 i = 0; i < pl->numPackets; i++) {
        for (int j = 0; j < p->length; j++) {
            if (p->data[j] == 0xF0) resp_len = 0;
            if (resp_len < 512) resp[resp_len++] = p->data[j];
            if (p->data[j] == 0xF7) got_response = 1;
        }
        p = MIDIPacketNext(p);
    }
}

static void done(MIDISysexSendRequest *r) {}

static int send_wait(MIDIEndpointRef dest, UInt8 *data, int len, const char *label) {
    printf("[%s] TX:", label);
    for (int i = 0; i < len; i++) printf(" %02X", data[i]);
    printf("\n");

    got_response = 0; resp_len = 0;
    MIDISysexSendRequest req = {0};
    req.destination = dest;
    req.data = data;
    req.bytesToSend = len;
    req.completionProc = done;

    if (MIDISendSysex(&req) != noErr) { printf("[%s] send failed\n", label); return -3; }

    for (int i = 0; i < 300 && !got_response; i++) usleep(10000);

    if (got_response) {
        printf("[%s] RX:", label);
        for (int i = 0; i < resp_len; i++) printf(" %02X", resp[i]);
        printf("\n");
        int st = (resp_len > 9) ? resp[9] : -1;
        printf("[%s] status=%d\n", label, st);
        return st;
    }
    printf("[%s] no response (device may have switched!)\n", label);
    return -2;
}

int main() {
    printf("=== TP-7 MTP Mode Switch ===\n\n");

    MIDIClientRef client; MIDIPortRef port;
    MIDIClientCreate(CFSTR("TP7"), NULL, NULL, &client);
    MIDIInputPortCreate(client, CFSTR("In"), read_proc, NULL, &port);

    MIDIEndpointRef src = 0, dest = 0;
    for (ItemCount i = 0; i < MIDIGetNumberOfSources(); i++) {
        MIDIEndpointRef s = MIDIGetSource(i);
        CFStringRef n; MIDIObjectGetStringProperty(s, kMIDIPropertyName, &n);
        char buf[256]; CFStringGetCString(n, buf, 256, kCFStringEncodingUTF8); CFRelease(n);
        if (strstr(buf, "TP-7")) { src = s; printf("Source: %s\n", buf); break; }
    }
    for (ItemCount i = 0; i < MIDIGetNumberOfDestinations(); i++) {
        MIDIEndpointRef d = MIDIGetDestination(i);
        CFStringRef n; MIDIObjectGetStringProperty(d, kMIDIPropertyName, &n);
        char buf[256]; CFStringGetCString(n, buf, 256, kCFStringEncodingUTF8); CFRelease(n);
        if (strstr(buf, "TP-7")) { dest = d; printf("Dest: %s\n", buf); break; }
    }
    if (!src || !dest) { printf("TP-7 not found!\n"); return 1; }
    MIDIPortConnectSource(port, src, NULL);

    // Step 1: Greet
    UInt8 greet[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x60, 0x01, 0x01, 0xF7};
    int st = send_wait(dest, greet, sizeof(greet), "greet");
    if (st != 0) { printf("Greet failed!\n"); return 1; }

    usleep(500000);

    // Step 2: Mode switch to MTP — payload 00 01 03
    UInt8 mode[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x60, 0x02, 0x04, 0x00, 0x01, 0x03, 0xF7};
    st = send_wait(dest, mode, sizeof(mode), "mode");

    if (st == 0) {
        printf("\n*** MODE SWITCH SUCCEEDED! ***\n");
        printf("TP-7 should re-enumerate as MTP device.\n");
    } else if (st == -2) {
        printf("\n*** No response — device likely re-enumerating to MTP! ***\n");
    } else {
        printf("\nMode switch returned status %d\n", st);
    }

    MIDIPortDispose(port);
    return 0;
}
