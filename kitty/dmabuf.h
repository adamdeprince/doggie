/*
 * dmabuf.h
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <sys/types.h>

// A dma-buf surface as a program names it in the graphics protocol: the
// process that has the buffer, its format and, for each plane, the descriptor
// of the buffer in that process and where the plane is in it
typedef struct DmabufPlane {
    int fd;
    uint32_t offset, stride;
} DmabufPlane;

typedef struct DmabufSpec {
    pid_t pid;
    uint32_t fourcc;
    uint64_t modifier;
    unsigned num_planes;
    DmabufPlane planes[4];
} DmabufSpec;

bool dmabuf_parse_spec(const char *spec, size_t len, DmabufSpec *ans, char *err, size_t errsz);
// Takes duplicates of the descriptors of the planes, into fds, from a process in the session of the process session_of
bool dmabuf_take_fds(const DmabufSpec *spec, pid_t session_of, int *fds, char *err, size_t errsz);
void dmabuf_close_fds(int *fds, unsigned count);
// With an EGL context current
void *dmabuf_import(const DmabufSpec *spec, const int *fds, uint32_t width, uint32_t height, char *err, size_t errsz);
bool dmabuf_bind_texture(void *surface, uint32_t *texture_id);
void dmabuf_release(void *surface);
