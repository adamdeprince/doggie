/*
 * vector.h
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

// A vector image: the element table of a graphics protocol f=200 image, see docs/vector-protocol.rst
typedef struct VectorDoc VectorDoc;

// Pixels of a raster image drawn by an `i` record, RGBA or RGB rows, freed by the renderer
typedef struct {
    uint8_t *data;
    unsigned width, height;
    bool is_opaque;
} VectorImageData;
typedef bool (*vector_image_lookup)(void *ctx, uint32_t image_id, VectorImageData *out);

VectorDoc *vector_doc_new(unsigned width, unsigned height);
void vector_doc_free(VectorDoc *doc);
// Applies the records in text, all or nothing. Returns NULL on success or a static error message.
const char *vector_doc_apply(VectorDoc *doc, const uint8_t *text, size_t sz);
size_t vector_doc_size(const VectorDoc *doc);
unsigned vector_doc_element_count(const VectorDoc *doc);
// Rasterizes the document into width x height straight alpha RGBA pixels, malloced, or NULL on failure
uint8_t *vector_doc_render(VectorDoc *doc, unsigned width, unsigned height, vector_image_lookup lookup, void *ctx);
