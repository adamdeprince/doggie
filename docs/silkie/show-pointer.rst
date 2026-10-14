.. include:: ../kittens/show_pointer.rst
   :end-before: .. include:: ../generated/cli-kitten-show_pointer.rst

Command line options
---------------------

.. program:: kitty +kitten show_pointer

.. option:: --only <sources>

   Enable only the named sources, separated by commas. This option may be
   repeated. Sources are ``tools``, ``fingers``, ``pads``, ``actions``,
   ``estimates``, ``accidental``, ``gestures``, ``hold``, and ``scroll``.
   ``tablet-pointer`` and ``gesture`` each select all sources of that protocol.
   By default, all sources the terminal offers are enabled.

.. option:: --ids

   Request hardware identifiers and show them. Without this option, identifiers
   are not requested and any pen serial numbers received are replaced by counters.

.. option:: --raw

   Print the received frames without decoding them, one per line. Other output
   lines begin with ``#``.

.. option:: --timeout <seconds>

   Wait this long for each round of queries. The default is ``2`` seconds.
