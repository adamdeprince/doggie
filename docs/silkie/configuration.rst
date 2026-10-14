Silkie configuration
=====================

These options configure Silkie's extensions in ``kitty.conf``. For the file
location, syntax, and inherited settings, see `kitty's configuration reference
<https://sw.kovidgoyal.net/kitty/conf/>`_.

The option defaults and descriptions below come from Silkie's configuration
definitions.

Input limits
------------

These limits apply to data a program writes to the terminal. Each one is a
maximum. ``0``, the default, means there is no limit. Set one only to contain
a program that tries to exhaust memory or time. Goblin View uses
``csi-limit`` and ``escape-limit``. Goblin Skiff uses ``--csi-limit``,
``--escape-limit`` and ``--vector-depth-limit``. The dash, raster and curve
limits apply when Silkie rasterizes a vector image.

``csi_limit``
    The maximum number of bytes in one CSI sequence, everything after ``ESC [``
    up to and including its final byte. A longer sequence is ignored. ``0``
    means a CSI may be of any length. Cursor motion and editing that name a
    count are still clamped to the screen.

``escape_limit``
    The maximum number of bytes in one OSC, APC, DCS, PM or SOS sequence, not
    counting its introducer and terminator. A longer sequence is discarded.
    ``0`` means these sequences may be of any length. Clipboard writes are
    still bounded by ``clipboard_max_size``.

``vector_depth_limit``
    The maximum number of groups a vector element may be nested inside. Deeper
    elements are not drawn. ``0`` means any depth. A cycle in the parent chain
    is rejected either way.

``vector_dash_limit``
    The maximum number of dash boundaries stroked for one path. A path that
    would need more is drawn solid. ``0`` means every dash is stroked.

``vector_raster_limit``
    The maximum number of pixels in the raster of one vector image. A larger
    requested size is scaled down to fit. ``0`` means the image is rasterized
    at the size it is shown.

``vector_curve_limit``
    The maximum number of line segments used to flatten one curve or circle.
    ``0`` means as many segments as the flattening error asks for.
