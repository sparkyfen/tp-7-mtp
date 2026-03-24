#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <time.h>
#include <stdint.h>

static void *real_lib = NULL;
static FILE *logf = NULL;

static void init_wrapper(void) __attribute__((constructor));
static void init_wrapper(void) {
    // Load the real libusb from a renamed copy
    real_lib = dlopen("@executable_path/../Frameworks/libusb_real.dylib", RTLD_NOW);
    if (!real_lib) {
        fprintf(stderr, "[WRAPPER] Failed to load real libusb: %s\n", dlerror());
        // Try absolute path
        real_lib = dlopen("/Users/sparky/Code/workspace/field-kit-linux/FieldKit_local.app/Contents/Frameworks/libusb_real.dylib", RTLD_NOW);
    }
    if (!real_lib) {
        fprintf(stderr, "[WRAPPER] FATAL: Cannot load real libusb: %s\n", dlerror());
        return;
    }
    logf = fopen("/tmp/fieldkit_usb.log", "w");
    if (logf) {
        fprintf(logf, "=== Field Kit USB Bulk Transfer Log ===\n");
        fflush(logf);
    }
    fprintf(stderr, "[WRAPPER] USB logging active -> /tmp/fieldkit_usb.log\n");
}

// Helper to get real function
static void *get_real(const char *name) {
    if (!real_lib) return NULL;
    void *sym = dlsym(real_lib, name);
    if (!sym) fprintf(stderr, "[WRAPPER] Symbol not found: %s\n", name);
    return sym;
}

static void log_data(const char *dir, unsigned char endpoint, const unsigned char *data, int len, int ret) {
    if (!logf) return;
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm *tm = localtime(&ts.tv_sec);
    fprintf(logf, "\n[%02d:%02d:%02d.%03ld] %s EP=0x%02X len=%d ret=%d\n",
        tm->tm_hour, tm->tm_min, tm->tm_sec, ts.tv_nsec/1000000, dir, endpoint, len, ret);
    
    int printlen = len < 256 ? len : 256;
    for (int i = 0; i < printlen; i++) {
        if (i % 16 == 0) fprintf(logf, "  %04X: ", i);
        fprintf(logf, "%02X ", data[i]);
        if (i % 16 == 15 || i == printlen-1) {
            // Print ASCII
            int start = i - (i % 16);
            int end = (i % 16 == 15) ? i : i;
            // Pad
            for (int p = end - start + 1; p < 16; p++) fprintf(logf, "   ");
            fprintf(logf, " |");
            for (int j = start; j <= end; j++) {
                char c = (data[j] >= 32 && data[j] < 127) ? data[j] : '.';
                fprintf(logf, "%c", c);
            }
            fprintf(logf, "|\n");
        }
    }
    
    // Decode as USB MIDI if applicable
    if (len >= 4) {
        fprintf(logf, "  MIDI: ");
        for (int i = 0; i < len && i < 256; i += 4) {
            int cin = data[i] & 0x0F;
            if (cin == 0x04 || cin == 0x07) 
                fprintf(logf, "%02X %02X %02X ", data[i+1], data[i+2], data[i+3]);
            else if (cin == 0x06)
                fprintf(logf, "%02X %02X ", data[i+1], data[i+2]);
            else if (cin == 0x05)
                fprintf(logf, "%02X ", data[i+1]);
            else
                fprintf(logf, "[CIN=%X: %02X %02X %02X] ", cin, data[i+1], data[i+2], data[i+3]);
        }
        fprintf(logf, "\n");
    }
    fflush(logf);
}

// We need to forward ALL libusb functions. The critical ones for logging are bulk_transfer.
// For the rest, we use a macro to generate forwarding stubs.

// The key function we want to intercept:
typedef int (*bulk_transfer_fn)(void*, unsigned char, unsigned char*, int, int*, unsigned int);
typedef int (*control_transfer_fn)(void*, uint8_t, uint8_t, uint16_t, uint16_t, unsigned char*, uint16_t, unsigned int);

int libusb_bulk_transfer(void *dev_handle, unsigned char endpoint,
    unsigned char *data, int length, int *actual_length, unsigned int timeout)
{
    static bulk_transfer_fn real_fn = NULL;
    if (!real_fn) real_fn = (bulk_transfer_fn)get_real("libusb_bulk_transfer");
    if (!real_fn) return -1;

    int is_out = (endpoint & 0x80) == 0;
    
    if (is_out && logf) {
        log_data("BULK-OUT", endpoint, data, length, 0);
    }

    int ret = real_fn(dev_handle, endpoint, data, length, actual_length, timeout);

    if (!is_out && ret == 0 && actual_length && *actual_length > 0 && logf) {
        log_data("BULK-IN ", endpoint, data, *actual_length, ret);
    }

    return ret;
}

int libusb_control_transfer(void *dev_handle, uint8_t request_type,
    uint8_t bRequest, uint16_t wValue, uint16_t wIndex,
    unsigned char *data, uint16_t wLength, unsigned int timeout)
{
    static control_transfer_fn real_fn = NULL;
    if (!real_fn) real_fn = (control_transfer_fn)get_real("libusb_control_transfer");
    if (!real_fn) return -1;

    int ret = real_fn(dev_handle, request_type, bRequest, wValue, wIndex, data, wLength, timeout);

    if (logf) {
        fprintf(logf, "\n[CTRL] type=0x%02X req=0x%02X wVal=0x%04X wIdx=0x%04X wLen=%d ret=%d\n",
            request_type, bRequest, wValue, wIndex, wLength, ret);
        if (ret > 0 && data) {
            log_data("CTRL-DATA", 0, data, ret, ret);
        }
        fflush(logf);
    }

    return ret;
}

// Forward all other libusb functions via dlsym
// We generate simple forwarding wrappers for the most commonly used ones

#define FORWARD_0(rettype, name) \
    rettype name(void) { \
        static rettype (*fn)(void) = NULL; \
        if (!fn) fn = get_real(#name); \
        return fn ? fn() : (rettype)0; \
    }

#define FORWARD_1(rettype, name, t1) \
    rettype name(t1 a1) { \
        static rettype (*fn)(t1) = NULL; \
        if (!fn) fn = get_real(#name); \
        return fn ? fn(a1) : (rettype)0; \
    }

#define FORWARD_2(rettype, name, t1, t2) \
    rettype name(t1 a1, t2 a2) { \
        static rettype (*fn)(t1, t2) = NULL; \
        if (!fn) fn = get_real(#name); \
        return fn ? fn(a1, a2) : (rettype)0; \
    }

#define FORWARD_3(rettype, name, t1, t2, t3) \
    rettype name(t1 a1, t2 a2, t3 a3) { \
        static rettype (*fn)(t1, t2, t3) = NULL; \
        if (!fn) fn = get_real(#name); \
        return fn ? fn(a1, a2, a3) : (rettype)0; \
    }

#define FORWARD_4(rettype, name, t1, t2, t3, t4) \
    rettype name(t1 a1, t2 a2, t3 a3, t4 a4) { \
        static rettype (*fn)(t1, t2, t3, t4) = NULL; \
        if (!fn) fn = get_real(#name); \
        return fn ? fn(a1, a2, a3, a4) : (rettype)0; \
    }

// Common libusb functions that need forwarding
FORWARD_1(int, libusb_init, void*)
FORWARD_1(void, libusb_exit, void*)
FORWARD_2(int, libusb_get_device_list, void*, void*)
FORWARD_1(void, libusb_free_device_list, void*)
FORWARD_1(int, libusb_get_device_descriptor, void*)
FORWARD_2(int, libusb_open, void*, void*)
FORWARD_1(void, libusb_close, void*)
FORWARD_3(int, libusb_claim_interface, void*, int, int)
FORWARD_2(int, libusb_release_interface, void*, int)
FORWARD_2(int, libusb_set_configuration, void*, int)
FORWARD_1(int, libusb_get_configuration, void*)
FORWARD_2(int, libusb_detach_kernel_driver, void*, int)
FORWARD_2(int, libusb_attach_kernel_driver, void*, int)
FORWARD_2(int, libusb_kernel_driver_active, void*, int)
FORWARD_1(int, libusb_reset_device, void*)
FORWARD_1(void*, libusb_get_device, void*)
FORWARD_1(int, libusb_get_bus_number, void*)
FORWARD_1(int, libusb_get_device_address, void*)
FORWARD_1(int, libusb_get_device_speed, void*)
FORWARD_3(int, libusb_get_port_numbers, void*, void*, int)
FORWARD_2(int, libusb_get_max_packet_size, void*, int)
FORWARD_2(int, libusb_get_max_iso_packet_size, void*, int)
FORWARD_1(void*, libusb_ref_device, void*)
FORWARD_1(void, libusb_unref_device, void*)
FORWARD_2(int, libusb_wrap_sys_device, void*, void*)
FORWARD_4(int, libusb_get_config_descriptor, void*, int, void*, int)
FORWARD_1(void, libusb_free_config_descriptor, void*)
FORWARD_1(int, libusb_set_auto_detach_kernel_driver, void*)
FORWARD_3(int, libusb_set_interface_alt_setting, void*, int, int)
FORWARD_1(int, libusb_clear_halt, void*)
FORWARD_4(void*, libusb_alloc_transfer, int, int, int, int)
FORWARD_1(void, libusb_free_transfer, void*)
FORWARD_1(int, libusb_submit_transfer, void*)
FORWARD_1(int, libusb_cancel_transfer, void*)
FORWARD_4(int, libusb_handle_events_timeout_completed, void*, void*, void*, int)
FORWARD_1(int, libusb_handle_events, void*)
FORWARD_2(int, libusb_handle_events_timeout, void*, void*)
FORWARD_1(const char*, libusb_strerror, int)
FORWARD_1(const char*, libusb_error_name, int)
FORWARD_1(int, libusb_has_capability, int)
FORWARD_1(void, libusb_set_debug, void*)

