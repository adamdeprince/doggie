/*
 * vector.c
 * Copyright (C) 2026 Adam DePrince
 *
 * Distributed under terms of the GPL3 license.
 */

// Vector images for the graphics protocol: a small retained scene graph of
// paths, symbols, pen strokes, raster images and gradients, parsed from text
// records and rasterized on the CPU with analytic antialiasing. See
// docs/vector-protocol.rst for the format.

#include "vector.h"
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <math.h>
#include <ctype.h>

#define MAX_ELEMENTS (1u << 22)
#define MAX_DEPTH 64
#define TOLERANCE 0.25  // flattening error in device pixels
#define SUBSAMPLES 16   // scanlines per pixel row

// Geometry {{{

typedef struct {
    double a, b, c, d, e, f;  // x' = a x + c y + e, y' = b x + d y + f
} Mat;
static const Mat identity = {1, 0, 0, 1, 0, 0};

static Mat
mat_mul(Mat m, Mat n) {  // apply n then m
    return (Mat){
        m.a * n.a + m.c * n.b, m.b * n.a + m.d * n.b, m.a * n.c + m.c * n.d, m.b * n.c + m.d * n.d, m.a * n.e + m.c * n.f + m.e, m.b * n.e + m.d * n.f + m.f};
}

static bool
mat_invert(Mat m, Mat *out) {
    double det = m.a * m.d - m.b * m.c;
    if (fabs(det) < 1e-12) return false;
    *out = (Mat){m.d / det, -m.b / det, -m.c / det, m.a / det, (m.c * m.f - m.d * m.e) / det, (m.b * m.e - m.a * m.f) / det};
    return true;
}

static double
mat_scale(Mat m) {  // largest stretch, used to scale tolerances into user space
    double s = fmax(m.a * m.a + m.b * m.b, m.c * m.c + m.d * m.d);
    return s > 1e-18 ? sqrt(s) : 1e-9;
}

static inline void
apply(Mat m, double x, double y, double *ox, double *oy) {
    *ox = m.a * x + m.c * y + m.e;
    *oy = m.b * x + m.d * y + m.f;
}

enum { PC_MOVE, PC_LINE, PC_QUAD, PC_CUBIC, PC_CLOSE };
typedef struct {
    uint8_t op;
    double p[6];
} PathCmd;
typedef struct {
    PathCmd *item;
    size_t count, capacity;
} Path;

typedef struct {
    double *pts;  // x, y pairs
    size_t count, capacity;
    bool closed;
} Poly;
typedef struct {
    Poly *item;
    size_t count, capacity;
} PolyList;

#define GROW(arr, field, needed)                                                                 \
    if ((arr)->count + (needed) > (arr)->capacity) {                                             \
        size_t nc = (arr)->capacity ? (arr)->capacity * 2 : 16;                                  \
        while (nc < (arr)->count + (needed)) nc *= 2;                                            \
        void *np = realloc((arr)->field, nc * sizeof(*(arr)->field));                            \
        if (!np) return false;                                                                   \
        (arr)->field = np;                                                                       \
        (arr)->capacity = nc;                                                                    \
    }

static bool
path_add(Path *p, uint8_t op, const double *pts, unsigned n) {
    GROW(p, item, 1);
    PathCmd *c = p->item + p->count++;
    c->op = op;
    memset(c->p, 0, sizeof(c->p));
    if (n) memcpy(c->p, pts, n * sizeof(double));
    return true;
}

static bool
poly_add(Poly *p, double x, double y) {
    GROW(p, pts, 2);
    p->pts[p->count++] = x;
    p->pts[p->count++] = y;
    return true;
}

static Poly *
polylist_new(PolyList *pl) {
    if (pl->count + 1 > pl->capacity) {
        size_t nc = pl->capacity ? pl->capacity * 2 : 8;
        void *np = realloc(pl->item, nc * sizeof(Poly));
        if (!np) return NULL;
        pl->item = np;
        pl->capacity = nc;
    }
    Poly *ans = pl->item + pl->count++;
    memset(ans, 0, sizeof(*ans));
    return ans;
}

static void
polylist_free(PolyList *pl) {
    for (size_t i = 0; i < pl->count; i++) free(pl->item[i].pts);
    free(pl->item);
    memset(pl, 0, sizeof(*pl));
}

static Poly *
start_subpath(PolyList *out, double x, double y) {
    Poly *p = polylist_new(out);
    if (p && !poly_add(p, x, y)) return NULL;
    return p;
}

// Flattens a path into polylines, with the transform applied to the control
// points first, so that tol is in the output space.
static bool
flatten_path(const Path *path, Mat m, double tol, PolyList *out) {
    Poly *cur = NULL;
    double cx = 0, cy = 0, sx = 0, sy = 0;  // current and subpath start points, in output space
    for (size_t i = 0; i < path->count; i++) {
        const PathCmd *c = path->item + i;
        double x, y;
        switch (c->op) {
            case PC_MOVE:
                apply(m, c->p[0], c->p[1], &x, &y);
                if (!(cur = start_subpath(out, x, y))) return false;
                cx = sx = x;
                cy = sy = y;
                break;
            case PC_LINE:
                if (!cur && !(cur = start_subpath(out, cx, cy))) return false;
                apply(m, c->p[0], c->p[1], &x, &y);
                if (!poly_add(cur, x, y)) return false;
                cx = x;
                cy = y;
                break;
            case PC_QUAD:
            case PC_CUBIC: {
                if (!cur && !(cur = start_subpath(out, cx, cy))) return false;
                double x1, y1, x2, y2, x3, y3;
                apply(m, c->p[0], c->p[1], &x1, &y1);
                apply(m, c->p[2], c->p[3], &x2, &y2);
                if (c->op == PC_QUAD) {  // elevate to a cubic
                    x3 = x2, y3 = y2;
                    x2 = x1 + (x3 - x1) / 3, y2 = y1 + (y3 - y1) / 3;
                    x1 = cx + 2 * (x1 - cx) / 3, y1 = cy + 2 * (y1 - cy) / 3;
                } else apply(m, c->p[4], c->p[5], &x3, &y3);
                // Wang's formula for the number of segments needed for the error to stay below tol
                double ddx = fmax(fabs(cx - 2 * x1 + x2), fabs(x1 - 2 * x2 + x3)), ddy = fmax(fabs(cy - 2 * y1 + y2), fabs(y1 - 2 * y2 + y3));
                double dd = sqrt(ddx * ddx + ddy * ddy);
                unsigned n = (unsigned)ceil(sqrt(0.75 * dd / tol));
                if (n < 1) n = 1;
                if (n > 1024) n = 1024;
                for (unsigned k = 1; k <= n; k++) {
                    double t = (double)k / n, mt = 1 - t;
                    double w0 = mt * mt * mt, w1 = 3 * mt * mt * t, w2 = 3 * mt * t * t, w3 = t * t * t;
                    if (!poly_add(cur, w0 * cx + w1 * x1 + w2 * x2 + w3 * x3, w0 * cy + w1 * y1 + w2 * y2 + w3 * y3)) return false;
                }
                cx = x3;
                cy = y3;
            } break;
            case PC_CLOSE:
                if (!cur) break;
                cur->closed = true;
                cx = sx;
                cy = sy;
                cur = NULL;
                break;
        }
    }
    return true;
}

// }}}

// Rasterizer {{{

typedef struct {
    double x0, y0, x1, y1, slope;  // y0 < y1
    int dir;
} Edge;
typedef struct {
    Edge *item;
    size_t count, capacity;
} EdgeList;

static bool
add_edge(EdgeList *el, double x0, double y0, double x1, double y1, int dir) {
    if (y0 == y1 || !isfinite(x0) || !isfinite(y0) || !isfinite(x1) || !isfinite(y1)) return true;
    GROW(el, item, 1);
    Edge *e = el->item + el->count++;
    if (y0 > y1) {
        double t = x0;
        x0 = x1, x1 = t, t = y0, y0 = y1, y1 = t;
        dir = -dir;
    }
    *e = (Edge){x0, y0, x1, y1, (x1 - x0) / (y1 - y0), dir};
    return true;
}

// Adds the closed polygon pts (n points) transformed by m. With orient, the
// polygon is wound consistently so that overlapping pieces union under the
// nonzero rule.
static bool
add_polygon(EdgeList *el, const double *pts, size_t n, Mat m, bool orient) {
    if (n < 2) return true;
    int dir = 1;
    if (orient) {
        double area = 0;
        for (size_t i = 0; i < n; i++) {
            size_t j = (i + 1) % n;
            area += pts[2 * i] * pts[2 * j + 1] - pts[2 * j] * pts[2 * i + 1];
        }
        if (area < 0) dir = -1;
        if ((m.a * m.d - m.b * m.c) < 0) dir = -dir;
    }
    for (size_t i = 0; i < n; i++) {
        size_t j = (i + 1) % n;
        double x0, y0, x1, y1;
        apply(m, pts[2 * i], pts[2 * i + 1], &x0, &y0);
        apply(m, pts[2 * j], pts[2 * j + 1], &x1, &y1);
        if (!add_edge(el, x0, y0, x1, y1, dir)) return false;
    }
    return true;
}

typedef void (*span_fn)(void *ctx, int y, int x0, int x1, const float *cov);

typedef struct {
    double x;
    int dir;
} Crossing;

static int
cmp_edge_y(const void *a, const void *b) {
    const Edge *x = a, *y = b;
    return x->y0 < y->y0 ? -1 : x->y0 > y->y0;
}

static inline void
add_span(float *acc, double xa, double xb, double limit) {
    if (xa < 0) xa = 0;
    if (xb > limit) xb = limit;
    if (xb <= xa) return;
    const float w = 1.f / SUBSAMPLES;
    int ia = (int)xa, ib = (int)xb;
    if (ia == ib) {
        acc[ia] += (float)(xb - xa) * w;
        acc[ia + 1] -= (float)(xb - xa) * w;
    } else {
        acc[ia] += (float)(ia + 1 - xa) * w;
        acc[ia + 1] += (float)(xa - ia) * w;
        acc[ib] += (float)(xb - ib - 1) * w;
        acc[ib + 1] -= (float)(xb - ib) * w;
    }
}

// Scanline rasterization with exact horizontal and SUBSAMPLES-fold vertical
// coverage, calling fn once per row with the coverage of the covered pixels.
static bool
rasterize(EdgeList *el, bool evenodd, int W, int H, span_fn fn, void *ctx) {
    if (!el->count || W <= 0 || H <= 0) return true;
    double minx = INFINITY, maxx = -INFINITY, miny = INFINITY, maxy = -INFINITY;
    for (size_t i = 0; i < el->count; i++) {
        const Edge *e = el->item + i;
        minx = fmin(minx, fmin(e->x0, e->x1));
        maxx = fmax(maxx, fmax(e->x0, e->x1));
        miny = fmin(miny, e->y0);
        maxy = fmax(maxy, e->y1);
    }
    int bx0 = (int)fmax(0, floor(minx)), bx1 = (int)fmin(W - 1, ceil(maxx));
    int by0 = (int)fmax(0, floor(miny)), by1 = (int)fmin(H - 1, ceil(maxy));
    if (bx1 < bx0 || by1 < by0) return true;
    const int bw = bx1 - bx0 + 1;
    float *acc = calloc(bw + 2, sizeof(float)), *cov = malloc(bw * sizeof(float));
    Edge **active = malloc(el->count * sizeof(Edge *));
    Crossing *xs = malloc(el->count * sizeof(Crossing));
    bool ok = acc && cov && active && xs;
    if (ok) {
        qsort(el->item, el->count, sizeof(Edge), cmp_edge_y);
        size_t next = 0, nactive = 0;
        for (int y = by0; y <= by1; y++) {
            bool any = false;
            for (int k = 0; k < SUBSAMPLES; k++) {
                double sy = y + (k + 0.5) / SUBSAMPLES;
                while (next < el->count && el->item[next].y0 <= sy) active[nactive++] = el->item + next++;
                size_t nx = 0;
                for (size_t i = 0; i < nactive;) {
                    Edge *e = active[i];
                    if (e->y1 <= sy) {
                        active[i] = active[--nactive];
                        continue;
                    }
                    xs[nx++] = (Crossing){e->x0 + (sy - e->y0) * e->slope - bx0, e->dir};
                    i++;
                }
                if (nx < 2) continue;
                for (size_t i = 1; i < nx; i++) {  // insertion sort, crossings are few and nearly sorted
                    Crossing c = xs[i];
                    size_t j = i;
                    while (j > 0 && xs[j - 1].x > c.x) {
                        xs[j] = xs[j - 1];
                        j--;
                    }
                    xs[j] = c;
                }
                int wind = 0;
                double start = 0;
                for (size_t i = 0; i < nx; i++) {
                    bool was = evenodd ? (wind & 1) : wind != 0;
                    wind += xs[i].dir;
                    bool now = evenodd ? (wind & 1) : wind != 0;
                    if (!was && now) start = xs[i].x;
                    else if (was && !now) {
                        add_span(acc, start, xs[i].x, bw);
                        any = true;
                    }
                }
            }
            if (!any) continue;
            float run = 0;
            int first = -1, last = -1;
            for (int i = 0; i < bw; i++) {
                run += acc[i];
                float c = run < 0 ? 0 : (run > 1 ? 1 : run);
                if (c > 0.0005f) {
                    if (first < 0) first = i;
                    last = i;
                }
                cov[i] = c;
            }
            memset(acc, 0, (bw + 2) * sizeof(float));
            if (first >= 0) fn(ctx, y, bx0 + first, bx0 + last + 1, cov + first);
        }
    }
    free(acc);
    free(cov);
    free(active);
    free(xs);
    return ok;
}

// }}}

// Stroking {{{

typedef struct {
    EdgeList *edges;
    Mat m;
} StrokeOut;

static bool
emit(StrokeOut *o, const double *pts, size_t n) {
    return add_polygon(o->edges, pts, n, o->m, true);
}

static bool
emit_circle(StrokeOut *o, double cx, double cy, double r, double tol) {
    if (r <= 0) return true;
    unsigned n = r > tol ? (unsigned)ceil(M_PI / acos(1 - tol / r)) : 6;
    if (n < 6) n = 6;
    if (n > 256) n = 256;
    double *pts = malloc(2 * n * sizeof(double));
    if (!pts) return false;
    for (unsigned i = 0; i < n; i++) {
        double a = 2 * M_PI * i / n;
        pts[2 * i] = cx + r * cos(a);
        pts[2 * i + 1] = cy + r * sin(a);
    }
    bool ok = emit(o, pts, n);
    free(pts);
    return ok;
}

enum { CAP_BUTT, CAP_ROUND, CAP_SQUARE };
enum { JOIN_MITER, JOIN_ROUND, JOIN_BEVEL };

static bool
emit_join(StrokeOut *o, double vx, double vy, double d0x, double d0y, double d1x, double d1y, double hw, int join, double miter_limit, double tol) {
    double cross = d0x * d1y - d0y * d1x;
    if (join == JOIN_ROUND) return emit_circle(o, vx, vy, hw, tol);
    if (fabs(cross) < 1e-9) return true;
    // outer side of the turn, where the segment quads leave a gap
    double s = cross > 0 ? -1 : 1;
    double u0x = -d0y * s, u0y = d0x * s, u1x = -d1y * s, u1y = d1x * s;
    double o0x = vx + u0x * hw, o0y = vy + u0y * hw, o1x = vx + u1x * hw, o1y = vy + u1y * hw;
    if (join == JOIN_MITER) {
        double bx = u0x + u1x, by = u0y + u1y, bl = bx * bx + by * by;
        if (bl > 1e-12 && 2 / sqrt(bl) <= miter_limit) {
            double tx = vx + bx * hw * 2 / bl, ty = vy + by * hw * 2 / bl;
            double q[8] = {vx, vy, o0x, o0y, tx, ty, o1x, o1y};
            return emit(o, q, 4);
        }
    }
    double t[6] = {vx, vy, o0x, o0y, o1x, o1y};
    return emit(o, t, 3);
}

static bool
emit_cap(StrokeOut *o, double px, double py, double dx, double dy, double hw, int cap, double tol) {
    // dx, dy points outward from the stroke
    switch (cap) {
        case CAP_ROUND: return emit_circle(o, px, py, hw, tol);
        case CAP_SQUARE: {
            double nx = -dy * hw, ny = dx * hw, ex = dx * hw, ey = dy * hw;
            double q[8] = {px + nx, py + ny, px + nx + ex, py + ny + ey, px - nx + ex, py - ny + ey, px - nx, py - ny};
            return emit(o, q, 4);
        }
    }
    return true;
}

// Removes repeated points. Returns the number of points left.
static size_t
dedupe(double *pts, size_t n) {
    size_t out = 0;
    for (size_t i = 0; i < n; i++) {
        if (out && fabs(pts[2 * i] - pts[2 * out - 2]) < 1e-9 && fabs(pts[2 * i + 1] - pts[2 * out - 1]) < 1e-9) continue;
        pts[2 * out] = pts[2 * i];
        pts[2 * out + 1] = pts[2 * i + 1];
        out++;
    }
    return out;
}

static bool
stroke_polyline(StrokeOut *o, double *pts, size_t n, bool closed, double hw, int cap, int join, double miter_limit, double tol) {
    n = dedupe(pts, n);
    if (closed && n > 2 && fabs(pts[0] - pts[2 * n - 2]) < 1e-9 && fabs(pts[1] - pts[2 * n - 1]) < 1e-9) n--;
    if (n == 1) return cap == CAP_BUTT ? true : (cap == CAP_ROUND ? emit_circle(o, pts[0], pts[1], hw, tol) : emit_cap(o, pts[0], pts[1], 1, 0, hw, CAP_SQUARE, tol));
    if (n < 2) return true;
    if (n == 2) closed = false;
    size_t nseg = closed ? n : n - 1;
    double pdx = 0, pdy = 0;
    for (size_t i = 0; i < nseg; i++) {
        size_t j = (i + 1) % n;
        double x0 = pts[2 * i], y0 = pts[2 * i + 1], x1 = pts[2 * j], y1 = pts[2 * j + 1];
        double dx = x1 - x0, dy = y1 - y0, len = sqrt(dx * dx + dy * dy);
        dx /= len, dy /= len;
        double nx = -dy * hw, ny = dx * hw;
        double q[8] = {x0 + nx, y0 + ny, x1 + nx, y1 + ny, x1 - nx, y1 - ny, x0 - nx, y0 - ny};
        if (!emit(o, q, 4)) return false;
        if (i > 0 && !emit_join(o, x0, y0, pdx, pdy, dx, dy, hw, join, miter_limit, tol)) return false;
        pdx = dx, pdy = dy;
    }
    if (closed) {
        double dx = pts[2] - pts[0], dy = pts[3] - pts[1], len = sqrt(dx * dx + dy * dy);
        if (!emit_join(o, pts[0], pts[1], pdx, pdy, dx / len, dy / len, hw, join, miter_limit, tol)) return false;
    } else {
        double dx = pts[0] - pts[2], dy = pts[1] - pts[3], len = sqrt(dx * dx + dy * dy);
        if (!emit_cap(o, pts[0], pts[1], dx / len, dy / len, hw, cap, tol)) return false;
        if (!emit_cap(o, pts[2 * n - 2], pts[2 * n - 1], pdx, pdy, hw, cap, tol)) return false;
    }
    return true;
}

// Splits a polyline into the "on" pieces of the dash pattern
static bool
dash_polyline(const Poly *p, const double *dash, unsigned ndash, double phase, PolyList *out) {
    double total = 0;
    for (unsigned i = 0; i < ndash; i++) total += dash[i];
    size_t n = p->count / 2;
    if (total <= 0 || n < 2) {
        Poly *q = polylist_new(out);
        if (!q) return false;
        q->closed = p->closed;
        for (size_t i = 0; i < n; i++)
            if (!poly_add(q, p->pts[2 * i], p->pts[2 * i + 1])) return false;
        return true;
    }
    unsigned idx = 0;
    double left = dash[0];
    bool on = true;
    phase = fmod(phase, total * (ndash & 1 ? 2 : 1));
    if (phase < 0) phase += total * (ndash & 1 ? 2 : 1);
    while (phase > 0) {
        if (phase >= left) {
            phase -= left;
            idx = (idx + 1) % ndash;
            left = dash[idx];
            on = !on;
        } else {
            left -= phase;
            phase = 0;
        }
    }
    Poly *cur = NULL;
    size_t nseg = p->closed ? n : n - 1;
    for (size_t i = 0; i < nseg; i++) {
        size_t j = (i + 1) % n;
        double x0 = p->pts[2 * i], y0 = p->pts[2 * i + 1], x1 = p->pts[2 * j], y1 = p->pts[2 * j + 1];
        double len = hypot(x1 - x0, y1 - y0), pos = 0;
        if (on && !cur) {
            if (!(cur = polylist_new(out)) || !poly_add(cur, x0, y0)) return false;
        }
        while (len - pos > left) {
            pos += left;
            double t = pos / len, x = x0 + (x1 - x0) * t, y = y0 + (y1 - y0) * t;
            if (on) {
                if (!poly_add(cur, x, y)) return false;
                cur = NULL;
            } else {
                if (!(cur = polylist_new(out)) || !poly_add(cur, x, y)) return false;
            }
            on = !on;
            idx = (idx + 1) % ndash;
            left = dash[idx];
        }
        left -= len - pos;
        if (on && !poly_add(cur, x1, y1)) return false;
    }
    return true;
}

// }}}

// Elements {{{

enum { PAINT_NONE, PAINT_SOLID, PAINT_GRADIENT };
typedef struct {
    uint8_t type, r, g, b, a;
    uint32_t gradient;
} Paint;
typedef struct {
    double offset;
    uint8_t r, g, b, a;
} Stop;
enum { BLEND_NORMAL, BLEND_MULTIPLY, BLEND_SCREEN };

typedef struct {
    uint32_t id, parent, ref;  // ref: clip path of a group, symbol of a use, image of an image
    char type;
    bool has_t, visible, has_focus, in_progress;
    Mat t;
    Path path;  // p and s
    double *pts;  // k: x, y, width triples
    size_t npts;
    Paint fill, stroke;
    double width, miter_limit, dash_phase;
    double *dash;
    unsigned ndash;
    uint8_t rule, cap, join, opacity, blend;
    double g[5];  // l: x1 y1 x2 y2, r: cx cy r fx fy
    Stop *stops;
    unsigned nstops;
    size_t slot, bytes;
} Elem;

#define NAME elem_map
#define KEY_TY uint32_t
#define VAL_TY Elem *
#include "kitty-verstable.h"

struct VectorDoc {
    unsigned width, height;
    elem_map by_id;
    Elem **order;  // creation order, NULL where deleted
    size_t count, capacity, live;
    size_t used_bytes;
    Elem root;
};

static void
elem_free(Elem *e) {
    if (!e) return;
    free(e->path.item);
    free(e->pts);
    free(e->dash);
    free(e->stops);
    free(e);
}

static Elem *
elem_new(void) {
    Elem *e = calloc(1, sizeof(Elem));
    if (!e) return NULL;
    e->t = identity;
    e->visible = true;
    e->width = 1;
    e->miter_limit = 4;
    e->opacity = 100;
    e->fill.type = PAINT_NONE;
    e->stroke.type = PAINT_NONE;
    return e;
}

VectorDoc *
vector_doc_new(unsigned width, unsigned height) {
    VectorDoc *d = calloc(1, sizeof(VectorDoc));
    if (!d) return NULL;
    d->width = width;
    d->height = height;
    vt_init(&d->by_id);
    d->root.t = identity;
    d->root.visible = true;
    d->root.opacity = 100;
    d->root.type = 'g';
    return d;
}

void
vector_doc_free(VectorDoc *d) {
    if (!d) return;
    for (size_t i = 0; i < d->count; i++) elem_free(d->order[i]);
    free(d->order);
    vt_cleanup(&d->by_id);
    free(d);
}

size_t
vector_doc_size(const VectorDoc *d) {
    return d->used_bytes;
}

unsigned
vector_doc_element_count(const VectorDoc *d) {
    return (unsigned)d->live;
}

static Elem *
lookup(const VectorDoc *d, uint32_t id) {
    elem_map_itr i = vt_get((elem_map *)&d->by_id, id);
    return vt_is_end(i) ? NULL : i.data->val;
}

static void
remove_elem(VectorDoc *d, Elem *e) {
    vt_erase(&d->by_id, e->id);
    d->order[e->slot] = NULL;
    d->used_bytes -= e->bytes;
    d->live--;
    elem_free(e);
}

static void
compact(VectorDoc *d) {
    if (d->count < 64 || d->live * 2 > d->count) return;
    size_t out = 0;
    for (size_t i = 0; i < d->count; i++) {
        if (!d->order[i]) continue;
        d->order[i]->slot = out;
        d->order[out++] = d->order[i];
    }
    d->count = out;
}

// Puts e into the document, replacing any element with the same id in place
static bool
insert_elem(VectorDoc *d, Elem *e) {
    Elem *old = lookup(d, e->id);
    if (old) {
        e->slot = old->slot;
        d->order[e->slot] = e;
        vt_erase(&d->by_id, old->id);
        d->used_bytes -= old->bytes;
        elem_free(old);
        d->live--;
    } else {
        if (d->live >= MAX_ELEMENTS) return false;
        if (d->count + 1 > d->capacity) {
            size_t nc = d->capacity ? d->capacity * 2 : 64;
            void *np = realloc(d->order, nc * sizeof(Elem *));
            if (!np) return false;
            d->order = np;
            d->capacity = nc;
        }
        e->slot = d->count;
        d->order[d->count++] = e;
    }
    if (vt_is_end(vt_insert(&d->by_id, e->id, e))) return false;
    d->used_bytes += e->bytes;
    d->live++;
    return true;
}

static bool
is_descendant(const VectorDoc *d, const Elem *e, uint32_t gid) {
    unsigned depth = 0;
    for (uint32_t p = e->parent; depth < MAX_DEPTH; depth++) {
        if (p == gid) return true;
        if (!p) return false;
        Elem *g = lookup(d, p);
        if (!g || g->type != 'g') return false;
        p = g->parent;
    }
    return false;
}

static void
delete_group(VectorDoc *d, uint32_t gid) {
    // mark first, the parent chains are looked up through groups that are about to go
    for (size_t i = 0; i < d->count; i++) {
        Elem *e = d->order[i];
        if (e) e->in_progress = e->id == gid || is_descendant(d, e, gid);
    }
    for (size_t i = 0; i < d->count; i++) {
        Elem *e = d->order[i];
        if (e && e->in_progress) remove_elem(d, e);
    }
}

// }}}

// Record parsing {{{

static const char *parse_error;

#define FAIL(msg)              \
    {                          \
        parse_error = (msg);   \
        return false;          \
    }

static bool
parse_num(const char **s, const char *end, double *out) {
    const char *p = *s;
    while (p < end && *p == ',') p++;
    if (p >= end) return false;
    char buf[64];
    size_t n = 0;
    while (p < end && n < sizeof(buf) - 1 && (isdigit((unsigned char)*p) || *p == '-' || *p == '+' || *p == '.' || *p == 'e' || *p == 'E')) {
        // a sign starts a new number unless it follows an exponent
        if (n && (*p == '-' || *p == '+') && buf[n - 1] != 'e' && buf[n - 1] != 'E') break;
        buf[n++] = *p++;
    }
    if (!n) return false;
    buf[n] = 0;
    char *e;
    *out = strtod(buf, &e);
    if (*e || !isfinite(*out)) return false;
    *s = p;
    return true;
}

static bool
parse_nums(const char **s, const char *end, double *out, unsigned n) {
    for (unsigned i = 0; i < n; i++)
        if (!parse_num(s, end, out + i)) return false;
    return true;
}

static bool
parse_path(const char *s, const char *end, Path *path) {
    double cx = 0, cy = 0, sx = 0, sy = 0, lcx = 0, lcy = 0;  // current point, subpath start, last control point
    char cmd = 0, last = 0;
    while (s < end) {
        if (*s == ',') {
            s++;
            continue;
        }
        if (isalpha((unsigned char)*s)) cmd = *s++;
        else if (!cmd) FAIL("Path data must start with a command");
        bool rel = islower((unsigned char)cmd);
        double v[6];
        switch (toupper((unsigned char)cmd)) {
            case 'M':
                if (!parse_nums(&s, end, v, 2)) FAIL("Bad moveto in path");
                if (rel) v[0] += cx, v[1] += cy;
                cx = sx = v[0], cy = sy = v[1];
                if (!path_add(path, PC_MOVE, v, 2)) FAIL("Out of memory");
                cmd = rel ? 'l' : 'L';  // further pairs are implicit linetos
                break;
            case 'L':
                if (!parse_nums(&s, end, v, 2)) FAIL("Bad lineto in path");
                if (rel) v[0] += cx, v[1] += cy;
                cx = v[0], cy = v[1];
                if (!path_add(path, PC_LINE, v, 2)) FAIL("Out of memory");
                break;
            case 'H':
                if (!parse_nums(&s, end, v, 1)) FAIL("Bad lineto in path");
                v[0] += rel ? cx : 0, v[1] = cy;
                cx = v[0];
                if (!path_add(path, PC_LINE, v, 2)) FAIL("Out of memory");
                break;
            case 'V':
                if (!parse_nums(&s, end, v + 1, 1)) FAIL("Bad lineto in path");
                v[0] = cx, v[1] += rel ? cy : 0;
                cy = v[1];
                if (!path_add(path, PC_LINE, v, 2)) FAIL("Out of memory");
                break;
            case 'C':
                if (!parse_nums(&s, end, v, 6)) FAIL("Bad curveto in path");
                if (rel)
                    for (unsigned i = 0; i < 6; i += 2) v[i] += cx, v[i + 1] += cy;
                lcx = v[2], lcy = v[3], cx = v[4], cy = v[5];
                if (!path_add(path, PC_CUBIC, v, 6)) FAIL("Out of memory");
                break;
            case 'S':
                if (!parse_nums(&s, end, v + 2, 4)) FAIL("Bad curveto in path");
                if (rel)
                    for (unsigned i = 2; i < 6; i += 2) v[i] += cx, v[i + 1] += cy;
                if (last == 'C' || last == 'S') v[0] = 2 * cx - lcx, v[1] = 2 * cy - lcy;
                else v[0] = cx, v[1] = cy;
                lcx = v[2], lcy = v[3], cx = v[4], cy = v[5];
                if (!path_add(path, PC_CUBIC, v, 6)) FAIL("Out of memory");
                break;
            case 'Q':
                if (!parse_nums(&s, end, v, 4)) FAIL("Bad curveto in path");
                if (rel)
                    for (unsigned i = 0; i < 4; i += 2) v[i] += cx, v[i + 1] += cy;
                lcx = v[0], lcy = v[1], cx = v[2], cy = v[3];
                if (!path_add(path, PC_QUAD, v, 4)) FAIL("Out of memory");
                break;
            case 'T':
                if (!parse_nums(&s, end, v + 2, 2)) FAIL("Bad curveto in path");
                if (rel) v[2] += cx, v[3] += cy;
                if (last == 'Q' || last == 'T') v[0] = 2 * cx - lcx, v[1] = 2 * cy - lcy;
                else v[0] = cx, v[1] = cy;
                lcx = v[0], lcy = v[1], cx = v[2], cy = v[3];
                if (!path_add(path, PC_QUAD, v, 4)) FAIL("Out of memory");
                break;
            case 'Z':
                cx = sx, cy = sy;
                if (!path_add(path, PC_CLOSE, NULL, 0)) FAIL("Out of memory");
                break;
            default: FAIL("Unknown path command");
        }
        last = toupper((unsigned char)cmd);
    }
    return true;
}

static bool
parse_color(const char *s, const char *end, Paint *p) {
    size_t n = end - s;
    if (n == 4 && !memcmp(s, "none", 4)) {
        p->type = PAINT_NONE;
        return true;
    }
    if (n > 1 && *s == '@') {
        double id;
        s++;
        if (!parse_num(&s, end, &id) || s != end || id < 0 || id > UINT32_MAX) FAIL("Bad gradient reference");
        p->type = PAINT_GRADIENT;
        p->gradient = (uint32_t)id;
        return true;
    }
    if (n < 7 || *s != '#') FAIL("Bad color");
    const char *star = memchr(s, '*', n);  // HDR brightness suffix, accepted and shown at SDR
    size_t hexlen = (star ? (size_t)(star - s) : n) - 1;
    if (hexlen != 6 && hexlen != 8) FAIL("Bad color");
    unsigned v[4] = {0, 0, 0, 255};
    for (size_t i = 0; i < hexlen / 2; i++) {
        unsigned x = 0;
        for (int k = 0; k < 2; k++) {
            char c = s[1 + 2 * i + k];
            x <<= 4;
            if (c >= '0' && c <= '9') x |= c - '0';
            else if (c >= 'a' && c <= 'f') x |= c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') x |= c - 'A' + 10;
            else FAIL("Bad color");
        }
        v[i] = x;
    }
    if (star) {
        double b;
        const char *q = star + 1;
        if (!parse_num(&q, end, &b) || q != end) FAIL("Bad brightness");
    }
    p->type = PAINT_SOLID;
    p->r = v[0], p->g = v[1], p->b = v[2], p->a = v[3];
    return true;
}

static bool
parse_list(const char *s, const char *end, double **out, size_t *count) {
    size_t n = 0, cap = 0;
    double *arr = NULL;
    while (s < end) {
        double v;
        if (!parse_num(&s, end, &v)) {
            free(arr);
            FAIL("Bad number list");
        }
        if (n == cap) {
            cap = cap ? cap * 2 : 16;
            void *np = realloc(arr, cap * sizeof(double));
            if (!np) {
                free(arr);
                FAIL("Out of memory");
            }
            arr = np;
        }
        arr[n++] = v;
    }
    *out = arr;
    *count = n;
    return true;
}

static int
cmp_stop(const void *a, const void *b) {
    const Stop *x = a, *y = b;
    return x->offset < y->offset ? -1 : x->offset > y->offset;
}

static bool
parse_stops(const char *s, const char *end, Elem *e) {
    unsigned cap = 0;
    while (s < end) {
        double off;
        if (!parse_num(&s, end, &off)) FAIL("Bad gradient stop");
        if (s >= end || *s != ',') FAIL("Bad gradient stop");
        s++;
        const char *c = memchr(s, ',', end - s);
        if (!c) c = end;
        Paint p;
        if (!parse_color(s, c, &p) || p.type != PAINT_SOLID) FAIL("Bad gradient stop color");
        s = c;
        if (e->nstops == cap) {
            cap = cap ? cap * 2 : 4;
            void *np = realloc(e->stops, cap * sizeof(Stop));
            if (!np) FAIL("Out of memory");
            e->stops = np;
        }
        e->stops[e->nstops++] = (Stop){fmin(1, fmax(0, off)), p.r, p.g, p.b, p.a};
    }
    if (!e->nstops) FAIL("Gradient without stops");
    qsort(e->stops, e->nstops, sizeof(Stop), cmp_stop);
    return true;
}

static bool
parse_choice(const char *s, const char *end, const char *const *names, unsigned n, uint8_t *out) {
    for (unsigned i = 0; i < n; i++)
        if (strlen(names[i]) == (size_t)(end - s) && !memcmp(s, names[i], end - s)) {
            *out = i;
            return true;
        }
    FAIL("Unknown keyword");
}

static bool
parse_uint(const char *s, const char *end, uint32_t *out) {
    double v;
    if (!parse_num(&s, end, &v) || s != end || v < 0 || v > UINT32_MAX || v != floor(v)) FAIL("Bad integer");
    *out = (uint32_t)v;
    return true;
}

typedef struct {
    char op;  // record type, or 'x' with id/all for deletes
    Elem *elem;
    uint32_t id;
    bool have_id, have_g, all, delete_group, have_d, have_pts, have_fill, have_stroke, have_cap;
} Record;

static bool
parse_field(Record *r, const char *key, size_t klen, const char *v, const char *end) {
    Elem *e = r->elem;
    double d;
#define IS(k) (klen == strlen(k) && !memcmp(key, k, klen))
#define NUM(field)                                   \
    {                                                \
        const char *q = v;                           \
        if (!parse_num(&q, end, &d) || q != end) FAIL("Bad number"); \
        field = d;                                   \
    }
    if (IS("id")) {
        if (!parse_uint(v, end, &e->id)) return false;
        r->have_id = true;
    } else if (IS("g")) {
        uint32_t g;
        if (!parse_uint(v, end, &g)) return false;
        if (r->op == 'x') r->id = g, r->delete_group = true;
        else e->parent = g;
        r->have_g = true;
    } else if (IS("p")) {
        if (!parse_uint(v, end, &e->parent)) return false;
    } else if (IS("t")) {
        double m[6];
        const char *q = v;
        if (!parse_nums(&q, end, m, 6) || q != end) FAIL("Bad transform");
        e->t = (Mat){m[0], m[1], m[2], m[3], m[4], m[5]};
        e->has_t = true;
    } else if (IS("clip") || IS("s") || IS("img")) {
        if (!parse_uint(v, end, &e->ref)) return false;
    } else if (IS("o")) {
        NUM(d);
        e->opacity = (uint8_t)fmin(100, fmax(0, d));
    } else if (IS("blend")) {
        static const char *const names[] = {"normal", "multiply", "screen"};
        if (!parse_choice(v, end, names, 3, &e->blend)) return false;
    } else if (IS("v")) {
        NUM(d);
        e->visible = d != 0;
    } else if (IS("d")) {
        if (!parse_path(v, end, &e->path)) return false;
        r->have_d = true;
    } else if (IS("fill")) {
        if (!parse_color(v, end, &e->fill)) return false;
        r->have_fill = true;
    } else if (IS("stroke")) {
        if (!parse_color(v, end, &e->stroke)) return false;
        r->have_stroke = true;
    } else if (IS("rule")) {
        static const char *const names[] = {"nz", "eo"};
        if (!parse_choice(v, end, names, 2, &e->rule)) return false;
    } else if (IS("w")) {
        NUM(e->width);
    } else if (IS("cap")) {
        static const char *const names[] = {"butt", "round", "square"};
        if (!parse_choice(v, end, names, 3, &e->cap)) return false;
        r->have_cap = true;
    } else if (IS("join")) {
        static const char *const names[] = {"miter", "round", "bevel"};
        if (!parse_choice(v, end, names, 3, &e->join)) return false;
    } else if (IS("ml")) {
        NUM(e->miter_limit);
    } else if (IS("dash")) {
        size_t n;
        free(e->dash);
        e->dash = NULL;
        if (!parse_list(v, end, &e->dash, &n)) return false;
        e->ndash = (unsigned)n;
        for (unsigned i = 0; i < e->ndash; i++)
            if (e->dash[i] < 0) FAIL("Negative dash length");
    } else if (IS("dp")) {
        NUM(e->dash_phase);
    } else if (IS("pts")) {
        size_t n;
        free(e->pts);
        e->pts = NULL;
        if (!parse_list(v, end, &e->pts, &n)) return false;
        if (n % 3) FAIL("Pen points must be x,y,width triples");
        e->npts = n / 3;
        r->have_pts = true;
    } else if (IS("x1")) {
        NUM(e->g[0]);
    } else if (IS("y1")) {
        NUM(e->g[1]);
    } else if (IS("x2")) {
        NUM(e->g[2]);
    } else if (IS("y2")) {
        NUM(e->g[3]);
    } else if (IS("cx")) {
        NUM(e->g[0]);
    } else if (IS("cy")) {
        NUM(e->g[1]);
    } else if (IS("r")) {
        NUM(e->g[2]);
    } else if (IS("fx")) {
        NUM(e->g[3]);
        e->has_focus = true;
    } else if (IS("fy")) {
        NUM(e->g[4]);
        e->has_focus = true;
    } else if (IS("stops")) {
        if (!parse_stops(v, end, e)) return false;
    }  // unknown keys are ignored for forward compatibility
#undef IS
#undef NUM
    return true;
}

static bool
parse_record(const char *line, const char *end, Record *r) {
    memset(r, 0, sizeof(*r));
    while (line < end && *line == ' ') line++;
    if (line >= end) return true;  // blank
    r->op = *line++;
    if (line < end && *line != ' ') FAIL("Record type must be a single character");
    if (!strchr("gpsuikalrx", r->op)) {
        r->op = 0;  // unknown record types are ignored for forward compatibility
        return true;
    }
    if (!(r->elem = elem_new())) FAIL("Out of memory");
    Elem *e = r->elem;
    e->type = r->op;
    while (line < end) {
        while (line < end && *line == ' ') line++;
        if (line >= end) break;
        const char *tok_end = memchr(line, ' ', end - line);
        if (!tok_end) tok_end = end;
        const char *eq = memchr(line, '=', tok_end - line);
        if (!eq) {
            if (r->op == 'x' && tok_end - line == 3 && !memcmp(line, "all", 3)) r->all = true;
            else FAIL("Field without =");
        } else if (!parse_field(r, line, eq - line, eq + 1, tok_end)) return false;
        line = tok_end;
    }
    if (r->op == 'x') {
        if (!r->all && !r->have_id && !r->have_g) FAIL("Delete record without id, g or all");
        if (!r->delete_group) r->id = e->id;
        return true;
    }
    if (!r->have_id) FAIL("Record without id");
    if (!e->id && r->op != 'g') FAIL("Only the root group has id 0");
    r->id = e->id;
    switch (r->op) {
        case 'p':
        case 's':
            if (!r->have_d) FAIL("Path without d");
            if (!r->have_fill && !r->have_stroke) e->fill = (Paint){PAINT_SOLID, 0, 0, 0, 255, 0};
            break;
        case 'u':
            if (!e->ref) FAIL("Use without s");
            if (!r->have_fill && !r->have_stroke) e->fill = (Paint){PAINT_SOLID, 0, 0, 0, 255, 0};
            break;
        case 'i':
            if (!e->ref) FAIL("Image without img");
            break;
        case 'k':
            if (!r->have_pts) FAIL("Pen without pts");
            if (!r->have_fill) e->fill = (Paint){PAINT_SOLID, 0, 0, 0, 255, 0};
            if (!r->have_cap) e->cap = CAP_ROUND;
            break;
        case 'a':
            if (!r->have_d && !r->have_pts) FAIL("Append without d or pts");
            break;
        case 'l':
        case 'r':
            if (!e->nstops) FAIL("Gradient without stops");
            break;
    }
    e->bytes = sizeof(Elem) + e->path.count * sizeof(PathCmd) + e->npts * 3 * sizeof(double) + e->ndash * sizeof(double) + e->nstops * sizeof(Stop);
    return true;
}

static bool
append_geometry(VectorDoc *d, Elem *target, Elem *src) {
    if (src->path.count) {
        if (target->type != 'p' && target->type != 's') return false;
        GROW(&target->path, item, src->path.count);
        memcpy(target->path.item + target->path.count, src->path.item, src->path.count * sizeof(PathCmd));
        target->path.count += src->path.count;
        d->used_bytes += src->path.count * sizeof(PathCmd);
        target->bytes += src->path.count * sizeof(PathCmd);
    }
    if (src->npts) {
        if (target->type != 'k') return false;
        size_t n = (target->npts + src->npts) * 3;
        void *np = realloc(target->pts, n * sizeof(double));
        if (!np) return false;
        target->pts = np;
        memcpy(target->pts + target->npts * 3, src->pts, src->npts * 3 * sizeof(double));
        target->npts += src->npts;
        d->used_bytes += src->npts * 3 * sizeof(double);
        target->bytes += src->npts * 3 * sizeof(double);
    }
    return true;
}

const char *
vector_doc_apply(VectorDoc *d, const uint8_t *text, size_t sz) {
    Record *recs = NULL;
    size_t nrecs = 0, cap = 0;
    const char *s = (const char *)text, *end = s + sz;
    static char errbuf[128];
    const char *err = NULL;
    unsigned lineno = 0;
    while (s < end) {
        const char *nl = memchr(s, '\n', end - s);
        const char *le = nl ? nl : end;
        if (le > s && le[-1] == '\r') le--;
        lineno++;
        if (nrecs == cap) {
            cap = cap ? cap * 2 : 64;
            void *np = realloc(recs, cap * sizeof(Record));
            if (!np) {
                err = "Out of memory";
                break;
            }
            recs = np;
        }
        parse_error = NULL;
        if (!parse_record(s, le, recs + nrecs)) {
            snprintf(errbuf, sizeof(errbuf), "Line %u: %s", lineno, parse_error ? parse_error : "Bad record");
            err = errbuf;
            nrecs++;
            break;
        }
        nrecs++;
        s = nl ? nl + 1 : end;
    }
    if (!err) {
        for (size_t i = 0; i < nrecs; i++) {
            Record *r = recs + i;
            switch (r->op) {
                case 0: break;
                case 'x':
                    if (r->all) {
                        for (size_t k = 0; k < d->count; k++)
                            if (d->order[k]) remove_elem(d, d->order[k]);
                        d->count = 0;
                        d->root.t = identity;
                        d->root.has_t = false;
                        d->root.ref = 0;
                        d->root.opacity = 100;
                        d->root.blend = BLEND_NORMAL;
                        d->root.visible = true;
                    } else if (r->delete_group) delete_group(d, r->id);
                    else {
                        Elem *e = lookup(d, r->id);
                        if (e) remove_elem(d, e);
                    }
                    break;
                case 'a': {
                    Elem *e = lookup(d, r->id);
                    if (e && !append_geometry(d, e, r->elem)) err = "Append to an element of another kind";
                } break;
                case 'g':
                    if (!r->elem->id) {  // the root group
                        d->root.t = r->elem->t;
                        d->root.has_t = r->elem->has_t;
                        d->root.ref = r->elem->ref;
                        d->root.opacity = r->elem->opacity;
                        d->root.blend = r->elem->blend;
                        d->root.visible = r->elem->visible;
                        break;
                    }
                    /* fallthrough */
                default:
                    if (!insert_elem(d, r->elem)) err = "Too many elements";
                    else r->elem = NULL;  // now owned by the document
                    break;
            }
            if (err) break;
        }
        compact(d);
    }
    for (size_t i = 0; i < nrecs; i++) elem_free(recs[i].elem);
    free(recs);
    return err;
}

// }}}

// Rendering {{{

typedef struct {
    uint8_t *px;  // premultiplied RGBA
    int W, H;
} Canvas;

enum { FILL_SOLID, FILL_LINEAR, FILL_RADIAL, FILL_IMAGE };

typedef struct {
    Canvas *canvas;
    const uint8_t *clip;  // W*H coverage mask or NULL
    int type;
    uint8_t blend;
    float r, g, b, a;  // premultiplied solid color
    float opacity;
    const Elem *grad;
    Mat inv;  // device to paint space
    const VectorImageData *img;
} Fill;

typedef struct {
    VectorDoc *doc;
    Elem **sorted;  // live elements sorted by parent then slot
    size_t nsorted;
    int W, H;
    vector_image_lookup lookup;
    void *lookup_ctx;
    bool failed;
} Render;

static inline float
clampf(float x) {
    return x < 0 ? 0 : (x > 1 ? 1 : x);
}

static void
eval_stops(const Elem *g, double t, float *r, float *gg, float *b, float *a) {
    const Stop *st = g->stops;
    unsigned n = g->nstops;
    if (t <= st[0].offset || n == 1) {
        *r = st[0].r, *gg = st[0].g, *b = st[0].b, *a = st[0].a;
    } else if (t >= st[n - 1].offset) {
        *r = st[n - 1].r, *gg = st[n - 1].g, *b = st[n - 1].b, *a = st[n - 1].a;
    } else {
        unsigned i = 1;
        while (i < n - 1 && st[i].offset < t) i++;
        double span = st[i].offset - st[i - 1].offset, f = span > 0 ? (t - st[i - 1].offset) / span : 0;
        *r = st[i - 1].r + (st[i].r - st[i - 1].r) * f;
        *gg = st[i - 1].g + (st[i].g - st[i - 1].g) * f;
        *b = st[i - 1].b + (st[i].b - st[i - 1].b) * f;
        *a = st[i - 1].a + (st[i].a - st[i - 1].a) * f;
    }
    *r /= 255, *gg /= 255, *b /= 255, *a /= 255;
}

static inline void
sample_image(const VectorImageData *img, double u, double v, float *r, float *g, float *b, float *a) {
    const unsigned bpp = img->is_opaque ? 3 : 4;
    double fx = u - 0.5, fy = v - 0.5;
    int x0 = (int)floor(fx), y0 = (int)floor(fy);
    float tx = (float)(fx - x0), ty = (float)(fy - y0), acc[4] = {0, 0, 0, 0};
    for (int j = 0; j < 2; j++) {
        int y = y0 + j;
        if (y < 0) y = 0;
        if (y >= (int)img->height) y = img->height - 1;
        for (int i = 0; i < 2; i++) {
            int x = x0 + i;
            if (x < 0) x = 0;
            if (x >= (int)img->width) x = img->width - 1;
            const uint8_t *p = img->data + ((size_t)y * img->width + x) * bpp;
            float w = (i ? tx : 1 - tx) * (j ? ty : 1 - ty), pa = img->is_opaque ? 255 : p[3];
            acc[0] += p[0] * pa * w;
            acc[1] += p[1] * pa * w;
            acc[2] += p[2] * pa * w;
            acc[3] += pa * w;
        }
    }
    *r = acc[0] / 65025.f, *g = acc[1] / 65025.f, *b = acc[2] / 65025.f, *a = acc[3] / 255.f;
}

static inline void
paint_at(const Fill *f, int x, int y, float *r, float *g, float *b, float *a) {
    if (f->type == FILL_SOLID) {
        *r = f->r, *g = f->g, *b = f->b, *a = f->a;
        return;
    }
    double u, v;
    apply(f->inv, x + 0.5, y + 0.5, &u, &v);
    if (f->type == FILL_IMAGE) {
        sample_image(f->img, u, v, r, g, b, a);
    } else {
        const Elem *gr = f->grad;
        double t;
        if (f->type == FILL_LINEAR) {
            double dx = gr->g[2] - gr->g[0], dy = gr->g[3] - gr->g[1], l2 = dx * dx + dy * dy;
            t = l2 > 0 ? ((u - gr->g[0]) * dx + (v - gr->g[1]) * dy) / l2 : 0;
        } else {
            // radial: find t such that p lies on the circle of radius t*r around focus + t*(center - focus)
            double cx = gr->g[0], cy = gr->g[1], rad = gr->g[2], fx = gr->has_focus ? gr->g[3] : cx, fy = gr->has_focus ? gr->g[4] : cy;
            double px = u - fx, py = v - fy, cdx = cx - fx, cdy = cy - fy;
            double A = cdx * cdx + cdy * cdy - rad * rad, B = px * cdx + py * cdy, C = px * px + py * py;
            if (fabs(A) < 1e-12) t = B != 0 ? C / (2 * B) : 0;
            else {
                double disc = B * B - A * C;
                t = disc < 0 ? 1 : (B - sqrt(disc)) / A;
                if (t < 0) t = (B + sqrt(fmax(0, disc))) / A;
            }
        }
        eval_stops(gr, t, r, g, b, a);
        *r *= *a, *g *= *a, *b *= *a;
    }
    *r *= f->opacity, *g *= f->opacity, *b *= f->opacity, *a *= f->opacity;
}

// Composites the premultiplied source S onto D, both in [0, 1], writing D's new value to out
static inline void
blend_pixel(uint8_t *out, const float *S, const float *D, uint8_t blend) {
    float O[4];
    switch (blend) {
        case BLEND_MULTIPLY:
            for (int k = 0; k < 3; k++) O[k] = S[k] * D[k] + S[k] * (1 - D[3]) + D[k] * (1 - S[3]);
            break;
        case BLEND_SCREEN:
            for (int k = 0; k < 3; k++) O[k] = S[k] + D[k] - S[k] * D[k];
            break;
        default:
            for (int k = 0; k < 3; k++) O[k] = S[k] + D[k] * (1 - S[3]);
    }
    O[3] = S[3] + D[3] * (1 - S[3]);
    for (int k = 0; k < 4; k++) out[k] = (uint8_t)(clampf(O[k]) * 255 + 0.5f);
}

static void
composite_span(void *ctx, int y, int x0, int x1, const float *cov) {
    const Fill *f = ctx;
    Canvas *c = f->canvas;
    uint8_t *row = c->px + ((size_t)y * c->W + x0) * 4;
    const uint8_t *clip = f->clip ? f->clip + (size_t)y * c->W + x0 : NULL;
    for (int x = x0; x < x1; x++, row += 4) {
        float cv = cov[x - x0];
        if (clip) cv *= clip[x - x0] / 255.f;
        if (cv <= 0) continue;
        float S[4], D[4];
        paint_at(f, x, y, S, S + 1, S + 2, S + 3);
        for (int k = 0; k < 4; k++) S[k] *= cv, D[k] = row[k] / 255.f;
        blend_pixel(row, S, D, f->blend);
    }
}

typedef struct {
    uint8_t *mask;
    const uint8_t *outer;
    int W;
} MaskCtx;

static void
mask_span(void *ctx, int y, int x0, int x1, const float *cov) {
    const MaskCtx *m = ctx;
    uint8_t *row = m->mask + (size_t)y * m->W;
    const uint8_t *outer = m->outer ? m->outer + (size_t)y * m->W : NULL;
    for (int x = x0; x < x1; x++) row[x] = (uint8_t)(cov[x - x0] * (outer ? outer[x] : 255) + 0.5f);
}

typedef struct {
    Canvas *canvas;
    const uint8_t *clip;
    uint8_t blend;
} Target;

static bool
setup_fill(Render *r, Fill *f, const Target *t, const Paint *p, Mat m, float opacity) {
    memset(f, 0, sizeof(*f));
    f->canvas = t->canvas;
    f->clip = t->clip;
    f->blend = t->blend;
    f->opacity = opacity;
    if (p->type == PAINT_SOLID) {
        f->type = FILL_SOLID;
        float a = p->a / 255.f * opacity;
        f->r = p->r / 255.f * a, f->g = p->g / 255.f * a, f->b = p->b / 255.f * a, f->a = a;
        return true;
    }
    Elem *g = lookup(r->doc, p->gradient);
    if (!g || (g->type != 'l' && g->type != 'r') || !mat_invert(m, &f->inv)) return false;
    f->type = g->type == 'l' ? FILL_LINEAR : FILL_RADIAL;
    f->grad = g;
    return true;
}

static void
fill_edges(Render *r, EdgeList *el, bool evenodd, Fill *f) {
    if (!rasterize(el, evenodd, r->W, r->H, composite_span, f)) r->failed = true;
}

static bool
stroke_polys(PolyList *polys, const Elem *style, double hw, Mat m, double tol, EdgeList *el) {
    StrokeOut out = {el, m};
    for (size_t i = 0; i < polys->count; i++) {
        PolyList pieces = {0};
        bool ok = dash_polyline(polys->item + i, style->dash, style->ndash, style->dash_phase, &pieces);
        for (size_t k = 0; ok && k < pieces.count; k++)
            ok = stroke_polyline(&out, pieces.item[k].pts, pieces.item[k].count / 2, pieces.item[k].closed, hw, style->cap, style->join, style->miter_limit, tol);
        polylist_free(&pieces);
        if (!ok) return false;
    }
    return true;
}

// Draws path with the style of e (which is e's own path or the symbol it uses)
static void
draw_path(Render *r, const Elem *e, const Path *path, Mat m, const Target *t) {
    if (e->fill.type != PAINT_NONE) {
        PolyList polys = {0};
        EdgeList el = {0};
        Fill f;
        bool ok = flatten_path(path, m, TOLERANCE, &polys);
        for (size_t i = 0; ok && i < polys.count; i++) ok = add_polygon(&el, polys.item[i].pts, polys.item[i].count / 2, identity, false);
        if (ok && setup_fill(r, &f, t, &e->fill, m, 1)) fill_edges(r, &el, e->rule == 1, &f);
        if (!ok) r->failed = true;
        polylist_free(&polys);
        free(el.item);
    }
    if (e->stroke.type != PAINT_NONE && e->width > 0) {
        PolyList polys = {0};
        EdgeList el = {0};
        Fill f;
        double tol = TOLERANCE / mat_scale(m);
        bool ok = flatten_path(path, identity, tol, &polys) && stroke_polys(&polys, e, e->width / 2, m, tol, &el);
        if (ok && setup_fill(r, &f, t, &e->stroke, m, 1)) fill_edges(r, &el, false, &f);
        if (!ok) r->failed = true;
        polylist_free(&polys);
        free(el.item);
    }
}

static void
draw_pen(Render *r, const Elem *e, Mat m, const Target *t) {
    if (e->fill.type == PAINT_NONE || !e->npts) return;
    EdgeList el = {0};
    StrokeOut out = {&el, m};
    double tol = TOLERANCE / mat_scale(m);
    bool ok = true;
    const double *p = e->pts;
    for (size_t i = 0; ok && i + 1 < e->npts; i++) {
        double x0 = p[3 * i], y0 = p[3 * i + 1], w0 = p[3 * i + 2] / 2, x1 = p[3 * i + 3], y1 = p[3 * i + 4], w1 = p[3 * i + 5] / 2;
        double dx = x1 - x0, dy = y1 - y0, len = sqrt(dx * dx + dy * dy);
        if (len < 1e-9) continue;
        dx /= len, dy /= len;
        double q[8] = {x0 - dy * w0, y0 + dx * w0, x1 - dy * w1, y1 + dx * w1, x1 + dy * w1, y1 - dx * w1, x0 + dy * w0, y0 - dx * w0};
        ok = emit(&out, q, 4);
    }
    for (size_t i = 0; ok && i < e->npts; i++) {
        bool end = i == 0 || i + 1 == e->npts;
        if (end && e->cap == CAP_BUTT && e->npts > 1) continue;
        ok = emit_circle(&out, p[3 * i], p[3 * i + 1], p[3 * i + 2] / 2, tol);
    }
    Fill f;
    if (ok && setup_fill(r, &f, t, &e->fill, m, 1)) fill_edges(r, &el, false, &f);
    if (!ok) r->failed = true;
    free(el.item);
}

static void
draw_image(Render *r, const Elem *e, Mat m, const Target *t) {
    VectorImageData img = {0};
    if (!r->lookup || !r->lookup(r->lookup_ctx, e->ref, &img) || !img.data || !img.width || !img.height) {
        free(img.data);
        return;
    }
    Fill f = {.canvas = t->canvas, .clip = t->clip, .blend = t->blend, .type = FILL_IMAGE, .opacity = e->opacity / 100.f, .img = &img};
    EdgeList el = {0};
    double q[8] = {0, 0, img.width, 0, img.width, img.height, 0, img.height};
    if (mat_invert(m, &f.inv) && add_polygon(&el, q, 4, m, false)) fill_edges(r, &el, false, &f);
    free(el.item);
    free(img.data);
}

static uint8_t *
make_clip(Render *r, const Elem *path, Mat m, const uint8_t *outer) {
    uint8_t *mask = calloc((size_t)r->W * r->H, 1);
    if (!mask) {
        r->failed = true;
        return NULL;
    }
    PolyList polys = {0};
    EdgeList el = {0};
    bool ok = flatten_path(&path->path, mat_mul(m, path->t), TOLERANCE, &polys);
    for (size_t i = 0; ok && i < polys.count; i++) ok = add_polygon(&el, polys.item[i].pts, polys.item[i].count / 2, identity, false);
    MaskCtx mc = {mask, outer, r->W};
    if (ok) ok = rasterize(&el, path->rule == 1, r->W, r->H, mask_span, &mc);
    if (!ok) r->failed = true;
    polylist_free(&polys);
    free(el.item);
    return mask;
}

static void
composite_group(Canvas *dst, const Canvas *src, float opacity) {
    size_t n = (size_t)dst->W * dst->H;
    for (size_t i = 0; i < n; i++) {
        const uint8_t *s = src->px + 4 * i;
        uint8_t *d = dst->px + 4 * i;
        if (!s[3]) continue;
        float S[4], D[4];
        for (int k = 0; k < 4; k++) S[k] = s[k] / 255.f * opacity, D[k] = d[k] / 255.f;
        blend_pixel(d, S, D, BLEND_NORMAL);
    }
}

static size_t
first_child(const Render *r, uint32_t gid) {
    size_t lo = 0, hi = r->nsorted;
    while (lo < hi) {
        size_t mid = (lo + hi) / 2;
        if (r->sorted[mid]->parent < gid) lo = mid + 1;
        else hi = mid;
    }
    return lo;
}

// Draws the children of g. The blend mode of a group applies to every drawing
// operation below it, as the PDF blend mode does; opacity composites the
// group as a whole through a layer.
static void
render_group(Render *r, Elem *g, Mat parent_m, Target parent, unsigned depth) {
    if (!g->visible || depth > MAX_DEPTH || g->in_progress || r->failed) return;
    g->in_progress = true;
    Mat m = g->has_t ? mat_mul(parent_m, g->t) : parent_m;
    Target t = parent;
    uint8_t *own_clip = NULL;
    if (g->ref) {
        Elem *cp = lookup(r->doc, g->ref);
        if (cp && (cp->type == 'p' || cp->type == 's')) t.clip = own_clip = make_clip(r, cp, m, t.clip);
    }
    if (g->blend != BLEND_NORMAL) t.blend = g->blend;
    Canvas layer = {0};
    if (g->opacity < 100) {
        layer.W = r->W, layer.H = r->H;
        layer.px = calloc((size_t)r->W * r->H, 4);
        if (!layer.px) r->failed = true;
        else t.canvas = &layer;
    }
    for (size_t i = first_child(r, g->id); i < r->nsorted && r->sorted[i]->parent == g->id && !r->failed; i++) {
        Elem *e = r->sorted[i];
        if (e == g) continue;
        Mat em = e->has_t ? mat_mul(m, e->t) : m;
        switch (e->type) {
            case 'g': render_group(r, e, m, t, depth + 1); break;
            case 'p': draw_path(r, e, &e->path, em, &t); break;
            case 'u': {
                Elem *sym = lookup(r->doc, e->ref);
                if (sym && sym->type == 's') draw_path(r, e, &sym->path, em, &t);
            } break;
            case 'k': draw_pen(r, e, em, &t); break;
            case 'i': draw_image(r, e, em, &t); break;
        }
    }
    if (layer.px) {
        composite_group(parent.canvas, &layer, g->opacity / 100.f);
        free(layer.px);
    }
    free(own_clip);
    g->in_progress = false;
}

static int
cmp_parent_slot(const void *a, const void *b) {
    const Elem *x = *(Elem *const *)a, *y = *(Elem *const *)b;
    if (x->parent != y->parent) return x->parent < y->parent ? -1 : 1;
    return x->slot < y->slot ? -1 : x->slot > y->slot;
}

uint8_t *
vector_doc_render(VectorDoc *d, unsigned width, unsigned height, vector_image_lookup lookup, void *ctx) {
    if (!width || !height || !d->width || !d->height) return NULL;
    Render r = {.doc = d, .W = width, .H = height, .lookup = lookup, .lookup_ctx = ctx};
    Canvas canvas = {.px = calloc((size_t)width * height, 4), .W = width, .H = height};
    r.sorted = malloc((d->live + 1) * sizeof(Elem *));
    if (!canvas.px || !r.sorted) {
        free(canvas.px);
        free(r.sorted);
        return NULL;
    }
    for (size_t i = 0; i < d->count; i++) {
        Elem *e = d->order[i];
        if (e && e->type != 's' && e->type != 'l' && e->type != 'r') r.sorted[r.nsorted++] = e;
    }
    qsort(r.sorted, r.nsorted, sizeof(Elem *), cmp_parent_slot);
    Mat m = {(double)width / d->width, 0, 0, (double)height / d->height, 0, 0};
    render_group(&r, &d->root, m, (Target){&canvas, NULL, BLEND_NORMAL}, 0);
    free(r.sorted);
    if (r.failed) {
        free(canvas.px);
        return NULL;
    }
    // straight alpha for the GPU
    for (size_t i = 0, n = (size_t)width * height; i < n; i++) {
        uint8_t *p = canvas.px + 4 * i;
        if (p[3] && p[3] != 255)
            for (int k = 0; k < 3; k++) p[k] = (uint8_t)fmin(255, (p[k] * 255 + p[3] / 2) / p[3]);
    }
    return canvas.px;
}

// }}}
