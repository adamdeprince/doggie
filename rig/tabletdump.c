/*
 * tabletdump.c
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 *
 * A Wayland client that binds tablet-v2, opens a window without contents and
 * prints every tablet, tool and pad event it is sent. selftest.sh runs it
 * against wlproxy.py to check what the proxy sends with libwayland itself,
 * independently of the terminal.
 */

#include <stdio.h>
#include <string.h>
#include <wayland-client.h>
#include "tablet-v2-client-protocol.h"
#include "xdg-shell-client-protocol.h"

#define UNUSED __attribute__((unused))
#define P(...) do { printf(__VA_ARGS__); putchar('\n'); fflush(stdout); } while (0)

static struct wl_compositor *compositor;
static struct xdg_wm_base *wm_base;
static struct wl_seat *seat;
static struct zwp_tablet_manager_v2 *manager;

// Tablets {{{
static void tablet_name(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED, const char *name) { P("tablet name %s", name); }
static void tablet_id(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED, uint32_t vid, uint32_t pid) { P("tablet id %04x:%04x", vid, pid); }
static void tablet_path(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED, const char *path) { P("tablet path %s", path); }
static void tablet_done(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED) { P("tablet done"); }
static void tablet_removed(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED) { P("tablet removed"); }
static void tablet_bustype(void *d UNUSED, struct zwp_tablet_v2 *t UNUSED, uint32_t bustype) { P("tablet bustype %u", bustype); }
static const struct zwp_tablet_v2_listener tablet_listener = {tablet_name, tablet_id, tablet_path, tablet_done, tablet_removed, tablet_bustype};
// }}}

// Tools {{{
#define T void *d UNUSED, struct zwp_tablet_tool_v2 *t UNUSED
static void tool_type(T, uint32_t type) { P("tool type %#x", type); }
static void tool_serial(T, uint32_t hi, uint32_t lo) { P("tool serial %llu", ((unsigned long long)hi << 32) | lo); }
static void tool_id_wacom(T, uint32_t hi, uint32_t lo) { P("tool id_wacom %#llx", ((unsigned long long)hi << 32) | lo); }
static void tool_capability(T, uint32_t c) { P("tool capability %u", c); }
static void tool_done(T) { P("tool done"); }
static void tool_removed(T) { P("tool removed"); }
static void tool_proximity_in(T, uint32_t serial UNUSED, struct zwp_tablet_v2 *tablet UNUSED, struct wl_surface *surface UNUSED) { P("tool proximity_in"); }
static void tool_proximity_out(T) { P("tool proximity_out"); }
static void tool_down(T, uint32_t serial UNUSED) { P("tool down"); }
static void tool_up(T) { P("tool up"); }
static void tool_motion(T, wl_fixed_t x, wl_fixed_t y) { P("tool motion %.2f %.2f", wl_fixed_to_double(x), wl_fixed_to_double(y)); }
static void tool_pressure(T, uint32_t p) { P("tool pressure %u", p); }
static void tool_distance(T, uint32_t v) { P("tool distance %u", v); }
static void tool_tilt(T, wl_fixed_t x, wl_fixed_t y) { P("tool tilt %.2f %.2f", wl_fixed_to_double(x), wl_fixed_to_double(y)); }
static void tool_rotation(T, wl_fixed_t v) { P("tool rotation %.2f", wl_fixed_to_double(v)); }
static void tool_slider(T, int32_t v) { P("tool slider %d", v); }
static void tool_wheel(T, wl_fixed_t deg, int32_t clicks) { P("tool wheel %.2f %d", wl_fixed_to_double(deg), clicks); }
static void tool_button(T, uint32_t serial UNUSED, uint32_t button, uint32_t state) { P("tool button %#x %u", button, state); }
static void tool_frame(T, uint32_t time UNUSED) { P("tool frame"); }
#undef T
static const struct zwp_tablet_tool_v2_listener tool_listener = {
    tool_type,  tool_serial,   tool_id_wacom, tool_capability, tool_done,   tool_removed, tool_proximity_in, tool_proximity_out, tool_down, tool_up,
    tool_motion, tool_pressure, tool_distance, tool_tilt,       tool_rotation, tool_slider,  tool_wheel,        tool_button,        tool_frame,
};
// }}}

// Pads {{{
static uint32_t last_mode_serial;

static void ring_source(void *d UNUSED, struct zwp_tablet_pad_ring_v2 *r UNUSED, uint32_t source) { P("ring source %u", source); }
static void ring_angle(void *d UNUSED, struct zwp_tablet_pad_ring_v2 *r UNUSED, wl_fixed_t deg) { P("ring angle %.2f", wl_fixed_to_double(deg)); }
static void ring_stop(void *d UNUSED, struct zwp_tablet_pad_ring_v2 *r UNUSED) { P("ring stop"); }
static void ring_frame(void *d UNUSED, struct zwp_tablet_pad_ring_v2 *r UNUSED, uint32_t time UNUSED) { P("ring frame"); }
static const struct zwp_tablet_pad_ring_v2_listener ring_listener = {ring_source, ring_angle, ring_stop, ring_frame};

static void strip_source(void *d UNUSED, struct zwp_tablet_pad_strip_v2 *s UNUSED, uint32_t source) { P("strip source %u", source); }
static void strip_position(void *d UNUSED, struct zwp_tablet_pad_strip_v2 *s UNUSED, uint32_t pos) { P("strip position %u", pos); }
static void strip_stop(void *d UNUSED, struct zwp_tablet_pad_strip_v2 *s UNUSED) { P("strip stop"); }
static void strip_frame(void *d UNUSED, struct zwp_tablet_pad_strip_v2 *s UNUSED, uint32_t time UNUSED) { P("strip frame"); }
static const struct zwp_tablet_pad_strip_v2_listener strip_listener = {strip_source, strip_position, strip_stop, strip_frame};

static void dial_delta(void *d UNUSED, struct zwp_tablet_pad_dial_v2 *x UNUSED, int32_t value120) { P("dial delta %d", value120); }
static void dial_frame(void *d UNUSED, struct zwp_tablet_pad_dial_v2 *x UNUSED, uint32_t time UNUSED) { P("dial frame"); }
static const struct zwp_tablet_pad_dial_v2_listener dial_listener = {dial_delta, dial_frame};

#define G void *d UNUSED, struct zwp_tablet_pad_group_v2 *g UNUSED
static void
group_buttons(G, struct wl_array *buttons) {
    char buf[256] = "";
    uint32_t *b;
    wl_array_for_each(b, buttons) snprintf(buf + strlen(buf), sizeof(buf) - strlen(buf), " %u", *b);
    P("group buttons%s", buf);
}
static void group_ring(G, struct zwp_tablet_pad_ring_v2 *ring) {
    P("group ring");
    zwp_tablet_pad_ring_v2_add_listener(ring, &ring_listener, NULL);
    // what a program does when the mode changes, here so that the proxy's side of it is exercised
    zwp_tablet_pad_ring_v2_set_feedback(ring, "zoom", last_mode_serial);
}
static void group_strip(G, struct zwp_tablet_pad_strip_v2 *strip) {
    P("group strip");
    zwp_tablet_pad_strip_v2_add_listener(strip, &strip_listener, NULL);
}
static void group_modes(G, uint32_t modes) { P("group modes %u", modes); }
static void group_done(G) { P("group done"); }
static void group_mode_switch(G, uint32_t time UNUSED, uint32_t serial, uint32_t mode) {
    last_mode_serial = serial;
    P("group mode_switch %u", mode);
}
static void group_dial(G, struct zwp_tablet_pad_dial_v2 *dial) {
    P("group dial");
    zwp_tablet_pad_dial_v2_add_listener(dial, &dial_listener, NULL);
    zwp_tablet_pad_dial_v2_set_feedback(dial, "brush size", last_mode_serial);
}
#undef G
static const struct zwp_tablet_pad_group_v2_listener group_listener = {
    group_buttons, group_ring, group_strip, group_modes, group_done, group_mode_switch, group_dial,
};

#define D void *d UNUSED, struct zwp_tablet_pad_v2 *pad UNUSED
static void pad_group(D, struct zwp_tablet_pad_group_v2 *group) {
    P("pad group");
    zwp_tablet_pad_group_v2_add_listener(group, &group_listener, NULL);
}
static void pad_path(D, const char *path) { P("pad path %s", path); }
static void pad_buttons(D, uint32_t n) { P("pad buttons %u", n); }
static void pad_done(D) { P("pad done"); }
static void pad_button(D, uint32_t time UNUSED, uint32_t button, uint32_t state) {
    P("pad button %u %u", button, state);
    if (state) zwp_tablet_pad_v2_set_feedback(pad, button, "undo", last_mode_serial);
}
static void pad_enter(D, uint32_t serial UNUSED, struct zwp_tablet_v2 *tablet UNUSED, struct wl_surface *surface UNUSED) { P("pad enter"); }
static void pad_leave(D, uint32_t serial UNUSED, struct wl_surface *surface UNUSED) { P("pad leave"); }
static void pad_removed(D) { P("pad removed"); }
#undef D
static const struct zwp_tablet_pad_v2_listener pad_listener = {
    pad_group, pad_path, pad_buttons, pad_done, pad_button, pad_enter, pad_leave, pad_removed,
};
// }}}

static void seat_tablet_added(void *d UNUSED, struct zwp_tablet_seat_v2 *s UNUSED, struct zwp_tablet_v2 *tablet) {
    P("tablet_added");
    zwp_tablet_v2_add_listener(tablet, &tablet_listener, NULL);
}
static void seat_tool_added(void *d UNUSED, struct zwp_tablet_seat_v2 *s UNUSED, struct zwp_tablet_tool_v2 *tool) {
    P("tool_added");
    zwp_tablet_tool_v2_add_listener(tool, &tool_listener, NULL);
}
static void seat_pad_added(void *d UNUSED, struct zwp_tablet_seat_v2 *s UNUSED, struct zwp_tablet_pad_v2 *pad) {
    P("pad_added");
    zwp_tablet_pad_v2_add_listener(pad, &pad_listener, NULL);
}
static const struct zwp_tablet_seat_v2_listener tablet_seat_listener = {seat_tablet_added, seat_tool_added, seat_pad_added};

static void wm_ping(void *d UNUSED, struct xdg_wm_base *wm, uint32_t serial) { xdg_wm_base_pong(wm, serial); }
static const struct xdg_wm_base_listener wm_listener = {wm_ping};
static void surface_configure(void *d UNUSED, struct xdg_surface *s, uint32_t serial) { xdg_surface_ack_configure(s, serial); }
static const struct xdg_surface_listener surface_listener = {surface_configure};

static void
registry_global(void *d UNUSED, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version) {
    if (!strcmp(iface, wl_compositor_interface.name)) compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
    else if (!strcmp(iface, xdg_wm_base_interface.name)) wm_base = wl_registry_bind(r, name, &xdg_wm_base_interface, 1);
    else if (!strcmp(iface, wl_seat_interface.name)) seat = wl_registry_bind(r, name, &wl_seat_interface, 1);
    else if (!strcmp(iface, zwp_tablet_manager_v2_interface.name)) {
        P("zwp_tablet_manager_v2 version %u", version);
        manager = wl_registry_bind(r, name, &zwp_tablet_manager_v2_interface, version < 2 ? version : 2);
    }
}
static void registry_global_remove(void *d UNUSED, struct wl_registry *r UNUSED, uint32_t name UNUSED) {}
static const struct wl_registry_listener registry_listener = {registry_global, registry_global_remove};

int
main(void) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return fprintf(stderr, "cannot connect to the Wayland display\n"), 1;
    struct wl_registry *registry = wl_display_get_registry(display);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip(display);
    if (!compositor || !wm_base || !seat || !manager) return fprintf(stderr, "the compositor lacks a global this needs\n"), 1;
    xdg_wm_base_add_listener(wm_base, &wm_listener, NULL);
    struct wl_surface *surface = wl_compositor_create_surface(compositor);
    struct xdg_surface *xs = xdg_wm_base_get_xdg_surface(wm_base, surface);
    xdg_surface_add_listener(xs, &surface_listener, NULL);
    xdg_surface_get_toplevel(xs);
    wl_surface_commit(surface);
    zwp_tablet_seat_v2_add_listener(zwp_tablet_manager_v2_get_tablet_seat(manager, seat), &tablet_seat_listener, NULL);
    while (wl_display_dispatch(display) != -1) {}
    int err = wl_display_get_error(display);
    const struct wl_interface *iface = NULL;
    uint32_t id = 0, code = wl_display_get_protocol_error(display, &iface, &id);
    fprintf(stderr, "the connection ended: error %d, protocol error %u on %s@%u\n", err, code, iface ? iface->name : "nothing", id);
    return 0;
}
