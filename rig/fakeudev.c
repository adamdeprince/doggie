// License: GPLv3 Copyright: 2026, Adam DePrince

// A stand-in for libudev that knows the two tablets of the rig and nothing
// else. The terminal asks libudev how large a tablet is and whether it is a
// display, by the device node the compositor names for the tablet, and the
// tablets of the rig have no node. run.sh builds this as libudev.so.1 where
// only the terminal finds it, and play.py names two character devices that
// every machine has as the nodes of the tablets: this file answers for those
// two as udev and the kernel would for the real tablets, in the properties and
// attributes they would be read from, and for no other device.

#include <stdlib.h>
#include <string.h>
#include <sys/sysmacros.h>
#include <sys/types.h>

struct udev {
    int unused;
};

typedef struct Pair {
    const char *key, *value;
} Pair;

// What is known of a tablet: the properties of its node in the udev database,
// and the attributes of the input device above it in sysfs
typedef struct Tablet {
    unsigned major, minor;
    Pair properties[8], attributes[8];
} Tablet;

struct udev_device {
    const Tablet *tablet;
    int is_input;  // the input device rather than its node
    struct udev_device *parent;
};

static const Tablet tablets[] = {
    // /dev/null: a Wacom Intuos5 touch M, 224 by 140 mm, which is not a display (INPUT_PROP_POINTER)
    {1, 3,
     {{"ID_INPUT", "1"}, {"ID_INPUT_TABLET", "1"}, {"ID_INPUT_WIDTH_MM", "224"}, {"ID_INPUT_HEIGHT_MM", "140"}},
     {{"name", "Wacom Intuos5 touch M Pen"}, {"id/vendor", "056a"}, {"id/product", "0027"}, {"properties", "1"}}},
    // /dev/zero: a Wacom Cintiq Pro 16, 345 by 194 mm, which is one (INPUT_PROP_DIRECT)
    {1, 5,
     {{"ID_INPUT", "1"}, {"ID_INPUT_TABLET", "1"}, {"ID_INPUT_WIDTH_MM", "345"}, {"ID_INPUT_HEIGHT_MM", "194"}},
     {{"name", "Wacom Cintiq Pro 16 Pen"}, {"id/vendor", "056a"}, {"id/product", "0350"}, {"properties", "2"}}},
};

static const char *
find(const Pair *pairs, const char *key) {
    for (int i = 0; i < 8 && pairs[i].key; i++) {
        if (!strcmp(pairs[i].key, key)) return pairs[i].value;
    }
    return NULL;
}

struct udev *
udev_new(void) {
    return calloc(1, sizeof(struct udev));
}

struct udev *
udev_unref(struct udev *udev) {
    free(udev);
    return NULL;
}

struct udev_device *
udev_device_new_from_devnum(struct udev *udev, char type, dev_t devnum) {
    if (!udev || type != 'c') return NULL;
    for (size_t i = 0; i < sizeof(tablets) / sizeof(tablets[0]); i++) {
        if (major(devnum) != tablets[i].major || minor(devnum) != tablets[i].minor) continue;
        struct udev_device *node = calloc(1, sizeof(struct udev_device)), *input = calloc(1, sizeof(struct udev_device));
        if (!node || !input) {
            free(node);
            free(input);
            return NULL;
        }
        node->tablet = input->tablet = tablets + i;
        input->is_input = 1;
        node->parent = input;
        return node;
    }
    return NULL;
}

struct udev_device *
udev_device_get_parent(struct udev_device *device) {
    return device ? device->parent : NULL;
}

const char *
udev_device_get_property_value(struct udev_device *device, const char *key) {
    return device && !device->is_input ? find(device->tablet->properties, key) : NULL;
}

const char *
udev_device_get_sysattr_value(struct udev_device *device, const char *sysattr) {
    return device && device->is_input ? find(device->tablet->attributes, sysattr) : NULL;
}

struct udev_device *
udev_device_unref(struct udev_device *device) {
    if (device) free(device->parent);
    free(device);
    return NULL;
}
