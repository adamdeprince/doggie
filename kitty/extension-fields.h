/*
 * extension-fields.h
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <string.h>

// The fields of a frame a program sends to one of the OSC 777 extensions, see
// docs/extension-framing.rst. The extensions share the rules, so this header is
// the same on the branch of every extension
typedef struct ExtensionFields {
    char buf[128];
    unsigned count;
    const char *keys[64], *values[64];
} ExtensionFields;

// Cuts a frame into its fields. False when the frame is to be rejected as a
// whole: its fields are longer than 127 bytes, one of them is not key=value
// with a key, or a key is given twice
static inline bool
extension_fields_parse(ExtensionFields *f, const char *data, size_t sz) {
    if (sz >= sizeof(f->buf)) return false;
    memcpy(f->buf, data, sz);
    f->buf[sz] = 0;
    f->count = 0;
    for (char *p = f->buf;;) {
        char *end = strchr(p, ':'), *eq;
        if (end) *end = 0;
        if (!(eq = strchr(p, '=')) || eq == p) return false;
        *eq = 0;
        for (unsigned i = 0; i < f->count; i++) {
            if (!strcmp(f->keys[i], p)) return false;
        }
        if (f->count >= sizeof(f->keys) / sizeof(f->keys[0])) return false;
        f->keys[f->count] = p;
        f->values[f->count++] = eq + 1;
        if (!end) break;
        p = end + 1;
    }
    return true;
}

// The value of a field, NULL when the frame does not have it
static inline const char *
extension_field(const ExtensionFields *f, const char *key) {
    for (unsigned i = 0; i < f->count; i++) {
        if (!strcmp(f->keys[i], key)) return f->values[i];
    }
    return NULL;
}

// A decimal integer from min to max: digits with an optional leading minus,
// no plus, nothing before or after them
static inline bool
extension_int(const char *val, long long min, long long max, long long *ans) {
    if (!val) return false;
    const bool negative = *val == '-';
    const char *p = val + negative;
    if (*p < '0' || *p > '9') return false;
    long long v = 0;
    for (; *p >= '0' && *p <= '9'; p++) {
        v = v * 10 + (*p - '0');
        if (v > 1000000000000000ll) return false;
    }
    if (*p) return false;
    if (negative) v = -v;
    if (v < min || v > max) return false;
    *ans = v;
    return true;
}

// A field that holds an integer from min to max. True when the frame has it
// and it is one, or when the frame does not have it, which leaves *ans as it
// was. False, when the frame is to be rejected, when the value is not one
static inline bool
extension_field_int(const ExtensionFields *f, const char *key, long long min, long long max, long long *ans) {
    const char *val = extension_field(f, key);
    return !val || extension_int(val, min, max, ans);
}

// The version and the op of a frame, which every frame has. False when the
// frame is to be rejected: either is missing, or the version is not the one
// this terminal speaks
static inline bool
extension_frame_header(const ExtensionFields *f, long long version, const char **op) {
    long long v;
    if (!extension_int(extension_field(f, "v"), 0, 2147483647ll, &v) || v != version) return false;
    return (*op = extension_field(f, "op")) != NULL;
}
