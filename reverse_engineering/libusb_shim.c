/*
 * libusb interposition shim — logs all bulk transfers.
 * Build: clang -shared -o libusb_shim.dylib libusb_shim.c -framework CoreFoundation
 * Usage: DYLD_INSERT_LIBRARIES=./libusb_shim.dylib /Applications/FieldKit.app/Contents/MacOS/FieldKit
 *
 * This intercepts libusb_bulk_transfer to log what Field Kit sends/receives.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <time.h>

// libusb types (minimal)
typedef struct libusb_device_handle libusb_device_handle;

// Function pointer for the real libusb_bulk_transfer
static int (*real_bulk_transfer)(libusb_device_handle *dev_handle,
    unsigned char endpoint, unsigned char *data, int length,
    int *actual_length, unsigned int timeout) = NULL;

// Function pointer for the real libusb_control_transfer
static int (*real_control_transfer)(libusb_device_handle *dev_handle,
    uint8_t request_type, uint8_t bRequest, uint16_t wValue, uint16_t wIndex,
    unsigned char *data, uint16_t wLength, unsigned int timeout) = NULL;

static FILE *logfile = NULL;

static void ensure_init(void) {
    if (!logfile) {
        logfile = fopen("/tmp/fieldkit_usb.log", "w");
        if (logfile) {
            fprintf(logfile, "=== Field Kit USB Trace ===\n");
            fflush(logfile);
            fprintf(stderr, "[SHIM] Logging USB traffic to /tmp/fieldkit_usb.log\n");
        }
    }
    if (!real_bulk_transfer) {
        real_bulk_transfer = dlsym(RTLD_NEXT, "libusb_bulk_transfer");
    }
    if (!real_control_transfer) {
        real_control_transfer = dlsym(RTLD_NEXT, "libusb_control_transfer");
    }
}

static void log_hex(FILE *f, const char *prefix, const unsigned char *data, int len) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm *tm = localtime(&ts.tv_sec);
    fprintf(f, "[%02d:%02d:%02d.%03ld] %s (%d bytes):",
        tm->tm_hour, tm->tm_min, tm->tm_sec, ts.tv_nsec / 1000000, prefix, len);
    for (int i = 0; i < len && i < 512; i++) {
        if (i % 16 == 0) fprintf(f, "\n  ");
        fprintf(f, "%02X ", data[i]);
    }
    fprintf(f, "\n");

    // Also decode as USB MIDI -> SysEx if it looks like MIDI
    if (len >= 4 && (data[0] & 0x0F) >= 0x04 && (data[0] & 0x0F) <= 0x07) {
        fprintf(f, "  MIDI decode: ");
        for (int i = 0; i < len; i += 4) {
            int cin = data[i] & 0x0F;
            if (cin == 0x04) fprintf(f, "%02X %02X %02X ", data[i+1], data[i+2], data[i+3]);
            else if (cin == 0x07) fprintf(f, "%02X %02X %02X ", data[i+1], data[i+2], data[i+3]);
            else if (cin == 0x06) fprintf(f, "%02X %02X ", data[i+1], data[i+2]);
            else if (cin == 0x05) fprintf(f, "%02X ", data[i+1]);
        }
        fprintf(f, "\n");
    }
    fflush(f);
}

int libusb_bulk_transfer(libusb_device_handle *dev_handle,
    unsigned char endpoint, unsigned char *data, int length,
    int *actual_length, unsigned int timeout)
{
    ensure_init();

    int is_out = (endpoint & 0x80) == 0;
    int ret = real_bulk_transfer(dev_handle, endpoint, data, length, actual_length, timeout);

    if (logfile) {
        char prefix[64];
        int xfer_len = (actual_length && *actual_length > 0) ? *actual_length : length;
        if (is_out) {
            snprintf(prefix, sizeof(prefix), "BULK OUT EP=0x%02X ret=%d", endpoint, ret);
            log_hex(logfile, prefix, data, length);
        } else {
            snprintf(prefix, sizeof(prefix), "BULK IN  EP=0x%02X ret=%d actual=%d",
                endpoint, ret, actual_length ? *actual_length : -1);
            if (ret == 0 && actual_length && *actual_length > 0) {
                log_hex(logfile, prefix, data, *actual_length);
            } else {
                fprintf(logfile, "[--:--:--.---] %s (no data)\n", prefix);
                fflush(logfile);
            }
        }
    }

    return ret;
}

int libusb_control_transfer(libusb_device_handle *dev_handle,
    uint8_t request_type, uint8_t bRequest, uint16_t wValue, uint16_t wIndex,
    unsigned char *data, uint16_t wLength, unsigned int timeout)
{
    ensure_init();

    int ret = real_control_transfer(dev_handle, request_type, bRequest,
        wValue, wIndex, data, wLength, timeout);

    if (logfile) {
        fprintf(logfile, "[CTRL] type=0x%02X req=0x%02X wVal=0x%04X wIdx=0x%04X wLen=%d ret=%d\n",
            request_type, bRequest, wValue, wIndex, wLength, ret);
        if (ret > 0 && data) {
            log_hex(logfile, "  CTRL DATA", data, ret);
        }
        fflush(logfile);
    }

    return ret;
}
