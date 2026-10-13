#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import alpha_blend;
import utils;
import gamut;

extern static const bool is_alpha_mask = false;
extern static const bool texture_is_not_premultiplied = true;


struct VSOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};


[shader("vertex")]
VSOutput
vertex_main(uint vertex_id: SV_VertexID, uniform float4 src_rect, uniform float4 dest_rect, ) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    return { ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0) };
}

uniform Sampler2D image;

[shader("fragment")]
float4
fragment_main(
    float2 texcoord: TEXCOORD,
    uniform float3 amask_fg,
    uniform float4 amask_bg_premult,
    uniform float extra_alpha,
    uniform float hdr_headroom,
    uniform float tone_peak,
    uniform uint image_gamut,
    uniform uint output_gamut)
    : SV_Target {
    float4 color = image.Sample(texcoord);
    if (is_alpha_mask) {
        color = float4(amask_fg, color.r);
        color = vec4_premul(color);
        color = alpha_blend_premul(color, amask_bg_premult);
    } else {
        // HDR images, SDR ones are never above 1. With tone mapping (tone_peak > 0) the
        // range from the knee to the image peak is compressed into the headroom, preserving
        // hue, otherwise what is above the headroom is clipped. See docs/hdr-protocol.rst
        float knee = 0.75f * hdr_headroom, m = max(color.r, max(color.g, color.b));
        if (tone_peak > hdr_headroom && m > knee) {
            float s = 1.f / (hdr_headroom - knee) - 1.f / (tone_peak - knee);
            color.rgb *= (knee + (m - knee) / (1.f + s * (m - knee))) / m;
        }
        color.rgb = min(color.rgb, float3(hdr_headroom));
        // An image in a gamut of its own is converted to that of the window,
        // which has to be done on colors that are not multiplied by alpha
        if (image_gamut != GAMUT_SRGB) {
            if (texture_is_not_premultiplied) color.rgb = convert_from_gamut(color.rgb, image_gamut, output_gamut);
            else if (color.a > 0.f) color.rgb = convert_from_gamut(color.rgb / color.a, image_gamut, output_gamut) * color.a;
        }
        color.a *= extra_alpha;
    }

    if (texture_is_not_premultiplied) color = vec4_premul(color);

    return color;
}
