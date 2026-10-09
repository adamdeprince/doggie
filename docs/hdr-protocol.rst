HDR brightness protocol
==========================

.. versionadded:: 0.50.0

Many modern displays can show colors brighter than the white used for normal
content, which Apple calls *extended dynamic range* (EDR). This protocol lets
programs request that extra brightness for text, for images and for the cursor,
without changing how anything else is displayed.

Everything is expressed relative to *SDR white*, the white of normal text,
which is rendered exactly as bright as it always has been. A brightness of
``100`` percent is SDR white, ``200`` percent is twice as bright in linear
light, and so on. How much extra brightness the display can show is called the
*headroom*, also a multiple of SDR white: a headroom of ``1`` means the display
has no extra range, a headroom of ``4`` means it can show up to four times SDR
white. The headroom changes with the brightness setting of the display and
when a window moves between screens.

The terminal clamps every request to the headroom it currently has. On a
display without HDR, or when the user has HDR turned off, every request is
clamped to ``1`` and the output is identical to what it was before this
protocol existed. Requests are never used to make anything dimmer, so programs
written without HDR in mind look the same in a terminal that implements this
protocol as in one that does not.

Text
------

Two new SGR attributes set the brightness of the foreground and the background
of subsequently written cells, as a percent of SDR white, using the colon
sub-parameter form::

    <ESC>[56:<percent>m      foreground brightness
    <ESC>[57:<percent>m      background brightness

For example, to show text in orange at two and a half times SDR white::

    <ESC>[38;2;255;136;0m<ESC>[56:250mHello<ESC>[m

The brightness is independent of how the color was chosen. It applies to
colors set with ``38``/``48``, to the sixteen basic colors, to colors from the
256 color palette and to the default foreground and background, so a program
can ask for the default text color, brighter, without knowing what that color
is. The text decorations of a cell (underline, strikethrough) use the
foreground brightness. Under reverse video the brightness follows the color it
was set with, so a reversed cell with a foreground brightness of 200 percent
shows a background at 200 percent.

The attributes are reset by ``<ESC>[0m``, by ``56`` and ``57`` without a
sub-parameter, and by a value of ``100`` or less. Values are rounded to quarter
steps (``125``, ``150``, ``175``...) and clamped to ``1675``. A request larger
than the headroom is shown at the headroom. The *dim* attribute (``2``) and
brightness are independent, dim text at 200 percent is dim relative to a
white twice as bright as usual.

Terminals that do not know these attributes ignore them, since that is what
most terminals do with unknown SGR parameters and their sub-parameters, so a
program can emit them unconditionally. A terminal that drops a whole SGR
sequence containing an unknown parameter would also lose any color set in the
same sequence, so send the brightness in its own ``<ESC>[...m`` after the
color, as in the example above. The percent is only recognized as a colon
sub-parameter, ``<ESC>[56;250m`` is ``56`` with no value followed by an
unrelated parameter.

Images
--------

The :doc:`graphics-protocol` gains a pixel format for HDR images, ``f=64``.
The data is RGBA with four 16-bit floating point numbers (IEEE 754 half
precision, little endian) per pixel, in *linear* extended sRGB where ``1.0`` is
SDR white and values above it are brighter. Alpha is straight (not
pre-multiplied), as for ``f=32``. The other keys work as for ``f=32``: the
width and height must be given with ``s`` and ``v``, the data may be
compressed with ``o=z``, and it may be sent by any transmission medium.
Animation frames and frame composition are not supported for these images,
the terminal responds with ``EINVAL`` to such commands.

Pixel values larger than the headroom are shown at the headroom. To check
whether a terminal supports ``f=64``, use the query action described in the
graphics protocol with ``f=64`` and a single pixel of data, a terminal that
does not know the format responds with ``EINVAL``.

Cursor
---------

In kitty the brightness of the block cursor is a configuration option,
:opt:`cursor_brightness`. A cursor brighter than any text makes it easy to
find on a crowded screen.

Querying the headroom
------------------------

A program that wants to know how much extra brightness is available, for
example to pick between several renderings of an image, can ask for the
headroom of the window it is running in with the ``XTGETTCAP`` query
mechanism, see :doc:`kittens/query_terminal`. The query name is
``kitty-query-hdr_headroom`` and the answer is the headroom as a decimal
number, ``1`` when there is none. For example, encoding the query name as
hex::

    <ESC>P+q6b697474792d71756572792d6864725f68656164726f6f6d<ESC>\

The headroom changes over time, so re-query it before relying on a value
obtained a while ago. No notification of changes is sent.

Configuration
----------------

In kitty, HDR output is off by default and enabled with the :opt:`hdr` option.
The user can cap how bright anything gets with :opt:`hdr_max_headroom`, which
the terminal applies before clamping to the headroom of the display, and that
cap is what the query above reports. Currently only macOS displays HDR
content, on other platforms the headroom is always ``1``.
