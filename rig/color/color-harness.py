#!/usr/bin/env python3
# Test only, never committed: makes the first preferred description that is read trigger a series of
# glfwSetWindowColorDescription calls, chosen with SILKIE_COLOR_TEST, and prints what each returned
import sys
p = sys.argv[1] + "/glfw/wl_color_management.c"
s = open(p).read()
if "color_test_harness" in s:
    raise SystemExit("harness already applied")
harness = r"""
#include <stdlib.h>
static void
color_test_harness(_GLFWwindow *window) {
    static bool ran = false;
    const char *t = getenv("SILKIE_COLOR_TEST");
    if (!t || ran) return;
    ran = true;
#define T(name, expect, intent, ...) { \
        GLFWcolordescription d = {__VA_ARGS__}; \
        bool ok = _glfwPlatformSetWindowColorDescription(window, &d, intent); \
        fprintf(stderr, "HARNESS %-44s %s%s\n", name, ok ? "accepted" : "refused", ok == expect ? "" : "   <-- UNEXPECTED"); }
#define P GLFW_COLOR_INTENT_PERCEPTUAL
    if (!strcmp(t, "matrix")) {
        T("p3 gamma22", true, P, .primaries = GLFW_COLOR_PRIMARIES_DISPLAY_P3, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        T("p3 srgb curve", true, P, .primaries = GLFW_COLOR_PRIMARIES_DISPLAY_P3, .transfer = GLFW_COLOR_TRANSFER_SRGB);
        T("p3 gamma22 relative intent", true, GLFW_COLOR_INTENT_RELATIVE, .primaries = GLFW_COLOR_PRIMARIES_DISPLAY_P3, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        T("bt2020 pq", true, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ);
        T("bt2020 pq luminances", true, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ, .min_luminance = 0.005f, .max_luminance = 10000, .reference_luminance = 203);
        T("srgb ext_linear", true, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_EXT_LINEAR);
        T("srgb ext_linear ref 80 max 400", true, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_EXT_LINEAR, .max_luminance = 400, .reference_luminance = 80);
        T("srgb ext_linear ref 203 max 80 (needs extended)", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_EXT_LINEAR, .max_luminance = 80, .reference_luminance = 203);
        T("srgb hlg (tf not offered)", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_HLG);
        T("dci_p3 gamma22 (primaries not offered)", false, P, .primaries = GLFW_COLOR_PRIMARIES_DCI_P3, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        T("adobe rgb by chromaticities", true, P, .transfer = GLFW_COLOR_TRANSFER_GAMMA22, .chromaticities = {0.64f, 0.33f, 0.21f, 0.71f, 0.15f, 0.06f, 0.3127f, 0.3290f});
        T("no primaries at all", false, P, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        T("power 2.4", true, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_POWER, .transfer_exponent = 2.4f);
        T("power 0.5 (out of range)", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_POWER, .transfer_exponent = 0.5f);
        T("unknown transfer", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB);
        T("out of range enum", false, P, .primaries = (GLFWcolorprimaries)77, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        T("windows_scrgb (feature not offered)", false, P, .windows_scrgb = true);
        T("target primaries (feature not offered)", false, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ, .target_chromaticities = {0.680f, 0.320f, 0.265f, 0.690f, 0.150f, 0.060f, 0.3127f, 0.3290f});
        T("target luminance (feature not offered)", false, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ, .target_max_luminance = 1000);
        T("min above max luminance", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_GAMMA22, .min_luminance = 100, .max_luminance = 50, .reference_luminance = 80);
        T("only a reference luminance", false, P, .primaries = GLFW_COLOR_PRIMARIES_SRGB, .transfer = GLFW_COLOR_TRANSFER_GAMMA22, .reference_luminance = 80);
        T("max_cll and max_fall", true, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ, .max_cll = 1000, .max_fall = 400);
        T("max_fall above max_cll", false, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ, .max_cll = 400, .max_fall = 1000);
        fprintf(stderr, "HARNESS unset: %s\n", _glfwPlatformSetWindowColorDescription(window, NULL, P) ? "ok" : "failed");
    }
    if (!strcmp(t, "p3") || !strcmp(t, "matrix")) T("final: p3 gamma22 left in place", true, P, .primaries = GLFW_COLOR_PRIMARIES_DISPLAY_P3, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
    if (!strcmp(t, "pq")) T("final: bt2020 pq left in place", true, P, .primaries = GLFW_COLOR_PRIMARIES_BT2020, .transfer = GLFW_COLOR_TRANSFER_PQ);
    if (!strcmp(t, "p3-unset")) {
        T("p3 gamma22", true, P, .primaries = GLFW_COLOR_PRIMARIES_DISPLAY_P3, .transfer = GLFW_COLOR_TRANSFER_GAMMA22);
        fprintf(stderr, "HARNESS unset: %s\n", _glfwPlatformSetWindowColorDescription(window, NULL, P) ? "ok" : "failed");
    }
#undef T
#undef P
}
"""
anchor = "static void\ninfo_done("
assert s.count(anchor) == 1
s = s.replace(anchor, "bool _glfwPlatformSetWindowColorDescription(_GLFWwindow *window, const GLFWcolordescription *desc, GLFWcolorintent intent);\n" + harness + "\n" + anchor)
call = "    _glfwInputWindowDamage(window);\n}\n\nstatic void\ninfo_icc_file("
assert s.count(call) == 1
s = s.replace(call, "    _glfwInputWindowDamage(window);\n    color_test_harness(window);\n}\n\nstatic void\ninfo_icc_file(")
open(p, "w").write(s)
print("harness applied")
