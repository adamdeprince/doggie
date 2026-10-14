/*
 * backend_utils.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _GNU_SOURCE
#include "backend_utils.h"
#include "internal.h"
#include "memfd.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <stdio.h>
#include <sys/mman.h>
#include <sys/stat.h>

#ifdef __NetBSD__
#define ppoll pollts
#endif

void
update_fds(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *w = eld->watches + i;
        eld->fds[i].fd = w->fd;
        eld->fds[i].events = w->enabled ? w->events : 0;
    }
}


id_type
addWatch(EventLoopData *eld, const char *name, int fd, int events, int enabled, watch_callback_func cb, void *cb_data) {
    if (eld->watches_count >= sizeof(eld->watches) / sizeof(eld->watches[0])) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many watches added");
        return 0;
    }
    static id_type watch_counter = 0;
    Watch *w = eld->watches + eld->watches_count++;
    w->name = name;
    w->fd = fd;
    w->events = events;
    w->enabled = enabled;
    w->callback = cb;
    w->callback_data = cb_data;
    w->free = NULL;
    w->id = ++watch_counter;
    update_fds(eld);
    return w->id;
}

#define removeX(which, item_id, update_func)                                                                                                   \
    {                                                                                                                                          \
        for (nfds_t i = 0; i < eld->which##_count; i++) {                                                                                      \
            if (eld->which[i].id == item_id) {                                                                                                 \
                eld->which##_count--;                                                                                                          \
                if (eld->which[i].callback_data && eld->which[i].free) {                                                                       \
                    eld->which[i].free(eld->which[i].id, eld->which[i].callback_data);                                                         \
                    eld->which[i].callback_data = NULL;                                                                                        \
                    eld->which[i].free = NULL;                                                                                                 \
                }                                                                                                                              \
                if (i < eld->which##_count) { memmove(eld->which + i, eld->which + i + 1, sizeof(eld->which[0]) * (eld->which##_count - i)); } \
                update_func(eld);                                                                                                              \
                break;                                                                                                                         \
            }                                                                                                                                  \
        }                                                                                                                                      \
    }

void
removeWatch(EventLoopData *eld, id_type watch_id) {
    removeX(watches, watch_id, update_fds);
}

void
toggleWatch(EventLoopData *eld, id_type watch_id, int enabled) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].id == watch_id) {
            if (eld->watches[i].enabled != enabled) {
                eld->watches[i].enabled = enabled;
                update_fds(eld);
            }
            break;
        }
    }
}

static id_type timer_counter = 0;

static int
compare_timers(const void *a_, const void *b_) {
    const Timer *a = (const Timer *)a_, *b = (const Timer *)b_;
    return (a->trigger_at > b->trigger_at) ? 1 : (a->trigger_at < b->trigger_at) ? -1 : 0;
}

static void
update_timers(EventLoopData *eld) {
    if (eld->timers_count > 1) qsort(eld->timers, eld->timers_count, sizeof(eld->timers[0]), compare_timers);
}

id_type
addTimer(
    EventLoopData *eld, const char *name, monotonic_t interval, int enabled, bool repeats, timer_callback_func cb, void *cb_data, GLFWuserdatafreefun free) {
    if (eld->timers_count >= sizeof(eld->timers) / sizeof(eld->timers[0])) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many timers added");
        return 0;
    }
    Timer *t = eld->timers + eld->timers_count++;
    t->interval = interval;
    t->name = name;
    t->trigger_at = enabled ? monotonic() + interval : MONOTONIC_T_MAX;
    t->repeats = repeats;
    t->callback = cb;
    t->callback_data = cb_data;
    t->free = free;
    t->id = ++timer_counter;
    update_timers(eld);
    return timer_counter;
}

void
removeTimer(EventLoopData *eld, id_type timer_id) {
    removeX(timers, timer_id, update_timers);
}

void
removeAllTimers(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].free && eld->timers[i].callback_data) eld->timers[i].free(eld->timers[i].id, eld->timers[i].callback_data);
    }
    eld->timers_count = 0;
}

void
toggleTimer(EventLoopData *eld, id_type timer_id, int enabled) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            monotonic_t trigger_at = enabled ? (monotonic() + eld->timers[i].interval) : MONOTONIC_T_MAX;
            if (trigger_at != eld->timers[i].trigger_at) {
                eld->timers[i].trigger_at = trigger_at;
                update_timers(eld);
            }
            break;
        }
    }
}

void
changeTimerInterval(EventLoopData *eld, id_type timer_id, monotonic_t interval) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            eld->timers[i].interval = interval;
            break;
        }
    }
}


monotonic_t
prepareForPoll(EventLoopData *eld, monotonic_t timeout) {
    for (nfds_t i = 0; i < eld->watches_count; i++) eld->fds[i].revents = 0;
    if (!eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return timeout;
    monotonic_t now = monotonic(), next_repeat_at = eld->timers[0].trigger_at;
    if (timeout < 0 || now + timeout > next_repeat_at) { timeout = next_repeat_at <= now ? 0 : next_repeat_at - now; }
    return timeout;
}

static struct timespec
calc_time(monotonic_t nsec) {
    struct timespec result;
    result.tv_sec = nsec / (1000LL * 1000LL * 1000LL);
    result.tv_nsec = nsec % (1000LL * 1000LL * 1000LL);
    return result;
}

int
pollWithTimeout(struct pollfd *fds, nfds_t nfds, monotonic_t timeout) {
    struct timespec tv = calc_time(timeout);
    return ppoll(fds, nfds, &tv, NULL);
}

static void
dispatchEvents(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *ww = eld->watches + i;
        struct pollfd *pfd = eld->fds + i;
        if (pfd->revents & ww->events) {
            ww->ready = 1;
            if (ww->callback) ww->callback(ww->fd, pfd->revents, ww->callback_data);
        } else ww->ready = 0;
    }
}

unsigned
dispatchTimers(EventLoopData *eld) {
    if (!eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return 0;
    static struct {
        timer_callback_func func;
        id_type id;
        void *data;
        bool repeats;
    } dispatches[sizeof(eld->timers) / sizeof(eld->timers[0])];
    unsigned num_dispatches = 0;
    monotonic_t now = monotonic();
    for (nfds_t i = 0; i < eld->timers_count && eld->timers[i].trigger_at <= now; i++) {
        eld->timers[i].trigger_at = now + eld->timers[i].interval;
        dispatches[num_dispatches].func = eld->timers[i].callback;
        dispatches[num_dispatches].id = eld->timers[i].id;
        dispatches[num_dispatches].data = eld->timers[i].callback_data;
        dispatches[num_dispatches].repeats = eld->timers[i].repeats;
        num_dispatches++;
    }
    // we dispatch separately so that the callbacks can modify timers
    for (unsigned i = 0; i < num_dispatches; i++) {
        dispatches[i].func(dispatches[i].id, dispatches[i].data);
        if (!dispatches[i].repeats) { removeTimer(eld, dispatches[i].id); }
    }
    if (num_dispatches) update_timers(eld);
    return num_dispatches;
}

static void
drain_wakeup_fd(int fd, EventLoopData *eld) {
    static char drain_buf[64];
    eld->wakeup_data_read = false;
    while (true) {
        ssize_t ret = read(fd, drain_buf, sizeof(drain_buf));
        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret > 0) {
            eld->wakeup_data_read = true;
            continue;
        }
        break;
    }
}

static void
mark_wakep_fd_ready(int fd UNUSED, int events UNUSED, void *data) {
    ((EventLoopData *)(data))->wakeup_fd_ready = true;
}

static void
mark_key_repeat_fd_ready(int fd UNUSED, int events UNUSED, void *data) {
    ((EventLoopData *)(data))->key_repeat_fd_ready = true;
}


bool
initPollData(EventLoopData *eld, int display_fd) {
    if (!addWatch(eld, "display", display_fd, POLLIN, 1, NULL, NULL)) return false;
#ifdef HAS_EVENT_FD
    eld->wakeupFd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (eld->wakeupFd == -1) return false;
    const int wakeup_fd = eld->wakeupFd;
#else
    if (pipe2(eld->wakeupFds, O_CLOEXEC | O_NONBLOCK) != 0) return false;
    const int wakeup_fd = eld->wakeupFds[0];
#endif
    if (!addWatch(eld, "wakeup", wakeup_fd, POLLIN, 1, mark_wakep_fd_ready, eld)) return false;

#ifdef HAS_TIMER_FD
    eld->key_repeat_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    if (eld->key_repeat_fd < 0) return false;
    const int key_repeat_fd = eld->key_repeat_fd;
#else
    if (pipe2(eld->key_repeat_fds, O_CLOEXEC | O_NONBLOCK) != 0) return false;
    const int key_repeat_fd = eld->key_repeat_fds[0];
#endif
#ifdef _GLFW_WAYLAND
    if (!addWatch(eld, "key_repeat", key_repeat_fd, POLLIN, 1, mark_key_repeat_fd_ready, eld)) return false;
#else
    (void)key_repeat_fd;
    (void)mark_key_repeat_fd_ready;
#endif
    return true;
}

void
check_for_wakeup_events(EventLoopData *eld) {
#ifdef HAS_EVENT_FD
    int fd = eld->wakeupFd;
#else
    int fd = eld->wakeupFds[0];
#endif
    drain_wakeup_fd(fd, eld);
}

void
wakeupEventLoop(EventLoopData *eld) {
#ifdef HAS_EVENT_FD
    static const uint64_t value = 1;
    while (write(eld->wakeupFd, &value, sizeof value) < 0 && (errno == EINTR || errno == EAGAIN));
#else
    while (write(eld->wakeupFds[1], "w", 1) < 0 && (errno == EINTR || errno == EAGAIN));
#endif
}

static void
closeFds(int *fds, size_t count) {
    while (count--) {
        if (*fds > 0) {
            close(*fds);
            *fds = -1;
        }
        fds++;
    }
}

void
finalizePollData(EventLoopData *eld) {
    (void)closeFds;
#ifdef HAS_EVENT_FD
    close(eld->wakeupFd);
    eld->wakeupFd = -1;
#else
    closeFds(eld->wakeupFds, arraysz(eld->wakeupFds));
#endif
#ifdef HAS_TIMER_FD
    close(eld->key_repeat_fd);
    eld->key_repeat_fd = -1;
#else
    closeFds(eld->key_repeat_fds, arraysz(eld->key_repeat_fds));
#endif
}

static int
display_fd_ready(EventLoopData *eld) {
    // watches[0] is always the display fd. Errors count as ready: the display
    // callback must complete the read rather than cancel it, so that a
    // compositor disconnect is turned into a display error instead of a poll()
    // that keeps returning immediately forever.
    return eld->fds[0].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL);
}

int
pollForEvents(EventLoopData *eld, monotonic_t timeout, watch_callback_func display_callback) {
    int read_ok = 0;
    timeout = prepareForPoll(eld, timeout);
    EVDBG("pollForEvents final timeout: %.3f", monotonic_t_to_s_double(timeout));
    int result;
    monotonic_t end_time = monotonic() + timeout;
    eld->wakeup_fd_ready = false;
    eld->key_repeat_fd_ready = false;

    while (1) {
        if (timeout >= 0) {
            errno = 0;
            result = pollWithTimeout(eld->fds, eld->watches_count, timeout);
            int saved_errno = errno;
            if (display_callback) display_callback(result, display_fd_ready(eld), NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
                break;
            }
            timeout = end_time - monotonic();
            if (timeout <= 0) break;
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        } else {
            errno = 0;
            result = poll(eld->fds, eld->watches_count, -1);
            int saved_errno = errno;
            if (display_callback) display_callback(result, display_fd_ready(eld), NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
            }
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        }
    }
    return read_ok;
}

// Converts the millisecond time of an input event to monotonic() time. The base
// of these times is unspecified and they wrap, so the event is placed by its
// age, which is measured against CLOCK_MONOTONIC, the clock compositors and X
// servers use. monotonic() runs on a different clock that drifts against that
// one, so the offset between the two is measured once and kept for as long as
// it stays right to within a millisecond. Events a number of milliseconds apart
// then come out exactly that far apart, however late each one is delivered
monotonic_t
event_time_to_monotonic(uint32_t time) {
    static monotonic_t offset = 0;
    static bool have_offset = false;
    const monotonic_t now = monotonic();
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return now;
    const monotonic_t clock_now = (monotonic_t)ts.tv_sec * MONOTONIC_T_1e9 + (monotonic_t)ts.tv_nsec, clock_ms = clock_now / MONOTONIC_T_1e6;
    const uint32_t age_ms = (uint32_t)clock_ms - time;
    // An implausible age means the event was stamped with some other clock
    if (age_ms > 1000) return now;
    const monotonic_t measured = now - clock_now;
    if (!have_offset || measured < offset || measured - offset > MONOTONIC_T_1e6) {
        // Half a millisecond below the measurement, so that the answer is
        // never later than now and the clocks have room to drift either way
        offset = measured - MONOTONIC_T_1e6 / 2;
        have_offset = true;
    }
    return ms_to_monotonic_t(clock_ms - (monotonic_t)age_ms) + offset;
}

// Duplicate a UTF-8 encoded string
// but cut it so that it has at most max_length bytes plus the null byte.
// This does not take combining characters into account.
GLFWAPI char *
utf_8_strndup(const char *source, size_t max_length) {
    if (!source) return NULL;
    size_t length = strnlen(source, max_length);
    if (length >= max_length) {
        for (length = max_length; length > 0; length--) {
            if ((source[length] & 0xC0) != 0x80) break;
        }
    }

    char *result = malloc(length + 1);
    memcpy(result, source, length);
    result[length] = 0;
    return result;
}

/*
 * Create a new, unique, anonymous file of the given size, and
 * return the file descriptor for it. The file descriptor is set
 * CLOEXEC. The file is immediately suitable for mmap()'ing
 * the given size at offset zero.
 *
 * The file should not have a permanent backing store like a disk,
 * but may have if XDG_RUNTIME_DIR is not properly implemented in OS.
 *
 * The file name is deleted from the file system.
 *
 * The file is suitable for buffer sharing between processes by
 * transmitting the file descriptor over Unix sockets using the
 * SCM_RIGHTS methods.
 *
 * posix_fallocate() is used to guarantee that disk space is available
 * for the file at the given size. If disk space is insufficient, errno
 * is set to ENOSPC. If posix_fallocate() is not supported, program may
 * receive SIGBUS on accessing mmap()'ed file contents instead.
 */
int
createAnonymousFile(off_t size) {
    int ret, fd = -1, shm_anon = 0;
#ifdef HAS_MEMFD_CREATE
    fd = glfw_memfd_create("glfw-shared", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (fd < 0) return -1;
    // We can add this seal before calling posix_fallocate(), as the file
    // is currently zero-sized anyway.
    //
    // There is also no need to check for the return value, we couldn’t do
    // anything with it anyway.
    fcntl(fd, F_ADD_SEALS, F_SEAL_SHRINK | F_SEAL_SEAL);
#elif defined(SHM_ANON)
    fd = shm_open(SHM_ANON, O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    shm_anon = 1;
#else
    static const char template[] = "/glfw-shared-XXXXXX";
    const char *path;
    char *name;

    path = getenv("XDG_RUNTIME_DIR");
    if (!path) {
        errno = ENOENT;
        return -1;
    }

    name = calloc(strlen(path) + sizeof(template), 1);
    strcpy(name, path);
    strcat(name, template);

    fd = createTmpfileCloexec(name);

    free(name);

    if (fd < 0) return -1;
#endif
    // posix_fallocate does not work on SHM descriptors
    ret = shm_anon ? ftruncate(fd, size) : posix_fallocate(fd, 0, size);
    if (ret != 0) {
        close(fd);
        errno = ret;
        return -1;
    }
    return fd;
}

// Input device nodes {{{
// The bits of the properties of an input device that say what its surface is, from linux/input-event-codes.h
#define INPUT_NODE_PROP_POINTER 1ul  // positions on it move a pointer that is somewhere else
#define INPUT_NODE_PROP_DIRECT 2ul   // it is a display, and a position on it is that place on the display

// libudev is loaded when it is first needed, and nothing is missed when it is not there
struct udev;
struct udev_device;
static struct {
    bool tried;
    void *handle;
    struct udev *(*new)(void);
    struct udev *(*unref)(struct udev *);
    struct udev_device *(*device_new_from_devnum)(struct udev *, char, dev_t);
    struct udev_device *(*device_get_parent)(struct udev_device *);
    const char *(*device_get_property_value)(struct udev_device *, const char *);
    const char *(*device_get_sysattr_value)(struct udev_device *, const char *);
    struct udev_device *(*device_unref)(struct udev_device *);
} libudev;

static bool
load_libudev(void) {
    if (libudev.tried) return libudev.handle != NULL;
    libudev.tried = true;
    void *handle = _glfw_dlopen("libudev.so.1");
    if (!handle) return false;
    glfw_dlsym(libudev.new, handle, "udev_new");
    glfw_dlsym(libudev.unref, handle, "udev_unref");
    glfw_dlsym(libudev.device_new_from_devnum, handle, "udev_device_new_from_devnum");
    glfw_dlsym(libudev.device_get_parent, handle, "udev_device_get_parent");
    glfw_dlsym(libudev.device_get_property_value, handle, "udev_device_get_property_value");
    glfw_dlsym(libudev.device_get_sysattr_value, handle, "udev_device_get_sysattr_value");
    glfw_dlsym(libudev.device_unref, handle, "udev_device_unref");
    if (!libudev.new || !libudev.unref || !libudev.device_new_from_devnum || !libudev.device_get_parent || !libudev.device_get_property_value ||
        !libudev.device_get_sysattr_value || !libudev.device_unref) {
        _glfw_dlclose(handle);
        return false;
    }
    libudev.handle = handle;
    return true;
}

// The udev device of a device node, to be released with its udev by the caller. The node is only looked at, never opened
static struct udev_device *
input_node_device(const char *path, struct udev **udev) {
    struct stat st;
    *udev = NULL;
    if (!path || !path[0] || stat(path, &st) != 0 || !S_ISCHR(st.st_mode) || !load_libudev()) return NULL;
    if (!(*udev = libudev.new())) return NULL;
    struct udev_device *dev = libudev.device_new_from_devnum(*udev, 'c', st.st_rdev);
    if (!dev) *udev = libudev.unref(*udev);
    return dev;
}

static bool
input_node_has(struct udev_device *dev, const char *property) {
    const char *value = libudev.device_get_property_value(dev, property);
    return value && value[0] == '1' && !value[1];
}

// Tablets and touch devices say how large they are and whether they are a
// display, and window systems mostly do not pass that on. What they do pass on
// is the device node, and with it the same can be had from where the system
// keeps it for everyone to read, with no access to the device: the size from
// the udev database, where udev puts what it works out from the range and the
// resolution of the position of the device, and the rest from the attributes
// of the kernel's input device in sysfs. Returns false when there is no such
// node or no libudev, and leaves at zero whatever is not said
bool
input_node_info(const char *path, InputNodeInfo *ans) {
    memset(ans, 0, sizeof(*ans));
    struct udev *udev;
    struct udev_device *dev = input_node_device(path, &udev);
    if (!dev) return false;
    ans->is_tablet = input_node_has(dev, "ID_INPUT_TABLET");
    ans->is_pad = input_node_has(dev, "ID_INPUT_TABLET_PAD");
    const char *width = libudev.device_get_property_value(dev, "ID_INPUT_WIDTH_MM"), *height = libudev.device_get_property_value(dev, "ID_INPUT_HEIGHT_MM");
    if (width && height) {
        const long w = strtol(width, NULL, 10), h = strtol(height, NULL, 10);
        if (w > 0 && h > 0 && w < 100000 && h < 100000) ans->width_mm = (int)w, ans->height_mm = (int)h;
    }
    // The node is a child of the input device, which has the rest
    struct udev_device *input = libudev.device_get_parent(dev);
    if (input) {
        const char *name = libudev.device_get_sysattr_value(input, "name"), *vendor = libudev.device_get_sysattr_value(input, "id/vendor");
        const char *product = libudev.device_get_sysattr_value(input, "id/product"), *properties = libudev.device_get_sysattr_value(input, "properties");
        if (name) snprintf(ans->name, sizeof(ans->name), "%s", name);
        if (vendor) ans->vendor = (unsigned)strtoul(vendor, NULL, 16);
        if (product) ans->product = (unsigned)strtoul(product, NULL, 16);
        if (properties) {
            // A bit set in hexadecimal words, the lowest bits in the last word
            const char *last = strrchr(properties, ' ');
            const unsigned long bits = strtoul(last ? last + 1 : properties, NULL, 16);
            ans->direct = (bits & INPUT_NODE_PROP_DIRECT) ? 1 : ((bits & INPUT_NODE_PROP_POINTER) ? -1 : 0);
        }
    }
    libudev.device_unref(dev);
    libudev.unref(udev);
    return true;
}
// }}}
