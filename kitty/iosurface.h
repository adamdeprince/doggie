/*
 * iosurface.h
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

void *iosurface_lookup(uint32_t id, uint32_t *width, uint32_t *height, bool *is_bgra, char *err, size_t errsz);
bool iosurface_bind_rectangle_texture(void *surface, uint32_t *texture_id, bool is_bgra);
void iosurface_release(void *surface);
