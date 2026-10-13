#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import alpha_blend;
import utils;
import linear2srgb;
import gamut;

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
fragment_main(float2 texcoord: TEXCOORD, uniform float encode_srgb, uniform uint output_gamut)
    : SV_Target {
    // The one place the layers of a window become what its surface holds. They are linear sRGB, which in a window
    // in a wide gamut reaches beyond zero and one, see gamut.slang. An HDR window has a linear float backbuffer: its
    // values are brought to the primaries of the window and left linear. Any other window is sRGB encoded, after
    // its values are brought to its primaries and clipped to them. For a window in sRGB neither step changes anything
    float4 color_premul = image.Sample(texcoord);
    if (encode_srgb == 0.0f) return float4(linear_output_from_extended(color_premul.rgb, output_gamut), color_premul.a);
    return vec4_premul(linear2srgb(output_from_extended(color_premul.rgb / color_premul.a, output_gamut)), color_premul.a);
}
