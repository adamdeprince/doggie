#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <wayland-client.h>
#include <wayland-egl.h>
#include <EGL/egl.h>
#include <EGL/eglext.h>
static struct wl_compositor *compositor;
static void global(void *d, struct wl_registry *r, uint32_t name, const char *iface, uint32_t ver) {
    (void)d; (void)ver;
    if (!strcmp(iface, "wl_compositor")) compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
}
static void global_remove(void *d, struct wl_registry *r, uint32_t name) { (void)d; (void)r; (void)name; }
static const struct wl_registry_listener rl = {global, global_remove};
int main(void) {
    struct wl_display *dpy = wl_display_connect(NULL);
    if (!dpy) { printf("no wayland display\n"); return 1; }
    struct wl_registry *reg = wl_display_get_registry(dpy);
    wl_registry_add_listener(reg, &rl, NULL);
    wl_display_roundtrip(dpy);
    EGLDisplay ed = eglGetPlatformDisplay(EGL_PLATFORM_WAYLAND_KHR, dpy, NULL);
    EGLint maj, min;
    if (!eglInitialize(ed, &maj, &min)) { printf("eglInitialize failed\n"); return 1; }
    const char *ext = eglQueryString(ed, EGL_EXTENSIONS);
    printf("vendor: %s\nversion: %s\n", eglQueryString(ed, EGL_VENDOR), eglQueryString(ed, EGL_VERSION));
    printf("EGL_EXT_pixel_format_float: %s\n", strstr(ext, "EGL_EXT_pixel_format_float") ? "yes" : "no");
    printf("EGL_KHR_gl_colorspace: %s  EGL_EXT_gl_colorspace_scrgb_linear: %s  EGL_KHR_no_config_context: %s\n", strstr(ext, "EGL_KHR_gl_colorspace") ? "yes" : "no", strstr(ext, "EGL_EXT_gl_colorspace_scrgb_linear") ? "yes" : "no", strstr(ext, "EGL_KHR_no_config_context") ? "yes" : "no");
    eglBindAPI(EGL_OPENGL_API);
    for (int pass = 0; pass < 3; pass++) {
        EGLint attrs[32]; int i = 0;
#define A(k, v) attrs[i++] = k; attrs[i++] = v;
        A(EGL_COLOR_BUFFER_TYPE, EGL_RGB_BUFFER) A(EGL_SURFACE_TYPE, EGL_WINDOW_BIT) A(EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT)
        if (pass == 0) { A(EGL_COLOR_COMPONENT_TYPE_EXT, EGL_COLOR_COMPONENT_TYPE_FLOAT_EXT) A(EGL_RED_SIZE, 16) A(EGL_GREEN_SIZE, 16) A(EGL_BLUE_SIZE, 16) A(EGL_ALPHA_SIZE, 16) }
        if (pass == 1) { A(EGL_RED_SIZE, 10) A(EGL_GREEN_SIZE, 10) A(EGL_BLUE_SIZE, 10) }
        if (pass == 2) { A(EGL_RED_SIZE, 8) A(EGL_GREEN_SIZE, 8) A(EGL_BLUE_SIZE, 8) A(EGL_ALPHA_SIZE, 8) }
        A(EGL_NONE, EGL_NONE)
        EGLConfig cfgs[64]; EGLint n = 0;
        EGLBoolean ok = eglChooseConfig(ed, attrs, cfgs, 64, &n);
        printf("pass %d (%s): ok=%d configs=%d\n", pass, pass == 0 ? "float16" : pass == 1 ? "10 bit" : "8 bit", ok, n);
        for (int c = 0; c < n && c < 3; c++) {
            EGLint r, g, b, a, t = 0, vid;
            eglGetConfigAttrib(ed, cfgs[c], EGL_RED_SIZE, &r); eglGetConfigAttrib(ed, cfgs[c], EGL_GREEN_SIZE, &g); eglGetConfigAttrib(ed, cfgs[c], EGL_BLUE_SIZE, &b); eglGetConfigAttrib(ed, cfgs[c], EGL_ALPHA_SIZE, &a);
            eglGetConfigAttrib(ed, cfgs[c], EGL_COLOR_COMPONENT_TYPE_EXT, &t); eglGetConfigAttrib(ed, cfgs[c], EGL_NATIVE_VISUAL_ID, &vid);
            printf("   config %d: rgba %d %d %d %d type %s visual 0x%x\n", c, r, g, b, a, t == EGL_COLOR_COMPONENT_TYPE_FLOAT_EXT ? "float" : "fixed", vid);
        }
        if (pass == 0 && n > 0 && compositor) {
            struct wl_surface *s = wl_compositor_create_surface(compositor);
            struct wl_egl_window *w = wl_egl_window_create(s, 64, 64);
            EGLSurface es = eglCreatePlatformWindowSurface(ed, cfgs[0], w, NULL);
            printf("   float window surface: %s (egl error 0x%x)\n", es != EGL_NO_SURFACE ? "created" : "FAILED", eglGetError());
            if (es != EGL_NO_SURFACE) {
                EGLint cattrs[] = {EGL_CONTEXT_MAJOR_VERSION, 3, EGL_CONTEXT_MINOR_VERSION, 3, EGL_CONTEXT_OPENGL_PROFILE_MASK, EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT, EGL_NONE};
                EGLContext ctx = eglCreateContext(ed, cfgs[0], EGL_NO_CONTEXT, cattrs);
                printf("   context: %s (0x%x)\n", ctx != EGL_NO_CONTEXT ? "created" : "FAILED", eglGetError());
                if (ctx != EGL_NO_CONTEXT) {
                    EGLBoolean mc = eglMakeCurrent(ed, es, es, ctx);
                    printf("   make current: %d (0x%x)\n", mc, eglGetError());
                }
            }
        }
    }
    return 0;
}
