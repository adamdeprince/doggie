Mouse pointer shapes
=======================

.. versionadded:: 0.31.0

This is a simple escape code that can be used by terminal programs to change
the shape of the mouse pointer. This is useful for buttons/links, dragging to
resize panes, etc. It is based on the original escape code proposal from xterm
however, it properly specifies names for the different shapes in a system
independent manner, adds a stack for easy push/pop of shapes, allows programs
to query support and specifies interaction with other terminal state.

The escape code is of the form::

    <OSC> 22 ; <optional first char> <comma-separates list of shape names> <ESC>\

Here, ``<OSC>`` is the bytes ``<ESC>]`` and ``<ESC>`` is the byte ``0x1b``.
Spaces in the above are present for clarity only and should not be actually used.

First some examples::

    # Set the pointer to a pointing hand
    <OSC> 22 ; pointer <ESC>\
    # Reset the pointer to default
    <OSC> 22 ; <ESC>\
    # Push a shape onto the stack making it the current shape
    <OSC> 22 ; >wait <ESC>\
    # Pop a shape off the stack restoring to the previous shape
    <OSC> 22 ; < <ESC>\
    # Query the terminal for what the currently set shape is
    <OSC> 22 ; ?__current__ <ESC>\

To demo the various shapes, simply run the following command inside kitty::

    kitten mouse-demo

For more details see below.

Setting the pointer shape
-------------------------------

For set operations, the optional first char can be either ``=`` or omitted.
Follow the first char with the name of the shape. See the
:ref:`pointer_shape_names` table.


Pushing and popping shapes onto the stack
---------------------------------------------

The terminal emulator maintains a stack of shapes. To add shapes to the stack,
the optional first char must be ``>`` followed by a comma separated list of
shape names. See the :ref:`pointer_shape_names` table. All the specified names
are added to the stack, with the last name being the top of the stack and the
current shape. If the stack is full, the entry at the bottom of the stack is
evicted. Terminal implementations are free to choose an appropriate maximum
stack size, with a minimum stack size of 16.

To pop shapes of the top of the stack the optional first char must be ``<``.
The comma separated list of names is ignored. Once the stack is empty further
pops have no effect. An empty stack means the terminal is free to use whatever
pointer shape it likes.


Querying support
-------------------

Terminal programs can ask the terminal about this feature by setting the
optional first char to ``?``. The comma separated list of names is then
considered the query to which the terminal must respond with an OSC 22 code.
For example::

    <OSC> 22 ; ?__current__ <ESC>\
    results in
    <OSC> 22 ; shape_name <ESC>\

Here, ``shape_name`` will be a name from the table of shape names below or ``0``
if the stack is empty, i.e., no shape is currently set.

To check if the terminal supports some shapes, pass the shape names and the
terminal will reply with a comma separated list of zeros and ones where 1 means
the shape name is supported and zero means it is not. For example::

    <OSC> 22 ; ?pointer,crosshair,no-such-name,wait <ESC>\
    results in
    <OSC> 22 ; 1,1,0,1 <ESC>\

In addition to ``__current__`` there are a couple of other special names::

    __default__ - The terminal responds with the shape name of the shape used by default
    __grabbed__ - The terminal responds with the shape name of the shape used when the mouse is "grabbed"


Interaction with other terminal features
---------------------------------------------

The terminal must maintain separate shape stacks for the *main* and *alternate*
screens. This allows full screen programs, which are likely to be the main
consumers of this feature, to easily temporarily switch back from the alternate screen,
without needing to worry about pointer shape state. Think of suspending a
terminal editor to get back to the shell, for example.

Resetting the terminal must empty both the shape stacks.

When dragging to select text, the terminal is free to ignore any mouse pointer
shape specified using this escape code in favor of one appropriate for
dragging.  Similarly, when hovering over a URL or OSC 8 based hyperlink, the
terminal may choose to change the mouse pointer regardless of the value set by
this escape code.

This feature is independent of mouse reporting. The changed pointer shapes apply
regardless of whether the terminal program has enabled mouse reporting or not.


.. _pointer_image_shapes:

Image shapes
-------------------

.. versionadded:: 0.50.0

A program can use an image it has sent with the :doc:`graphics-protocol` as the
pointer, for example a drawing program showing the size and color of the
current brush under the pen. Anywhere a shape name is accepted, the name::

    image:<image id>:<hotspot x>:<hotspot y>

refers to the image transmitted with that ``i=`` id in the same window. The
hotspot is the pixel of the image that sits under the pointer position, with
the origin at the top left corner; one or both coordinates may be left out and
default to zero. For example, a 2 pixel wide outline of a circle with a 48
pixel diameter, sent as image ``9``, centered on the pointer::

    <OSC> 22 ; image:9:24:24 <ESC>\

The image is shown with one image pixel per physical pixel, exactly as the
graphics protocol displays an image placed without scaling, so a brush preview
drawn at the size the brush has on the canvas lines up with it. The window and
cell sizes reported by ``CSI 14 t`` and ``CSI 16 t`` are in the same pixels.
The current frame of an animated image is used, changes to the frames of the
image are reflected on the pointer.

The name is only a reference to the image. If no image with that id exists
when the shape is set, or the image is deleted later, the entry is ignored and
the pointer falls back to the shape below it on the stack, or to the default
shape, until an image with that id is transmitted again. Deleting the image
therefore does not pop the stack. The reply to ``?__current__`` is the image
name, with both hotspot coordinates, when an image shape is in effect. The
query form ``?image:1:2:3`` answers ``1`` when the terminal supports image
shapes, regardless of whether image ``1`` exists.

An image larger than the platform allows for a pointer, which happens on X11
for big images, is ignored as if it did not exist. A multiplexer or a relay
such as mosh passes the name through unchanged, the terminal at the far end
resolves the id among the images of that window.


.. _pointer_shape_names:

Pointer shape names
----------------------------------

There is a well defined set of shape names that all conforming terminal
emulators must support. The list is based on the names used by the `cursor
property in the CSS standard
<https://developer.mozilla.org/en-US/docs/Web/CSS/cursor>`__, click the link to
see representative images for the names. Valid names must consist of only the
characters from the set ``a-z0-9_-``.

.. start list of shape css names (auto generated by gen-key-constants.py do not edit)

#. alias
#. cell
#. copy
#. crosshair
#. default
#. e-resize
#. ew-resize
#. grab
#. grabbing
#. help
#. move
#. n-resize
#. ne-resize
#. nesw-resize
#. no-drop
#. not-allowed
#. ns-resize
#. nw-resize
#. nwse-resize
#. pointer
#. progress
#. s-resize
#. se-resize
#. sw-resize
#. text
#. vertical-text
#. w-resize
#. wait
#. zoom-in
#. zoom-out

.. end list of shape css names

To demo the various shapes, simply run the following command inside kitty::

    kitten mouse-demo

Legacy xterm compatibility
----------------------------

The original xterm proposal for this escape code used shape names from the
:file:`X11/cursorfont.h` header on X11 based systems. Terminal implementations
wishing to maintain compatibility with xterm can also implement these names as
aliases for the CSS based names defined in the :ref:`pointer_shape_names` table.

The simplest mode of operation of this escape code, which is no leading
optional char and a single shape name is compatible with xterm.
