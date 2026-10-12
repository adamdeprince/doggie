Wide gamut colors
=====================

.. versionadded:: 0.50.0

Terminal colors are sRGB. Most displays made in the last few years can show
colors outside that gamut, the deeper reds and greens of Display P3 and the
still larger Rec. 2020 gamut, but a program has no way to ask for them. This
extension lets a program say which gamut an RGB color is in, using a slot the
existing escape code already has, so that nothing changes for programs that
do not use it.

Choosing a gamut
-------------------

The colon form of the RGB color SGR has an optional color space id between
the ``2`` and the red component, defined in ITU-T T.416 but never given a
meaning by terminals, which skip it. This extension gives it one::

    <ESC>[38:2:<id>:<r>:<g>:<b>m      foreground
    <ESC>[48:2:<id>:<r>:<g>:<b>m      background

``id`` is ``0`` for sRGB, which is the same as leaving it out, ``1`` for
Display P3 and ``2`` for Rec. 2020. Any other id is treated as ``0``. The
components are 0 to 255, encoded with the sRGB transfer curve in every gamut,
so only the primaries change with the id and a terminal needs a single
curve. The brightest red of Display P3 is::

    <ESC>[38:2:1:255:0:0m

The gamut belongs to the RGB color it was given with. Selecting one of the
sixteen basic colors, a color from the 256 color palette or the default color
also selects sRGB, as does an RGB color without an id. Under reverse video
the gamut follows the color, so a reversed cell with a Display P3 foreground
shows a Display P3 background. Decorations, underline and strikethrough, use
the foreground and its gamut unless a decoration color is set with ``58``,
which is always sRGB.

Terminals that do not know the id skip it, so a program can emit the id
unconditionally and get the same color interpreted as sRGB elsewhere, which
is a little less saturated and never wrong. The id is only recognized in the
colon form. The semicolon form ``<ESC>[38;2;<r>;<g>;<b>m`` has no id, since
the parameters it is followed by are unrelated attributes.

What the terminal does with it
------------------------------------

The terminal converts a color tagged with a gamut to the gamut it draws in,
through CIE XYZ, and clips what the display cannot show. Colors without an id
are what they always were, the terminal's own colorspace, and are not
touched, so programs that do not use the id are rendered exactly as they were
before this extension existed. When a terminal draws in sRGB, a Display P3 or
Rec. 2020 color is shown as the nearest sRGB color, which is close to, though
not the same as, reading its components as sRGB. Only when the terminal draws
in a wider gamut do the extra colors appear.

A program that wants to know whether asking for wide gamut colors is
worthwhile asks for the ``gamut`` of the display with the ``display`` query
of the display information protocol, where the terminal has one, and
otherwise simply emits the id. Brightness above SDR white is a separate
attribute, the ``56`` and ``57`` of the HDR brightness protocol, and the two
combine: a Display P3 red at twice SDR white is
``<ESC>[38:2:1:255:0:0m<ESC>[56:200m``.

In kitty
------------

In kitty the gamut is stored with the color of the cell and survives
everything the color survives: scrollback, copying with formatting, and
``DECRQSS`` reports of the current SGR state, which include the id when it is
not ``0``. On macOS the window draws in the colorspace selected by
:opt:`macos_colorspace`, and tagged colors are converted to it: with ``srgb``
Display P3 and Rec. 2020 colors are clipped to sRGB, with ``displayp3``
Display P3 colors are shown as they are and Rec. 2020 colors are clipped to
Display P3, while untagged colors keep being interpreted as Display P3, as
that option has always done. With ``default`` the window is in the native
colorspace of the display and every color is passed through unconverted. On
other platforms the window draws in sRGB.
