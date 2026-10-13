#!/usr/bin/env python3
# License: GPLv3 Copyright: 2026, Adam DePrince

"""
A Wayland proxy that plays the part of the input devices.

It sits between one client, the terminal under test, and a real compositor,
and forwards everything the two say to each other. On top of that it gives
the client a keyboard, a pointer, a touchscreen, pointer gestures, and the
tablets, tools and pads of the tablet-v2 protocol, none of which exist as far
as the compositor or the kernel are concerned: their events are written by
this program, on request, over a control socket. So a pen, a pad with a dial
or a five finger touch can be played to the client on a machine that has no
such hardware, without root and without creating a device anyone else can see.

The proxy understands the wire format through the protocol XML files, which
is how it knows which messages create objects and which arguments name them.
Objects it invents are answered here and never reach the compositor. See
README.rst for the control commands.
"""

import argparse
import array
import ctypes
import ctypes.util
import glob
import json
import os
import selectors
import socket
import struct
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import IO, Any

SERVER_ID_START = 0xFF000000
FAKE_TABLET_GLOBAL = 0x7AB1E7  # the registry name of the tablet manager made here
FIRST_SERIAL = 0x100000  # far from the compositor's own serials
MAX_FDS = 28  # what libwayland accepts with one message


# The protocols {{{
@dataclass
class Arg:
    name: str
    type: str
    interface: str = ''


@dataclass
class Message:
    name: str
    args: list[Arg]
    destructor: bool = False
    since: int = 1


@dataclass
class Interface:
    name: str
    version: int
    requests: list[Message] = field(default_factory=list)
    events: list[Message] = field(default_factory=list)

    def event(self, name: str) -> tuple[int, Message]:
        for i, m in enumerate(self.events):
            if m.name == name:
                return i, m
        raise KeyError(f'{self.name} has no event named {name}')


def load_protocols(paths: list[str]) -> dict[str, Interface]:
    ans: dict[str, Interface] = {}
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError):
            continue
        for x in root.iter('interface'):
            iface = Interface(x.get('name', ''), int(x.get('version', '1')))
            for kind, dest in (('request', iface.requests), ('event', iface.events)):
                for m in x.findall(kind):
                    args = [Arg(a.get('name', ''), a.get('type', ''), a.get('interface', '')) for a in m.findall('arg')]
                    dest.append(Message(m.get('name', ''), args, m.get('type') == 'destructor', int(m.get('since', '1'))))
            # the same interface can be in several files, the newest version knows every message
            if iface.name not in ans or ans[iface.name].version < iface.version:
                ans[iface.name] = iface
    return ans


def pad4(n: int) -> int:
    return (n + 3) & ~3


def decode(msg: Message, data: bytes) -> tuple[list[Any], list[int]]:
    "The arguments of a message and the offset each object id is at"
    vals: list[Any] = []
    offsets: list[int] = []
    o = 0
    for a in msg.args:
        offsets.append(o)
        if a.type in ('int', 'fixed'):
            (v,) = struct.unpack_from('=i', data, o)
            vals.append(v / 256 if a.type == 'fixed' else v)
            o += 4
        elif a.type in ('uint', 'object') or (a.type == 'new_id' and a.interface):
            vals.append(struct.unpack_from('=I', data, o)[0])
            o += 4
        elif a.type == 'new_id':  # untyped: the interface name and version come first
            (n,) = struct.unpack_from('=I', data, o)
            name = data[o + 4 : o + 4 + n - 1].decode()
            o += 4 + pad4(n)
            version, nid = struct.unpack_from('=II', data, o)
            offsets[-1] = o + 4
            vals.append((name, version, nid))
            o += 8
        elif a.type == 'string':
            (n,) = struct.unpack_from('=I', data, o)
            vals.append(data[o + 4 : o + 4 + n - 1].decode('utf-8', 'replace') if n else None)
            o += 4 + pad4(n)
        elif a.type == 'array':
            (n,) = struct.unpack_from('=I', data, o)
            vals.append(data[o + 4 : o + 4 + n])
            o += 4 + pad4(n)
        else:  # an fd travels beside the data
            vals.append(None)
    return vals, offsets


def encode(msg: Message, vals: list[Any]) -> bytes:
    out = bytearray()
    for a, v in zip(msg.args, vals):
        if a.type == 'int':
            out += struct.pack('=i', int(v))
        elif a.type == 'fixed':
            out += struct.pack('=i', round(float(v) * 256))
        elif a.type in ('uint', 'object', 'new_id'):
            out += struct.pack('=I', int(v or 0) & 0xFFFFFFFF)
        elif a.type == 'string':
            if v is None:
                out += struct.pack('=I', 0)
            else:
                s = str(v).encode() + b'\0'
                out += struct.pack('=I', len(s)) + s + b'\0' * (pad4(len(s)) - len(s))
        elif a.type == 'array':  # as hex, so that what was sent can be logged as JSON
            b = bytes.fromhex(v) if isinstance(v, str) else bytes(v)
            out += struct.pack('=I', len(b)) + b + b'\0' * (pad4(len(b)) - len(b))
    return bytes(out)


def pack(obj: int, opcode: int, payload: bytes) -> bytes:
    return struct.pack('=II', obj, ((8 + len(payload)) << 16) | opcode) + payload


# }}}


def default_keymap() -> bytes:
    "The keymap of the default XKB layout, which a wl_keyboard has to send before anything else"
    lib = ctypes.CDLL(ctypes.util.find_library('xkbcommon') or 'libxkbcommon.so.0')
    lib.xkb_context_new.restype = ctypes.c_void_p
    lib.xkb_keymap_new_from_names.restype = ctypes.c_void_p
    lib.xkb_keymap_new_from_names.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int]
    lib.xkb_keymap_get_as_string.restype = ctypes.c_void_p
    lib.xkb_keymap_get_as_string.argtypes = [ctypes.c_void_p, ctypes.c_int]
    ctx = lib.xkb_context_new(0)
    keymap = lib.xkb_keymap_new_from_names(ctx, None, 0)
    return ctypes.string_at(lib.xkb_keymap_get_as_string(keymap, 1)) + b'\0'


def now_ms() -> int:
    "The time input events carry: milliseconds of CLOCK_MONOTONIC, wrapping at 32 bits"
    return int(time.clock_gettime(time.CLOCK_MONOTONIC) * 1000) & 0xFFFFFFFF


class Closed(Exception):
    pass


class Channel:
    "One direction of the connection: whole messages in, whole messages and their fds out"

    def __init__(self, src: socket.socket, dst: socket.socket) -> None:
        self.src, self.dst = src, dst
        self.buf = bytearray()
        self.fds: list[int] = []

    def read(self) -> list[tuple[int, int, bytes]]:
        fds = array.array('i')
        data, anc, _, _ = self.src.recvmsg(65536, socket.CMSG_LEN(64 * fds.itemsize))
        for level, kind, cdata in anc:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                fds.frombytes(cdata[: len(cdata) - (len(cdata) % fds.itemsize)])
        self.fds.extend(fds)
        if not data:
            raise Closed()
        self.buf += data
        ans = []
        while len(self.buf) >= 8:
            obj, word = struct.unpack_from('=II', self.buf)
            size = word >> 16
            if size < 8:
                raise Closed(f'a message of {size} bytes')
            if len(self.buf) < size:
                break
            ans.append((obj, word & 0xFFFF, bytes(self.buf[8:size])))
            del self.buf[:size]
        return ans

    def write(self, data: bytes, fds: list[int] | None = None) -> None:
        "Sends data on, with the fds that came in since the last write"
        fds = self.fds if fds is None else fds
        while data:
            part = fds[:MAX_FDS]
            del fds[:MAX_FDS]
            # fds that do not fit ride with the next byte
            chunk = data[:1] if fds else data
            if part:
                n = self.dst.sendmsg([chunk], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', part))])
                for fd in part:
                    os.close(fd)
                self.dst.sendall(chunk[n:])
            else:
                self.dst.sendall(chunk)
            data = data[len(chunk) :]


class Connection:
    "The client, the compositor, and the objects that exist only here"

    def __init__(self, rig: 'Rig', client: socket.socket, upstream: socket.socket) -> None:
        self.rig = rig
        self.protocols = rig.protocols
        self.up = Channel(client, upstream)
        self.down = Channel(upstream, client)
        self.client, self.upstream = client, upstream
        # every object the client knows, by the id the client uses for it
        self.objs: dict[int, tuple[Interface, int]] = {1: (self.protocols['wl_display'], 1)}
        self.fake: set[int] = set()
        # server allocated ids are renumbered, since the ones made here share the client's numbering
        self.to_client_id: dict[int, int] = {}
        self.to_upstream_id: dict[int, int] = {}
        self.server_ids = 0
        self.sync_done: set[int] = set()
        self.sync_deleted: set[int] = set()
        self.serial = FIRST_SERIAL
        self.registries: list[int] = []
        self.globals: dict[int, tuple[str, int]] = {}
        self.xdg_surfaces: dict[int, int] = {}
        self.surface = 0  # the wl_surface of the first toplevel
        self.size = (0, 0)
        self.named: dict[str, int] = {}  # the objects control commands can address
        self.by_interface: dict[str, list[int]] = {}
        self.tablet_seat = 0
        self.announced: set[str] = set()

    def log(self, kind: str, text: str) -> None:
        self.rig.log(kind, text)

    # Client to compositor {{{
    def from_client(self, obj: int, opcode: int, payload: bytes) -> bytes:
        up_obj = self.to_upstream_id.get(obj, obj) if obj >= SERVER_ID_START else obj
        ent = self.objs.get(obj)
        if ent is None or opcode >= len(ent[0].requests):
            return pack(up_obj, opcode, payload)
        iface, version = ent
        msg = iface.requests[opcode]
        vals, offsets = decode(msg, payload)
        name = f'{iface.name}.{msg.name}'
        on_fake = obj in self.fake
        mine = (
            on_fake
            or (name == 'wl_registry.bind' and vals[0] == FAKE_TABLET_GLOBAL)
            or name in ('wl_seat.get_pointer', 'wl_seat.get_keyboard', 'wl_seat.get_touch')
            or any(a.type == 'object' and v in self.fake for a, v in zip(msg.args, vals))
        )
        out = b''
        for a, v in zip(msg.args, vals):
            if a.type != 'new_id':
                continue
            niface, nversion, nid = (a.interface, version, v) if a.interface else v
            if niface in self.protocols:
                self.objs[nid] = self.protocols[niface], nversion
            if mine:
                self.fake.add(nid)
                self.by_interface.setdefault(niface, []).append(nid)
                # the compositor must see the id used, or the client's next id is out of sequence
                out += pack(1, 0, struct.pack('=I', nid))
                self.sync_done.add(nid)
                self.sync_deleted.add(nid)
        if mine:
            self.fake_request(name, obj, vals)
            if on_fake and msg.destructor:
                self.forget(obj)
            return out
        if name == 'wl_display.get_registry':
            self.registries.append(vals[0])
            if self.rig.tablet_version:
                self.send(vals[0], 'global', FAKE_TABLET_GLOBAL, 'zwp_tablet_manager_v2', self.rig.tablet_version, quiet=True)
        elif name == 'xdg_wm_base.get_xdg_surface':
            self.xdg_surfaces[vals[0]] = vals[1]
        elif name == 'xdg_surface.get_toplevel' and not self.surface:
            self.surface = self.xdg_surfaces.get(obj, 0)
            self.log('toplevel', f'surface {self.surface}')
        p = bytearray(payload)
        for a, v, o in zip(msg.args, vals, offsets):
            if a.type == 'object' and isinstance(v, int) and v >= SERVER_ID_START:
                struct.pack_into('=I', p, o, self.to_upstream_id.get(v, v))
        if msg.destructor and obj >= SERVER_ID_START:
            self.objs.pop(obj, None)
            self.to_client_id.pop(self.to_upstream_id.pop(obj, 0), None)
        return pack(up_obj, opcode, bytes(p))

    def forget(self, obj: int) -> None:
        self.fake.discard(obj)
        self.objs.pop(obj, None)
        for objs in self.by_interface.values():
            if obj in objs:
                objs.remove(obj)
        for k in [k for k, v in self.named.items() if v == obj]:
            del self.named[k]
        if obj < SERVER_ID_START:
            self.down.write(pack(1, 1, struct.pack('=I', obj)), [])  # wl_display.delete_id

    def fake_request(self, name: str, obj: int, vals: list[Any]) -> None:
        if name == 'wl_seat.get_keyboard':
            self.send_keymap(vals[0])
        elif name == 'zwp_tablet_manager_v2.get_tablet_seat':
            self.tablet_seat = vals[0]
            self.announce()
        if name not in ('wl_pointer.set_cursor', 'wl_registry.bind', 'wl_seat.get_pointer', 'wl_seat.get_keyboard', 'wl_seat.get_touch'):
            who = next((k for k, v in self.named.items() if v == obj), str(obj))
            self.log('request', f'{name} on {who} {json.dumps(vals)}')

    # }}}

    # Compositor to client {{{
    def new_server_id(self) -> int:
        self.server_ids += 1
        return SERVER_ID_START + self.server_ids - 1

    def from_upstream(self, obj: int, opcode: int, payload: bytes) -> bytes:
        if obj == 1 and opcode == 1:  # wl_display.delete_id
            (i,) = struct.unpack('=I', payload)
            if i in self.sync_deleted:
                self.sync_deleted.discard(i)
                return b''
            self.objs.pop(i, None)
            self.xdg_surfaces.pop(i, None)
            return pack(obj, opcode, payload)
        if obj in self.sync_done:
            self.sync_done.discard(obj)
            return b''
        cobj = obj
        if obj >= SERVER_ID_START:
            if obj not in self.to_client_id:
                self.log('warning', f'the compositor used object {obj:#x}, which no known message created')
                self.to_client_id[obj] = cid = self.new_server_id()
                self.to_upstream_id[cid] = obj
            cobj = self.to_client_id[obj]
        ent = self.objs.get(cobj)
        if ent is None or opcode >= len(ent[0].events):
            return pack(cobj, opcode, payload)
        iface, version = ent
        msg = iface.events[opcode]
        vals, offsets = decode(msg, payload)
        name = f'{iface.name}.{msg.name}'
        p = bytearray(payload)
        for a, v, o in zip(msg.args, vals, offsets):
            if a.type == 'new_id':
                cid = self.new_server_id()
                self.to_client_id[v], self.to_upstream_id[cid] = cid, v
                if a.interface in self.protocols:
                    self.objs[cid] = self.protocols[a.interface], version
                struct.pack_into('=I', p, o, cid)
            elif a.type == 'object' and isinstance(v, int) and v >= SERVER_ID_START:
                struct.pack_into('=I', p, o, self.to_client_id.get(v, v))
        if name == 'wl_display.error':
            self.log('error', f'the compositor reports a protocol error: object {vals[0]} code {vals[1]}: {vals[2]}')
        elif name == 'wl_registry.global':
            self.globals[vals[0]] = vals[1], vals[2]
            if vals[1] == 'zwp_tablet_manager_v2':
                self.log('compositor', f'offers zwp_tablet_manager_v2 version {vals[2]}, replaced by the one made here')
                return b''
        elif name == 'wl_seat.capabilities':
            self.log('compositor', f'seat capabilities {vals[0]}, sent on as {vals[0] | self.rig.capabilities}')
            struct.pack_into('=I', p, 0, vals[0] | self.rig.capabilities)
        elif name == 'xdg_toplevel.configure' and vals[0] and vals[1]:
            self.size = vals[0], vals[1]
        return pack(cobj, opcode, bytes(p))

    # }}}

    # Events made here {{{
    def send(self, obj: int, event: str, *args: Any, fds: list[int] | None = None, quiet: bool = False) -> list[int]:
        "Sends an event to the client, returning the ids of the objects it creates"
        iface, version = self.objs[obj]
        opcode, msg = iface.event(event)
        if msg.since > version:
            self.log('skipped', f'{iface.name}.{event}: the client bound version {version}, this needs {msg.since}')
            return []
        vals = list(args)
        created = []
        for i, a in enumerate(msg.args):
            if a.type == 'new_id':
                cid = self.new_server_id()
                self.objs[cid] = self.protocols[a.interface], version
                self.fake.add(cid)
                self.by_interface.setdefault(a.interface, []).append(cid)
                vals.insert(i, cid)
                created.append(cid)
            elif a.type == 'fd':
                vals.insert(i, None)
        if len(vals) != len(msg.args):
            raise ValueError(f'{iface.name}.{event} takes {[a.name for a in msg.args if a.type not in ("new_id", "fd")]}')
        self.down.write(pack(obj, opcode, encode(msg, vals)), fds or [])
        if not quiet:
            who = next((k for k, v in self.named.items() if v == obj), iface.name)
            self.log('event', f'{who} {event} {json.dumps(list(args))}')
        return created

    def next_serial(self) -> int:
        self.serial += 1
        return self.serial

    def send_keymap(self, keyboard: int) -> None:
        keymap = self.rig.keymap
        fd = os.memfd_create('rig-keymap')
        os.write(fd, keymap)
        self.send(keyboard, 'keymap', 1, len(keymap), fds=[fd], quiet=True)
        self.send(keyboard, 'repeat_info', 25, 600, quiet=True)

    def announce(self) -> None:
        "Tells the client about the tablets, tools and pads it has not heard of yet"
        if not self.tablet_seat:
            return
        seat = self.tablet_seat
        for key, d in self.rig.devices.items():
            if key in self.announced:
                continue
            self.announced.add(key)
            kind, _, name = key.partition(':')
            if kind == 'tablet':
                (t,) = self.send(seat, 'tablet_added')
                self.named[key] = t
                self.send(t, 'name', d['name'])
                self.send(t, 'id', d.get('vid', 0), d.get('pid', 0))
                for path in d.get('paths', ()):
                    self.send(t, 'path', path)
                self.send(t, 'bustype', d.get('bustype', 3))
                self.send(t, 'done')
            elif kind == 'tool':
                (t,) = self.send(seat, 'tool_added')
                self.named[key] = t
                self.send(t, 'type', TOOL_TYPES[d['type']])
                if d.get('serial'):
                    self.send(t, 'hardware_serial', d['serial'] >> 32, d['serial'] & 0xFFFFFFFF)
                if d.get('hwid'):
                    self.send(t, 'hardware_id_wacom', d['hwid'] >> 32, d['hwid'] & 0xFFFFFFFF)
                for cap in d.get('caps', ()):
                    self.send(t, 'capability', TOOL_CAPABILITIES[cap])
                self.send(t, 'done')
            elif kind == 'pad':
                (pad,) = self.send(seat, 'pad_added')
                self.named[key] = pad
                for gi, g in enumerate(d.get('groups', ())):
                    (group,) = self.send(pad, 'group')
                    self.named[f'group:{name}:{gi}'] = group
                    self.send(group, 'buttons', struct.pack(f'={len(g.get("buttons", ()))}I', *g.get('buttons', ())).hex())
                    for what in ('ring', 'strip', 'dial'):
                        for i in range(g.get(what + 's', 0)):
                            # a dial needs version 2, which an older client does not have
                            for x in self.send(group, what):
                                self.named[f'{what}:{name}:{gi}:{i}'] = x
                    self.send(group, 'modes', g.get('modes', 1))
                    self.send(group, 'done')
                for path in d.get('paths', ()):
                    self.send(pad, 'path', path)
                self.send(pad, 'buttons', d.get('buttons', 0))
                self.send(pad, 'done')

    def resolve(self, name: str) -> int:
        "The object a control command names: a device, or the first object of an interface"
        if name in self.named:
            return self.named[name]
        objs = self.by_interface.get(ALIASES.get(name, name))
        if not objs:
            raise KeyError(f'the client has no {name}')
        return objs[0]

    def play(self, target: str, events: list[list[Any]]) -> None:
        obj = self.resolve(target)
        iface = self.objs[obj][0]
        now = now_ms()  # one clock reading, so the times within a command are exactly as far apart as it says
        for name, *args in events:
            _, msg = iface.event(name)
            types = [a.type for a in msg.args if a.type not in ('new_id', 'fd')]
            vals = []
            for kind, v in zip(types, args):
                if v == '$serial':
                    v = self.next_serial()
                elif v == '$surface':
                    if not self.surface:
                        raise RuntimeError('the client has no window yet')
                    v = self.surface
                elif isinstance(v, str) and v.startswith('$time'):
                    v = (now + int(v[5:] or 0)) & 0xFFFFFFFF
                elif kind == 'object' and isinstance(v, str):
                    v = self.resolve(v)
                elif kind == 'array' and not isinstance(v, str):  # a list of numbers
                    v = struct.pack(f'={len(v)}I', *v).hex()
                vals.append(v)
            if len(vals) != len(types) or len(args) != len(types):
                raise ValueError(f'{iface.name}.{name} takes {[a.name for a in msg.args if a.type not in ("new_id", "fd")]}')
            self.send(obj, name, *vals)

    # }}}


TOOL_TYPES = {'pen': 0x140, 'eraser': 0x141, 'brush': 0x142, 'pencil': 0x143, 'airbrush': 0x144, 'finger': 0x145, 'mouse': 0x146, 'lens': 0x147}
TOOL_CAPABILITIES = {'tilt': 1, 'pressure': 2, 'distance': 3, 'rotation': 4, 'slider': 5, 'wheel': 6}
ALIASES = {
    'keyboard': 'wl_keyboard',
    'pointer': 'wl_pointer',
    'touch': 'wl_touch',
    'swipe': 'zwp_pointer_gesture_swipe_v1',
    'pinch': 'zwp_pointer_gesture_pinch_v1',
    'hold': 'zwp_pointer_gesture_hold_v1',
    'cursor-shape': 'wp_cursor_shape_device_v1',
}


class Rig:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        xml = ['/usr/share/wayland/wayland.xml', *glob.glob('/usr/share/wayland-protocols/**/*.xml', recursive=True)]
        for d in args.xml:
            xml += glob.glob(os.path.join(d, '*.xml'))
        self.protocols = load_protocols(xml)
        self.tablet_version = args.tablet_version
        self.capabilities = args.capabilities
        self.keymap = default_keymap()
        self.devices: dict[str, dict[str, Any]] = {}
        self.conn: Connection | None = None
        self.logfile: IO[str] = open(args.log, 'w', buffering=1) if args.log else sys.stderr
        self.sel = selectors.DefaultSelector()
        self.listener = self.listen(args.listen)
        self.control = self.listen(args.control)
        self.sel.register(self.listener, selectors.EVENT_READ, self.accept)
        self.sel.register(self.control, selectors.EVENT_READ, self.accept_control)

    def log(self, kind: str, text: str) -> None:
        self.logfile.write(f'{time.monotonic():.6f} {kind} {text}\n')

    def listen(self, path: str) -> socket.socket:
        if os.path.exists(path):
            os.unlink(path)
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.bind(path)
        s.listen(4)
        return s

    def accept(self) -> None:
        client, _ = self.listener.accept()
        if self.conn is not None:
            self.log('warning', 'a second client connected while the first is running, refused')
            client.close()
            return
        upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        upstream.connect(self.args.upstream)
        self.conn = c = Connection(self, client, upstream)
        self.sel.register(client, selectors.EVENT_READ, lambda: self.relay(c.up, c.from_client))
        self.sel.register(upstream, selectors.EVENT_READ, lambda: self.relay(c.down, c.from_upstream))
        self.log('client', 'connected')

    def relay(self, channel: Channel, handle: Any) -> None:
        c = self.conn
        assert c is not None
        try:
            out = b''.join(handle(*m) for m in channel.read())
            if out:
                channel.write(out)
        except (Closed, OSError) as e:
            self.log('client', f'disconnected {e}')
            for s in (c.client, c.upstream):
                self.sel.unregister(s)
                s.close()
            self.conn = None

    def accept_control(self) -> None:
        s, _ = self.control.accept()
        buf = bytearray()
        self.sel.register(s, selectors.EVENT_READ, lambda: self.read_control(s, buf))

    def read_control(self, s: socket.socket, buf: bytearray) -> None:
        data = s.recv(1 << 16)
        if not data:
            self.sel.unregister(s)
            s.close()
            return
        buf += data
        *lines, rest = bytes(buf).split(b'\n')
        buf[:] = rest
        for line in lines:
            try:
                ans = self.command(json.loads(line)) or {}
                ans['ok'] = True
            except Exception as e:
                ans = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
                self.log('error', f'{line.decode(errors="replace")}: {ans["error"]}')
            s.sendall(json.dumps(ans).encode() + b'\n')

    def command(self, cmd: dict[str, Any]) -> dict[str, Any] | None:
        op = cmd['op']
        c = self.conn
        if op == 'add':  # a tablet, tool or pad, see README.rst
            self.devices[cmd['device']] = cmd
            if c is not None:
                c.announce()
            return None
        if op == 'info':
            if c is None:
                return {'connected': False}
            return {
                'connected': True,
                'surface': c.surface,
                'size': c.size,
                'named': sorted(c.named),
                'interfaces': {k: [c.objs[o][1] for o in v] for k, v in c.by_interface.items() if v},
                'globals': {v[0]: v[1] for v in c.globals.values()},
            }
        if c is None:
            raise RuntimeError('no client is connected')
        if op == 'play':
            c.play(cmd['to'], cmd['events'])
        elif op == 'quit':
            raise SystemExit(0)
        else:
            raise ValueError(f'unknown op {op}')
        return None

    def run(self) -> None:
        self.log('rig', f'listening on {self.args.listen}, tablet-v2 version {self.tablet_version}')
        while True:
            for key, _ in self.sel.select():
                key.data()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--listen', required=True, help='The socket the client connects to, the full path of its WAYLAND_DISPLAY')
    p.add_argument('--upstream', required=True, help='The socket of the real compositor')
    p.add_argument('--control', required=True, help='The socket control commands arrive on')
    p.add_argument('--log', help='Where to log what is sent and what the client asks of the invented objects, stderr by default')
    p.add_argument('--xml', action='append', default=[], help='A directory with more protocol XML files, the glfw directory of the tree under test')
    p.add_argument(
        '--tablet-version', type=int, default=2, help='The version of tablet-v2 to offer: 2 has dials, 1 is what sway 1.11 has, 0 offers no tablets at all'
    )
    p.add_argument('--capabilities', type=int, default=7, help='The seat capabilities to add: 1 pointer, 2 keyboard, 4 touch')
    args = p.parse_args()
    try:
        Rig(args).run()
    finally:
        for path in (args.listen, args.control):
            if os.path.exists(path):
                os.unlink(path)


if __name__ == '__main__':
    main()
