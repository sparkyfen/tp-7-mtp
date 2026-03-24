/*
 * TP-7 Mode Switch - Using correct b6=0x61 header format.
 * Build: xcrun clang -o tp7_mode_b6_61 tp7_mode_b6_61.c -framework CoreMIDI -framework CoreFoundation
 */

#include <CoreMIDI/CoreMIDI.h>
#include <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static volatile int got_response = 0;
static UInt8 response_buf[512];
static int response_len = 0;

static void print_hex(const char *label, const UInt8 *data, int len) {
    printf("%s (%d bytes):", label, len);
    for (int i = 0; i < len; i++) printf(" %02X", data[i]);
    printf("\n");
}

static void midi_read_proc(const MIDIPacketList *pktList, void *a, void *b) {
    const MIDIPacket *pkt = &pktList->packet[0];
    for (UInt32 i = 0; i < pktList->numPackets; i++) {
        for (int j = 0; j < pkt->length; j++) {
            if (pkt->data[j] == 0xF0) response_len = 0;
            if (response_len < 512) response_buf[response_len++] = pkt->data[j];
            if (pkt->data[j] == 0xF7) got_response = 1;
        }
        pkt = MIDIPacketNext(pkt);
    }
}

static void sysex_done(MIDISysexSendRequest *r) {}

static int send_and_wait(MIDIEndpointRef dest, UInt8 *data, int len, const char *label, int timeout_ms) {
    printf("\n  [%s] TX: ", label);
    for (int i = 0; i < len; i++) printf("%02X ", data[i]);
    printf("\n");

    got_response = 0;
    response_len = 0;

    MIDISysexSendRequest req = {0};
    req.destination = dest;
    req.data = data;
    req.bytesToSend = len;
    req.completionProc = sysex_done;

    OSStatus err = MIDISendSysex(&req);
    if (err) { printf("  Send error: %d\n", (int)err); return -3; }

    for (int i = 0; i < timeout_ms/10 && !req.complete; i++) usleep(10000);
    for (int i = 0; i < timeout_ms/10 && !got_response; i++) usleep(10000);

    if (got_response) {
        printf("  [%s] RX: ", label);
        for (int i = 0; i < response_len; i++) printf("%02X ", response_buf[i]);
        printf("\n");
        int st = (response_len > 9) ? response_buf[9] : -1;
        printf("  [%s] cmd=0x%02X status=%d b6=0x%02X b7=0x%02X\n",
               label, response_buf[8], st, response_buf[6], response_buf[7]);
        return st;
    }
    printf("  [%s] TIMEOUT (device may have switched!)\n", label);
    return -2;
}

int main() {
    printf("=== TP-7 Mode Switch (b6=0x61 format) ===\n");

    MIDIClientRef client;
    MIDIPortRef inPort;
    MIDIClientCreate(CFSTR("TP7"), NULL, NULL, &client);
    MIDIInputPortCreate(client, CFSTR("In"), midi_read_proc, NULL, &inPort);

    // Find TP-7
    MIDIEndpointRef src = 0, dest = 0;
    for (ItemCount i = 0; i < MIDIGetNumberOfSources(); i++) {
        MIDIEndpointRef s = MIDIGetSource(i);
        CFStringRef n; MIDIObjectGetStringProperty(s, kMIDIPropertyName, &n);
        char buf[256]; CFStringGetCString(n, buf, 256, kCFStringEncodingUTF8); CFRelease(n);
        if (strstr(buf, "TP-7")) { src = s; break; }
    }
    for (ItemCount i = 0; i < MIDIGetNumberOfDestinations(); i++) {
        MIDIEndpointRef d = MIDIGetDestination(i);
        CFStringRef n; MIDIObjectGetStringProperty(d, kMIDIPropertyName, &n);
        char buf[256]; CFStringGetCString(n, buf, 256, kCFStringEncodingUTF8); CFRelease(n);
        if (strstr(buf, "TP-7")) { dest = d; break; }
    }
    if (!src || !dest) { printf("TP-7 not found!\n"); return 1; }

    MIDIPortConnectSource(inPort, src, NULL);
    printf("Connected to TP-7.\n");

    // Step 1: Greet with b6=0x61
    UInt8 greet[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x01, 0x01, 0xF7};
    int st = send_and_wait(dest, greet, sizeof(greet), "greet b6=0x61", 3000);
    if (st != 0) { printf("Greet failed!\n"); return 1; }
    printf("  Greet OK!\n");
    usleep(500000);

    // Step 2: Try mode with b6=0x61 and various payloads
    printf("\n=== Mode switch attempts with b6=0x61 ===\n");

    // 2a: No payload
    UInt8 m1[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x02, 0x04, 0xF7};
    st = send_and_wait(dest, m1, sizeof(m1), "mode bare", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2b: 7-bit encoded "mtp"
    UInt8 m2[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x03, 0x04, 0x00, 0x6D, 0x74, 0x70, 0xF7};
    st = send_and_wait(dest, m2, sizeof(m2), "mode 'mtp'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2c: Raw byte 0x02
    UInt8 m3[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x04, 0x04, 0x02, 0xF7};
    st = send_and_wait(dest, m3, sizeof(m3), "mode raw 0x02", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2d: 7-bit encoded "mode:mtp"
    UInt8 m4[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x05, 0x04,
                  0x00, 0x6D, 0x6F, 0x64, 0x65, 0x3A, 0x6D, 0x00, 0x74, 0x70, 0xF7};
    st = send_and_wait(dest, m4, sizeof(m4), "mode 'mode:mtp'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2e: Single byte payloads 0x00-0x07
    for (int v = 0; v <= 7; v++) {
        UInt8 m[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, (UInt8)(0x10+v), 0x04, (UInt8)v, 0xF7};
        char label[32]; snprintf(label, sizeof(label), "mode val=%d", v);
        st = send_and_wait(dest, m, sizeof(m), label, 2000);
        if (st == 0 || st == -2) goto check;
        usleep(200000);
    }

    // 2f: 7-bit encoded "midi" (switch to midi - maybe current mode matters?)
    UInt8 m5[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x20, 0x04, 0x00, 0x6D, 0x69, 0x64, 0x69, 0xF7};
    st = send_and_wait(dest, m5, sizeof(m5), "mode 'midi'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2g: 7-bit encoded "massStorage"
    UInt8 m6[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x21, 0x04,
                  0x00, 0x6D, 0x61, 0x73, 0x73, 0x53, 0x74, 0x00, 0x6F, 0x72, 0x61, 0x67, 0x65, 0xF7};
    st = send_and_wait(dest, m6, sizeof(m6), "mode 'massStorage'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2h: 7-bit encoded with key=value "usb_mode:mtp"
    UInt8 m7[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x22, 0x04,
                  0x00, 0x75, 0x73, 0x62, 0x5F, 0x6D, 0x6F, 0x00, 0x64, 0x65, 0x3A, 0x6D, 0x74, 0x70, 0xF7};
    st = send_and_wait(dest, m7, sizeof(m7), "mode 'usb_mode:mtp'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2i: 7-bit encoded "2" (the number as a string)
    UInt8 m8[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x23, 0x04, 0x00, 0x32, 0xF7};
    st = send_and_wait(dest, m8, sizeof(m8), "mode '2'", 3000);
    if (st == 0 || st == -2) goto check;
    usleep(300000);

    // 2j: Two-byte encoded value [0x00, 0x02] (7-bit encoded 0x02)
    UInt8 m9[] = {0xF0, 0x00, 0x20, 0x76, 0x19, 0x40, 0x61, 0x24, 0x04, 0x00, 0x02, 0xF7};
    st = send_and_wait(dest, m9, sizeof(m9), "mode enc(0x02)", 3000);
    if (st == 0 || st == -2) goto check;

    printf("\nAll mode attempts returned error.\n");
    printf("The mode command payload remains unknown.\n");
    goto done;

check:
    printf("\n*** Possible success! Checking device... ***\n");
    sleep(3);

done:
    MIDIPortDispose(inPort);
    printf("\nDone.\n");
    return 0;
}
