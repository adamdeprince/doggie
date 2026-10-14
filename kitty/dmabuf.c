/*
 * dmabuf.c
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

// GPU surfaces on Linux: a dma-buf that a program in the window renders into,
// shown by the terminal without its pixels passing through the CPU. See the
// t=g transmission medium in docs/graphics-protocol.rst

#include "data-types.h"
#include "dmabuf.h"

#ifdef __linux__
#include "gl.h"
#include <dlfcn.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/vfs.h>
#include <unistd.h>

#ifndef SYS_pidfd_send_signal
#define SYS_pidfd_send_signal 424
#endif
#ifndef SYS_pidfd_open
#define SYS_pidfd_open 434
#endif
#ifndef SYS_pidfd_getfd
#define SYS_pidfd_getfd 438
#endif
#define DMA_BUF_MAGIC 0x444d4142  // the file system of dma-buf descriptors, from linux/magic.h
#define fourcc_code(a, b, c, d) ((uint32_t)(a) | ((uint32_t)(b) << 8) | ((uint32_t)(c) << 16) | ((uint32_t)(d) << 24))
#define DRM_FORMAT_MOD_LINEAR 0ull
#define DRM_FORMAT_MOD_INVALID 0x00ffffffffffffffull

#define FAIL(...)                              \
    {                                          \
        snprintf(err, errsz, __VA_ARGS__);     \
        return false;                          \
    }

// Parsing {{{

// The formats are those of f=32, straight alpha, in the byte orders a GPU has them in
static const char formats[][5] = {"AB24", "XB24", "AR24", "XR24"};

static bool
expect(const char **p, const char *end, char c) {
    if (*p >= end || **p != c) return false;
    (*p)++;
    return true;
}

// A decimal number, or a hexadecimal one after 0x
static bool
parse_number(const char **p, const char *end, uint64_t *out, uint64_t max) {
    const char *s = *p;
    unsigned base = 10;
    if (end - s > 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) base = 16, s += 2;
    uint64_t v = 0;
    const char *start = s;
    for (; s < end; s++) {
        unsigned d;
        if (*s >= '0' && *s <= '9') d = *s - '0';
        else if (base == 16 && *s >= 'a' && *s <= 'f') d = *s - 'a' + 10;
        else if (base == 16 && *s >= 'A' && *s <= 'F') d = *s - 'A' + 10;
        else break;
        if (v > (max - d) / base) return false;
        v = v * base + d;
    }
    if (s == start) return false;
    *out = v;
    *p = s;
    return true;
}

// dmabuf:<pid>:<fourcc>:<modifier>:<fd>,<offset>,<stride>[:<fd>,<offset>,<stride>...]
bool
dmabuf_parse_spec(const char *spec, size_t len, DmabufSpec *ans, char *err, size_t errsz) {
    memset(ans, 0, sizeof(*ans));
    const char *p = spec, *end = spec + len;
    uint64_t v;
    if (len < 7 || memcmp(p, "dmabuf:", 7) != 0) FAIL("Not a dma-buf surface");
    p += 7;
    if (!parse_number(&p, end, &v, INT32_MAX) || !v || !expect(&p, end, ':')) FAIL("Bad process id in the dma-buf surface");
    ans->pid = (pid_t)v;
    if (end - p < 5 || p[4] != ':') FAIL("The format of a dma-buf surface must be a fourcc of four characters");
    bool known = false;
    for (size_t i = 0; i < arraysz(formats) && !known; i++) known = memcmp(p, formats[i], 4) == 0;
    if (!known) FAIL("Unsupported dma-buf format: %.4s", p);
    ans->fourcc = fourcc_code(p[0], p[1], p[2], p[3]);
    p += 5;
    if (!parse_number(&p, end, &ans->modifier, UINT64_MAX) || !expect(&p, end, ':')) FAIL("Bad format modifier in the dma-buf surface");
    while (true) {
        if (ans->num_planes >= arraysz(ans->planes)) FAIL("A dma-buf surface has at most %zu planes", arraysz(ans->planes));
        DmabufPlane *pl = ans->planes + ans->num_planes++;
        uint64_t fd, offset, stride;
        if (!parse_number(&p, end, &fd, INT32_MAX) || !expect(&p, end, ',') || !parse_number(&p, end, &offset, INT32_MAX) || !expect(&p, end, ',') ||
            !parse_number(&p, end, &stride, INT32_MAX) || !stride)
            FAIL("Bad plane %u in the dma-buf surface, it must be <fd>,<offset>,<stride>", ans->num_planes);
        pl->fd = (int)fd;
        pl->offset = (uint32_t)offset;
        pl->stride = (uint32_t)stride;
        if (p == end) break;
        if (!expect(&p, end, ':')) FAIL("Unexpected text after plane %u of the dma-buf surface", ans->num_planes);
    }
    return true;
}
// }}}

// Taking the buffer from the program {{{

void
dmabuf_close_fds(int *fds, unsigned count) {
    for (unsigned i = 0; i < count; i++) {
        if (fds[i] > -1) close(fds[i]);
        fds[i] = -1;
    }
}

// A descriptor has no name another process can open, so the terminal takes a
// duplicate from the process that has it, as a debugger could. It does so only
// for a process in the session of the window's program: everything the program
// runs, and nothing any other window or program of the user runs, so a program
// cannot make the terminal show another one's buffers. The kernel adds its own
// rule: the terminal must be allowed to trace the process, which under Yama's
// ptrace_scope 1 means that it is a descendant of the terminal
bool
dmabuf_take_fds(const DmabufSpec *s, pid_t session_of, int *fds, char *err, size_t errsz) {
    for (unsigned i = 0; i < s->num_planes; i++) fds[i] = -1;
    if (session_of <= 0) FAIL("There is no program in this window to take a dma-buf from");
    const pid_t session = getsid(session_of);
    if (session < 0) FAIL("The program in this window has gone away");
    const int pidfd = (int)syscall(SYS_pidfd_open, s->pid, 0);
    if (pidfd < 0) FAIL("Cannot open process %d: %s", (int)s->pid, strerror(errno));
    // The session is read after the process is held, and the process is checked to be alive after that, so a process
    // id that was reused in between cannot pass for the one that was named
    if (getsid(s->pid) != session || syscall(SYS_pidfd_send_signal, pidfd, 0, NULL, 0) != 0) {
        close(pidfd);
        FAIL("Process %d is not in the session of the program in this window", (int)s->pid);
    }
    for (unsigned i = 0; i < s->num_planes; i++) {
        // the new descriptor is close on exec
        fds[i] = (int)syscall(SYS_pidfd_getfd, pidfd, s->planes[i].fd, 0);
        if (fds[i] < 0) {
            const int e = errno;
            dmabuf_close_fds(fds, s->num_planes);
            close(pidfd);
            FAIL("Cannot take descriptor %d of process %d: %s%s", s->planes[i].fd, (int)s->pid, strerror(e),
                 e == EPERM ? ", the system does not let the terminal trace it (see ptrace_scope in the documentation of Yama)" : "");
        }
        struct statfs st;
        if (fstatfs(fds[i], &st) != 0 || st.f_type != DMA_BUF_MAGIC) {
            dmabuf_close_fds(fds, s->num_planes);
            close(pidfd);
            FAIL("Descriptor %d of process %d is not a dma-buf", s->planes[i].fd, (int)s->pid);
        }
    }
    close(pidfd);
    return true;
}
// }}}

// Importing it into GL {{{
// EGL is loaded at run time by GLFW, as it is here, and its declarations are
// those of the extensions, so that building needs no EGL headers

typedef void *EGLDisplay;
typedef void *EGLContext;
typedef void *EGLImageKHR;
typedef void *EGLClientBuffer;
typedef int32_t EGLint;
typedef unsigned int EGLenum;
typedef unsigned int EGLBoolean;

#define EGL_EXTENSIONS 0x3055
#define EGL_HEIGHT 0x3056
#define EGL_WIDTH 0x3057
#define EGL_NONE 0x3038
#define EGL_LINUX_DMA_BUF_EXT 0x3270
#define EGL_LINUX_DRM_FOURCC_EXT 0x3271

static const EGLint plane_attributes[4][5] = {
    // fd, offset, pitch, modifier low and high bits
    {0x3272, 0x3273, 0x3274, 0x3443, 0x3444},
    {0x3275, 0x3276, 0x3277, 0x3445, 0x3446},
    {0x3278, 0x3279, 0x327A, 0x3447, 0x3448},
    {0x3440, 0x3441, 0x3442, 0x3449, 0x344A},
};

static struct {
    bool tried, ok;
    void *(*GetProcAddress)(const char *);
    EGLDisplay (*GetCurrentDisplay)(void);
    const char *(*QueryString)(EGLDisplay, EGLint);
    EGLint (*GetError)(void);
    EGLImageKHR (*CreateImageKHR)(EGLDisplay, EGLContext, EGLenum, EGLClientBuffer, const EGLint *);
    EGLBoolean (*DestroyImageKHR)(EGLDisplay, EGLImageKHR);
    void (*ImageTargetTexture2DOES)(GLenum, void *);
} egl;

static bool
load_egl(void) {
    if (egl.tried) return egl.ok;
    egl.tried = true;
    // GLFW has loaded it already, this only finds it
    void *handle = dlopen("libEGL.so.1", RTLD_LAZY);
    if (!handle) return false;
    *(void **)(&egl.GetProcAddress) = dlsym(handle, "eglGetProcAddress");
    *(void **)(&egl.GetCurrentDisplay) = dlsym(handle, "eglGetCurrentDisplay");
    *(void **)(&egl.QueryString) = dlsym(handle, "eglQueryString");
    *(void **)(&egl.GetError) = dlsym(handle, "eglGetError");
    if (!egl.GetProcAddress || !egl.GetCurrentDisplay || !egl.QueryString || !egl.GetError) return false;
    *(void **)(&egl.CreateImageKHR) = egl.GetProcAddress("eglCreateImageKHR");
    *(void **)(&egl.DestroyImageKHR) = egl.GetProcAddress("eglDestroyImageKHR");
    *(void **)(&egl.ImageTargetTexture2DOES) = egl.GetProcAddress("glEGLImageTargetTexture2DOES");
    egl.ok = egl.CreateImageKHR && egl.DestroyImageKHR && egl.ImageTargetTexture2DOES;
    return egl.ok;
}

static bool
has_extension(const char *list, const char *name) {
    const size_t n = strlen(name);
    for (const char *p = list; p && (p = strstr(p, name)); p += n) {
        if ((p == list || p[-1] == ' ') && (p[n] == ' ' || !p[n])) return true;
    }
    return false;
}

typedef struct DmabufSurface {
    EGLDisplay display;
    EGLImageKHR image;
} DmabufSurface;

#undef FAIL
#define FAIL(...)                              \
    {                                          \
        snprintf(err, errsz, __VA_ARGS__);     \
        return NULL;                           \
    }

void *
dmabuf_import(const DmabufSpec *s, const int *fds, uint32_t width, uint32_t height, char *err, size_t errsz) {
    if (!load_egl()) FAIL("GPU surfaces need EGL with EGL_KHR_image_base and GL_OES_EGL_image");
    EGLDisplay display = egl.GetCurrentDisplay();
    if (!display) FAIL("GPU surfaces need an EGL context, and the terminal has none");
    const char *extensions = egl.QueryString(display, EGL_EXTENSIONS);
    if (!has_extension(extensions, "EGL_EXT_image_dma_buf_import")) FAIL("The EGL driver cannot import dma-bufs");
    bool with_modifier = s->modifier != DRM_FORMAT_MOD_INVALID;
    if (with_modifier && !has_extension(extensions, "EGL_EXT_image_dma_buf_import_modifiers")) {
        if (s->modifier != DRM_FORMAT_MOD_LINEAR) FAIL("The EGL driver cannot import dma-bufs with format modifiers");
        // a driver without modifiers takes a buffer to be linear
        with_modifier = false;
    }
    EGLint attributes[6 + 4 * 10 + 1];
    size_t n = 0;
#define A(k, v) attributes[n++] = (k), attributes[n++] = (EGLint)(v)
    A(EGL_WIDTH, width);
    A(EGL_HEIGHT, height);
    A(EGL_LINUX_DRM_FOURCC_EXT, s->fourcc);
    for (unsigned i = 0; i < s->num_planes; i++) {
        A(plane_attributes[i][0], fds[i]);
        A(plane_attributes[i][1], s->planes[i].offset);
        A(plane_attributes[i][2], s->planes[i].stride);
        if (with_modifier) {
            A(plane_attributes[i][3], s->modifier & 0xffffffffu);
            A(plane_attributes[i][4], s->modifier >> 32);
        }
    }
#undef A
    attributes[n++] = EGL_NONE;
    // EGL keeps the buffer for as long as the image exists, the descriptors can be closed once it is made
    EGLImageKHR image = egl.CreateImageKHR(display, NULL, EGL_LINUX_DMA_BUF_EXT, NULL, attributes);
    if (!image) FAIL("The EGL driver refused the dma-buf, EGL error: 0x%x", (unsigned)egl.GetError());
    DmabufSurface *ans = calloc(1, sizeof(DmabufSurface));
    if (!ans) {
        egl.DestroyImageKHR(display, image);
        FAIL("Out of memory");
    }
    ans->display = display;
    ans->image = image;
    return ans;
}

// Points the texture at the buffer. Done again for every refresh, which a
// driver can take as the moment the program says the buffer is ready
bool
dmabuf_bind_texture(void *surface, uint32_t *texture_id) {
    DmabufSurface *s = surface;
    for (unsigned i = 0; i < 16 && glGetError() != GL_NO_ERROR; i++);
    if (!*texture_id) glGenTextures(1, texture_id);
    glBindTexture(GL_TEXTURE_2D, *texture_id);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    egl.ImageTargetTexture2DOES(GL_TEXTURE_2D, s->image);
    const bool ok = glGetError() == GL_NO_ERROR;
    glBindTexture(GL_TEXTURE_2D, 0);
    return ok;
}

void
dmabuf_release(void *surface) {
    DmabufSurface *s = surface;
    if (!s) return;
    egl.DestroyImageKHR(s->display, s->image);
    free(s);
}
// }}}

#else
// Only Linux has dma-bufs
typedef int dmabuf_not_on_this_platform;
#endif
