/*
 * osc777.c
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

#include "screen.h"
#include "control-codes.h"

// Every OSC 777 selector this terminal speaks, with the version of its
// protocol, see docs/capabilities-protocol.rst. A selector handled in
// dispatch_osc() must also be listed here.
static const struct { const char *selector; unsigned version; } extensions[] = {
    {"caps", 1},
};

void
screen_caps_query(Screen *self, const char *data, size_t sz) {
    char buf[128], reply[512], *saveptr = NULL;
    const char *op = "";
    int v = 0, id = -1;
    if (sz >= sizeof(buf)) return;
    memcpy(buf, data, sz);
    buf[sz] = 0;
    for (char *tok = strtok_r(buf, ":", &saveptr); tok; tok = strtok_r(NULL, ":", &saveptr)) {
        char *val = strchr(tok, '=');
        if (!val) return;
        *val++ = 0;
        if (!strcmp(tok, "v")) v = atoi(val);
        else if (!strcmp(tok, "op")) op = val;
        else if (!strcmp(tok, "id")) id = atoi(val);
    }
    if (v != 1 || strcmp(op, "query") || id < 0) return;
    int n = snprintf(reply, sizeof(reply), "777;caps;v=1:op=cap:id=%d:caps=1:ext=", id);
    for (size_t i = 0; i < arraysz(extensions) && n < (int)sizeof(reply); i++)
        n += snprintf(reply + n, sizeof(reply) - n, "%s%s.%u", i ? "," : "", extensions[i].selector, extensions[i].version);
    write_escape_code_to_child(self, ESC_OSC, reply);
}
