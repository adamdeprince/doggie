Cell background alpha
========================

.. versionadded:: 0.50.0

A program can draw images in the terminal, but it cannot draw text over them
without hiding them, because a cell background is always opaque. This
extension lets a program make the background of a cell translucent, so that
whatever is beneath, the window background, a background image or an image
placed below the text, shows through. The usual use is a heads up display
over a canvas or a dimmed overlay behind a menu.

Setting the alpha
--------------------

A new SGR attribute sets the opacity of the background of subsequently
written cells, as a percent, using the colon sub-parameter form::

    <ESC>[70:<percent>m

``100`` is opaque, which is the default, and ``0`` is fully transparent. For
example, to show text on a red background that is thirty percent opaque::

    <ESC>[48;2;255;0;0m<ESC>[70:30mHello<ESC>[m

The alpha is independent of how the background color was chosen. It applies
to colors set with ``48``, to the sixteen basic colors, to colors from the
256 color palette and to the default background, and it stays in effect when
the background color is changed. It is reset by ``<ESC>[0m``, by ``70``
without a sub-parameter, and by a value of ``100`` or more. Values are
rounded down to even percentages. The percent is only recognized as a colon
sub-parameter, ``<ESC>[70;30m`` is ``70`` with no value followed by an
unrelated parameter.

The translucent background is blended over whatever the terminal draws
beneath the cell: the window background including its own transparency, a
background image, and images placed below the text with a negative z-index.
Cells under the cursor, selected cells and cells with reverse video are
drawn opaque, as they are today, and under reverse video the alpha is ignored
since the background color is being used as the foreground. The foreground
text, underlines and strikethrough are not affected.

Compatibility
----------------

Terminals that do not know this attribute ignore it, since that is what most
terminals do with unknown SGR parameters and their sub-parameters, so a
program can emit it unconditionally and get an opaque background elsewhere. A
terminal that drops a whole SGR sequence containing an unknown parameter would
also lose any color set in the same sequence, so send the alpha in its own
``<ESC>[...m`` after the color, as in the example above.

In kitty the attribute is stored with the background color of the cell and
survives everything the color survives: scrollback, copying with formatting,
and ``DECRQSS`` reports of the current SGR state, which include ``70:<percent>``
when the alpha is not 100.
