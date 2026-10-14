Window actions
===============

Kill an unresponsive window
---------------------------

Silkie adds the ``kill_window`` action. It sends ``SIGKILL`` to the foreground
process group and to the shell, then closes the active terminal window. Use it
when a program no longer responds; the killed programs cannot save their state.

To bind the action in ``kitty.conf``::

    map kitty_mod+k kill_window

On macOS, the Shell menu also provides **Kill Window**. For the mapping syntax
and inherited actions, see `kitty's keyboard mapping documentation
<https://sw.kovidgoyal.net/kitty/mapping/>`_.
