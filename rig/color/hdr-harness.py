#!/usr/bin/env python3
# Test-only changes for a tree under test, never committed: with SILKIE_HDR_TEST set, a window is treated as an
# HDR window although its surface is an ordinary 8 bit one, so that everything but the floating point surface
# itself can be exercised where no driver has one, and what the renderer produced is logged.
import sys
tree = sys.argv[1]

def sub(path, old, new):
    p = f'{tree}/{path}'
    s = open(p).read()
    assert s.count(old) == 1, (path, old[:60], s.count(old))
    open(p, 'w').write(s.replace(old, new))

sub('glfw/wl_window.c', '''            } else if (!_glfwHasFloatColorEGL(ctxconfig, fbconfig)) {''',
    '''            } else if (!getenv("SILKIE_HDR_TEST") && !_glfwHasFloatColorEGL(ctxconfig, fbconfig)) {''')
sub('glfw/wl_window.c', '''        window->wl.hdr.enabled = window->context.egl.floatColor;''',
    '''        window->wl.hdr.enabled = window->context.egl.floatColor || (getenv("SILKIE_HDR_TEST") && window->wl.hdr.described);''')
sub('kitty/child-monitor.c', '''w->linear_output = backbuffer_is_float();''', '''w->linear_output = backbuffer_is_float() || getenv("SILKIE_HDR_TEST");''')
sub('kitty/shaders.c', '''    if (!w->linear_output || !(w->hdr_white_level > 0.f) || w->hdr_white_level == 1.f) return;
''', '''    if (!w->linear_output || !(w->hdr_white_level > 0.f) || w->hdr_white_level == 1.f) {
        if (getenv("SILKIE_HDR_TEST")) { static float last = -1; if (last != w->hdr_white_level) { last = w->hdr_white_level; fprintf(stderr, "HDRTEST no scaling, white level %g headroom %g\\n", w->hdr_white_level, effective_hdr_headroom(w)); } }
        return;
    }
    float before[4] = {0}, after[4] = {0};
    const bool hdrtest = getenv("SILKIE_HDR_TEST") != NULL;
    if (hdrtest) { glBindFramebuffer(GL_FRAMEBUFFER, 0); glReadPixels(2, 2, 1, 1, GL_RGBA, GL_FLOAT, before); }
''')
sub('kitty/shaders.c', '''    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
}
''', '''    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
    if (hdrtest) {
        static float last = -1;
        glReadPixels(2, 2, 1, 1, GL_RGBA, GL_FLOAT, after);
        if (last != w->hdr_white_level) { last = w->hdr_white_level; fprintf(stderr, "HDRTEST scaled by white level %g headroom %g: corner pixel %g %g %g %g -> %g %g %g %g\\n", w->hdr_white_level, effective_hdr_headroom(w), before[0], before[1], before[2], before[3], after[0], after[1], after[2], after[3]); }
    }
}
''')
# what the float layer holds before it is copied to the window
sub('kitty/shaders.c', '''            // debug_rendering("Custom shaders inactive, falling back to blit\\n");
''', '''            if (getenv("SILKIE_HDR_TEST")) {
                static float last = -1;
                const int vw = os_window->viewport_width, vh = os_window->viewport_height;
                float *px = malloc(sizeof(float) * 4 * vw * vh), mx = 0;
                glBindFramebuffer(GL_READ_FRAMEBUFFER, global_state.layers_render_texture.framebuffer_id);
                glReadPixels(0, global_state.layers_render_texture.height - vh, vw, vh, GL_RGBA, GL_FLOAT, px);
                for (int i = 0; i < vw * vh * 4; i++) if (i % 4 != 3 && px[i] > mx) mx = px[i];
                free(px);
                if (mx != last) { last = mx; fprintf(stderr, "HDRTEST layers are %s, brightest value %g\\n", global_state.layers_render_texture.is_float ? "float" : "fixed", mx); }
            }
''')
print('harness applied to', tree)
