// License: GPLv3 Copyright: 2026, Adam DePrince

// Gives an input device of an X server a property, as its driver would. The
// devices of the inputtest driver have none of the properties the libinput and
// wacom drivers give a tablet, and xinput cannot make one that is a string, so
// xrun.sh uses this to name the device node of the rig's tablets:
//
//   xdevprop <device name> string <property> <value>
//   xdevprop <device name> int32 <property> <value> [<value> ...]

#include <X11/Xatom.h>
#include <X11/Xlib.h>
#include <X11/extensions/XInput2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int
main(int argc, char **argv) {
    if (argc < 5 || (strcmp(argv[2], "string") && strcmp(argv[2], "int32")) || (!strcmp(argv[2], "string") && argc != 5)) {
        fprintf(stderr, "usage: %s <device name> string <property> <value> | <device name> int32 <property> <value>...\n", argv[0]);
        return 2;
    }
    Display *display = XOpenDisplay(NULL);
    if (!display) {
        fprintf(stderr, "cannot open the display\n");
        return 1;
    }
    int count = 0, deviceid = -1;
    XIDeviceInfo *devices = XIQueryDevice(display, XIAllDevices, &count);
    for (int i = 0; devices && i < count; i++) {
        if (!strcmp(devices[i].name, argv[1])) deviceid = devices[i].deviceid;
    }
    if (devices) XIFreeDeviceInfo(devices);
    if (deviceid < 0) {
        fprintf(stderr, "no input device named %s\n", argv[1]);
        return 1;
    }
    const Atom property = XInternAtom(display, argv[3], False);
    if (!strcmp(argv[2], "string")) {
        XIChangeProperty(display, deviceid, property, XA_STRING, 8, XIPropModeReplace, (unsigned char *)argv[4], (int)strlen(argv[4]));
    } else {
        const int n = argc - 4;
        uint32_t *values = calloc((size_t)n, sizeof(uint32_t));
        if (!values) return 1;
        for (int i = 0; i < n; i++) values[i] = (uint32_t)strtoul(argv[4 + i], NULL, 0);
        XIChangeProperty(display, deviceid, property, XA_INTEGER, 32, XIPropModeReplace, (unsigned char *)values, n);
        free(values);
    }
    XSync(display, False);
    XCloseDisplay(display);
    return 0;
}
