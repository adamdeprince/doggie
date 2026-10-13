#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module gamut;

// The gamuts a color or an image can be tagged with, see
// docs/wide-gamut-protocol.rst, and the last one, which only a window has:
// its colorspace is whatever the display is, so nothing is converted for it.
public static const uint GAMUT_SRGB = 0, GAMUT_DISPLAY_P3 = 1, GAMUT_REC2020 = 2, GAMUT_UNMANAGED = 3;

// Linear RGB of each gamut to CIE XYZ and back, all with the D65 white point
static const float3x3 gamut_to_xyz[3] = {
    float3x3(0.4124564, 0.3575761, 0.1804375, 0.2126729, 0.7151522, 0.0721750, 0.0193339, 0.1191920, 0.9503041),
    float3x3(0.4865709, 0.2656677, 0.1982173, 0.2289746, 0.6917385, 0.0792869, 0.0000000, 0.0451134, 1.0439444),
    float3x3(0.6369580, 0.1446169, 0.1688810, 0.2627002, 0.6779981, 0.0593017, 0.0000000, 0.0280727, 1.0609851),
};
static const float3x3 xyz_to_gamut[3] = {
    float3x3(3.2404542, -1.5371385, -0.4985314, -0.9692660, 1.8760108, 0.0415560, 0.0556434, -0.2040259, 1.0572252),
    float3x3(2.4934969, -0.9313836, -0.4027108, -0.8294890, 1.7626641, 0.0236247, 0.0358458, -0.0761724, 0.9568845),
    float3x3(1.7166512, -0.3556708, -0.2533663, -0.6666844, 1.6164812, 0.0157685, 0.0176399, -0.0427706, 0.9421031),
};

// A linear color tagged with a gamut, as the window draws it. An untagged
// color is the colorspace of the window, as it always was, so it and a color
// already in the gamut of the window are passed through untouched. Anything
// else is converted to the gamut of the window and clipped to it.
public float3
convert_from_gamut(float3 c, uint gamut, uint output_gamut) {
    if (gamut == GAMUT_SRGB || gamut == output_gamut || output_gamut == GAMUT_UNMANAGED) return c;
    return clamp(mul(xyz_to_gamut[output_gamut], mul(gamut_to_xyz[gamut], c)), 0.f, 1.f);
}
