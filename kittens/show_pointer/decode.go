// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"encoding/base64"
	"fmt"
	"strings"
)

var _ = fmt.Print

// The names of the bits of a bit set, lowest bit first
type bit_names []string

// The names of the set bits, joined by sep. Bits that have no name are shown
// as a number, so that a bit added to a protocol later is not lost
func (self bit_names) describe(value int64, sep, when_zero string) string {
	if value == 0 {
		return when_zero
	}
	var ans []string
	var unknown int64
	for i := range 63 {
		if bit := int64(1) << i; value&bit != 0 {
			if i < len(self) && self[i] != "" {
				ans = append(ans, self[i])
			} else {
				unknown |= bit
			}
		}
	}
	if value < 0 {
		unknown |= -1 << 63
	}
	if unknown != 0 {
		ans = append(ans, fmt.Sprintf("%#x", uint64(unknown)))
	}
	return strings.Join(ans, sep)
}

// The name of a value, or the empty string when the value has none
type value_names []string

func (self value_names) name(value int64) string {
	if 0 <= value && value < int64(len(self)) {
		return self[value]
	}
	return ""
}

var (
	tablet_cap_names  = bit_names{"tools", "fingers on a touchscreen", "fingers on a touchpad", "the shape of a finger contact", "pads", "tool actions", "hardware identifiers", "estimated and predicted samples", "accidental contacts"}
	tablet_mode_names = bit_names{"tools", "fingers", "pads", "hardware identifiers", "tool actions", "estimated and predicted samples", "accidental contacts"}
	tablet_mode_short = bit_names{"tools", "fingers", "pads", "ids", "actions", "estimates", "accidental"}
	measurement_names = bit_names{"pressure", "tilt", "twist", "tangent", "z", "distance", "wheel", "shape", "place", "grip"}
	button_names      = bit_names{"tip", "barrel", "barrel2", "back", "forward", "barrel3"}
	modifier_names    = bit_names{"shift", "alt", "ctrl", "super"}
	gesture_cap_names = bit_names{"pinch", "rotate", "swipe", "smart zoom", "hold"}
	gesture_modes     = bit_names{"pinch, rotate, swipe and smart zoom", "hold"}
	gesture_short     = bit_names{"gestures", "hold"}
	scroll_cap_names  = bit_names{"pixel distances"}
	on_off            = bit_names{"on"}

	report_kinds    = value_names{"", "tool", "finger", "pad", "action"}
	contact_phases  = value_names{"hover", "down", "move", "up", "cancel", "out", "frame", "correction"}
	tool_names      = value_names{"finger", "pen", "eraser", "brush", "pencil", "airbrush", "mouse", "lens", "totem"}
	action_names    = value_names{"", "double-tap", "squeeze", "tail-click", "tail-double-click", "tail-hold", "docked", "undocked", "air-motion"}
	gesture_kinds   = value_names{"", "pinch", "rotate", "swipe", "smart-zoom", "hold"}
	gesture_phases  = value_names{"", "begin", "update", "end", "cancel"}
	scroll_sources  = value_names{"wheel", "precise"}
	scroll_phases   = value_names{"", "began", "moving", "ended", "coasting-began", "coasting", "coasting-ended", "cancelled"}
	pad_button_text = value_names{"released", "pressed"}
	action_states   = value_names{"ended", "began", "moving"}
	confidence      = value_names{"accidental", "meant"}
	surface_kinds   = value_names{"not-a-display", "display"}
	line_styles     = value_names{"", "ink", "pencil", "highlighter", "chisel-marker", "brush"}
)

// The size of the cell area and of a cell in pixels, zero when unknown
type geometry struct {
	width, height, cell_width, cell_height int64
}

// Turns frames into one line of text each. Every field of a frame is shown:
// the ones this program knows with a name and a unit, the rest as they came
type decoder struct {
	geometry geometry
	show_ids bool
	serials  map[string]int
	// When each stream of reports was last heard from, in microseconds
	last_time map[string]int64
}

func new_decoder(show_ids bool) *decoder {
	return &decoder{show_ids: show_ids, serials: make(map[string]int), last_time: make(map[string]int64)}
}

// A serial number identifies one pen, and with it its owner, so unless asked
// for it is replaced by a counter that still tells two pens apart
func (self *decoder) serial(value string) string {
	if self.show_ids {
		return printable(value)
	}
	n, found := self.serials[value]
	if !found {
		n = len(self.serials) + 1
		self.serials[value] = n
	}
	return fmt.Sprintf("#%d", n)
}

func (self *decoder) hide_ids(f Field) (string, bool) {
	if f.Key == "serial" && !self.show_ids {
		return self.serial(f.Value), true
	}
	return "", false
}

// The frame as it came, with serial numbers replaced unless they were asked for
func (self *decoder) raw(f *Frame) string { return f.Raw(self.hide_ids) }

// Positions are in 1/256 of a pixel
func pixels(v int64) string {
	if ans := fmt.Sprintf("%.2f", float64(v)/256); ans != "-0.00" {
		return ans
	}
	return "0.00"
}

func degrees(v int64) string { return fmt.Sprintf("%.2f°", float64(v)/100) }

func fraction(v, of int64) string {
	return fmt.Sprintf("%.3f", float64(v)/float64(of))
}

func floor_div(a, b int64) int64 {
	q := a / b
	if (a%b != 0) && ((a < 0) != (b < 0)) {
		q--
	}
	return q
}

// The cell under a position given in 1/256 of a pixel
func (self *decoder) cell(x, y int64) string {
	g := self.geometry
	if g.cell_width <= 0 || g.cell_height <= 0 {
		return ""
	}
	return fmt.Sprintf("cell=%d,%d", floor_div(x, 256*g.cell_width), floor_div(y, 256*g.cell_height))
}

func take_version(r *reader) {
	if v, found := r.frame.Get("v"); found && v == "1" {
		r.skip("v")
	}
}

// A field whose value is one of a set of numbers with names
func named(r *reader, key string, names value_names) string {
	if i := r.index(key); i >= 0 {
		if v, ok := parse_int(r.frame.Fields[i].Value); ok {
			if name := names.name(v); name != "" {
				r.used[i] = true
				return name
			}
		}
	}
	return ""
}

func add(parts []string, items ...string) []string {
	for _, x := range items {
		if x != "" {
			parts = append(parts, x)
		}
	}
	return parts
}

func mods(r *reader) string {
	if v, ok := r.take_int("mods"); ok {
		return "mods=" + modifier_names.describe(v, "+", "none")
	}
	return ""
}

// The time of a report and how long after the previous report of the same
// stream it came, which is what shows the rate a device reports at
func (self *decoder) time(r *reader, stream string, starts_stream bool) (ans []string) {
	i := r.index("t")
	if i < 0 {
		return
	}
	t, ok := parse_int(r.frame.Fields[i].Value)
	if !ok {
		return
	}
	r.used[i] = true
	us, text, fine := t*1000, fmt.Sprintf("t=%dms", t), false
	if j := r.index("tu"); j >= 0 {
		if tu, ok := parse_int(r.frame.Fields[j].Value); ok && 0 <= tu && tu < 1000 {
			r.used[j] = true
			us += tu
			text, fine = fmt.Sprintf("t=%d.%03dms", t, tu), true
		}
	}
	ans = append(ans, text)
	if prev, found := self.last_time[stream]; found && !starts_stream {
		if fine {
			ans = append(ans, fmt.Sprintf("dt=%.3fms", float64(us-prev)/1000))
		} else {
			ans = append(ans, fmt.Sprintf("dt=%dms", (us-prev)/1000))
		}
	}
	if len(self.last_time) > 1024 {
		clear(self.last_time)
	}
	self.last_time[stream] = us
	return
}

func (self *decoder) ids(r *reader) (ans []string) {
	if serial, found := r.take("serial"); found {
		ans = append(ans, "serial="+self.serial(serial))
	}
	if hwid, ok := r.take_int("hwid"); ok {
		ans = append(ans, fmt.Sprintf("hwid=%#x", uint64(hwid)))
	}
	if vid, pid, ok := r.take_pair("vid", "pid"); ok {
		ans = append(ans, fmt.Sprintf("usb=%04x:%04x", uint64(vid), uint64(pid)))
	}
	return
}

// One line describing any frame
func (self *decoder) describe(f *Frame) string {
	r := new_reader(f)
	take_version(r)
	var parts []string
	switch f.Selector {
	case "tablet-pointer":
		parts = self.tablet(r)
	case "gesture":
		parts = self.gesture(r)
	case "scroll":
		parts = self.scroll(r)
	default:
		parts = []string{printable(f.Selector)}
	}
	return strings.Join(append(parts, r.rest()...), " ")
}

func (self *decoder) tablet(r *reader) []string {
	parts := []string{"tablet"}
	op, _ := r.frame.Get("op")
	switch op {
	case "event":
		r.skip("op")
		kind, _ := r.frame.Int("kind")
		switch name := report_kinds.name(kind); kind {
		case 1, 2:
			r.skip("kind")
			return append(parts, self.contact(r, name)...)
		case 3:
			r.skip("kind")
			return append(parts, self.pad(r)...)
		case 4:
			r.skip("kind")
			return append(parts, self.action(r)...)
		}
		return append(parts, "event")
	case "device":
		r.skip("op")
		return append(parts, self.device(r)...)
	case "cap":
		r.skip("op")
		parts = append(parts, "capabilities")
		if v, ok := r.take_int("caps"); ok {
			parts = append(parts, "can-report="+tablet_cap_names.describe(v, ", ", "nothing"))
		}
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+tablet_mode_short.describe(v, "+", "off"))
		}
		if w, h, ok := r.take_pair("w", "h"); ok {
			parts = append(parts, fmt.Sprintf("area=%dx%dpx", w, h))
		}
		if w, h, ok := r.take_pair("cw", "ch"); ok {
			parts = append(parts, fmt.Sprintf("cell=%dx%dpx", w, h))
		}
	case "mode":
		r.skip("op")
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+tablet_mode_short.describe(v, "+", "off"))
		}
	}
	return parts
}

// A report of a tool or a finger
func (self *decoder) contact(r *reader, kind string) []string {
	parts := []string{kind}
	phase, has_phase := r.frame.Int("phase")
	parts = add(parts, named(r, "phase", contact_phases))
	device, _ := r.frame.Get("device")
	contact, _ := r.frame.Get("contact")
	stream := kind + "/" + device + "/" + contact
	if v, found := r.take("device"); found {
		parts = append(parts, "device="+printable(v))
	}
	if v, found := r.take("contact"); found {
		parts = append(parts, "contact="+printable(v))
	}
	if name := named(r, "tool", tool_names); name != "" {
		parts = append(parts, "tool="+name)
	}
	on_touchpad := false
	if v, found := r.frame.Get("src"); found && v == "1" {
		r.skip("src")
		on_touchpad = true
		parts = append(parts, "touchpad")
	}
	if x, y, ok := r.take_pair("x", "y"); ok {
		if on_touchpad {
			parts = append(parts, fmt.Sprintf("at=%.1f%%,%.1f%%", float64(x)/655.35, float64(y)/655.35))
		} else {
			parts = add(parts, "x="+pixels(x)+"px", "y="+pixels(y)+"px", self.cell(x, y))
		}
	}
	if w, h, ok := r.take_pair("w", "h"); ok {
		parts = append(parts, fmt.Sprintf("pad=%.1fx%.1fmm", float64(w)/256, float64(h)/256))
	}
	if v, ok := r.take_int("buttons"); ok {
		parts = append(parts, "buttons="+button_names.describe(v, "+", "none"))
	}
	parts = add(parts, mods(r))
	if v, ok := r.take_int("valid"); ok {
		parts = append(parts, "valid="+measurement_names.describe(v, "+", "none"))
	}
	if v, ok := r.take_int("p"); ok {
		parts = append(parts, "pressure="+fraction(v, 65535))
	}
	if v, ok := r.take_int("stage"); ok {
		parts = append(parts, fmt.Sprintf("stage=%d", v))
	}
	if x, y, ok := r.take_pair("tx", "ty"); ok {
		parts = append(parts, "tilt="+degrees(x)+","+degrees(y))
	}
	if v, ok := r.take_int("twist"); ok {
		parts = append(parts, "twist="+degrees(v))
	}
	if v, ok := r.take_int("tangent"); ok {
		parts = append(parts, "tangent="+fraction(v, 65535))
	}
	if v, ok := r.take_int("z"); ok {
		parts = append(parts, fmt.Sprintf("z=%d", v))
	}
	if v, ok := r.take_int("dist"); ok {
		parts = append(parts, "distance="+fraction(v, 65535))
	}
	if v, ok := r.take_int("wheel"); ok {
		parts = append(parts, "wheel="+degrees(v))
	}
	if v, ok := r.take_int("wclicks"); ok {
		parts = append(parts, fmt.Sprintf("clicks=%d", v))
	}
	if major, minor, ok := r.take_pair("major", "minor"); ok {
		shape := "shape=" + pixels(major) + "x" + pixels(minor) + "px"
		if v, ok := r.take_int("angle"); ok {
			shape += "@" + degrees(v)
		}
		parts = append(parts, shape)
	}
	// Where the tool is on its tablet, whatever the system made of that for the pointer
	if x, y, ok := r.take_pair("rx", "ry"); ok {
		parts = append(parts, fmt.Sprintf("on-tablet=%.1f%%,%.1f%%", float64(x)/655.35, float64(y)/655.35))
	}
	if v, ok := r.take_int("grip"); ok {
		parts = append(parts, "grip="+fraction(v, 65535))
	}
	// Whether the system takes a finger to be meant or to be a palm, under the name the protocol has for it
	if name := named(r, "conf", confidence); name != "" {
		parts = append(parts, "conf="+name)
	}
	// Which of the measurements are estimates the terminal may correct later
	if v, ok := r.take_int("est"); ok {
		parts = append(parts, "estimated="+measurement_names.describe(v, "+", "none"))
	}
	if v, found := r.frame.Get("pred"); found && v == "1" {
		r.skip("pred")
		parts = append(parts, "predicted")
	}
	parts = append(parts, self.ids(r)...)
	return append(parts, self.time(r, stream, has_phase && phase == 1)...)
}

// A report of the keys, rings, strips and dials on the body of a tablet
func (self *decoder) pad(r *reader) []string {
	parts := []string{"pad"}
	device, _ := r.frame.Get("device")
	if v, found := r.take("device"); found {
		parts = append(parts, "device="+printable(v))
	}
	if v, ok := r.take_int("button"); ok {
		parts = add(parts, fmt.Sprintf("button=%d", v), named(r, "state", pad_button_text))
	}
	stopped := func() {
		if v, found := r.frame.Get("stop"); found && v == "1" {
			r.skip("stop")
			parts = append(parts, "stopped")
		}
	}
	if v, ok := r.take_int("ring"); ok {
		parts = append(parts, fmt.Sprintf("ring=%d", v))
		if a, ok := r.take_int("angle"); ok {
			parts = append(parts, "angle="+degrees(a))
		}
		stopped()
	}
	if v, ok := r.take_int("strip"); ok {
		parts = append(parts, fmt.Sprintf("strip=%d", v))
		if p, ok := r.take_int("pos"); ok {
			parts = append(parts, "position="+fraction(p, 65535))
		}
		stopped()
	}
	if v, ok := r.take_int("dial"); ok {
		parts = append(parts, fmt.Sprintf("dial=%d", v))
		if d, ok := r.take_int("delta"); ok {
			parts = append(parts, fmt.Sprintf("turned=%+.2fdetents", float64(d)/120))
		}
	}
	if v, found := r.frame.Get("src"); found && v == "1" {
		r.skip("src")
		parts = append(parts, "by-finger")
	}
	parts = add(parts, mods(r))
	return append(parts, self.time(r, "pad/"+device, false)...)
}

// Something done with a tool that is not a button being held, such as a double
// tap on the barrel
func (self *decoder) action(r *reader) []string {
	parts := []string{"action"}
	device, _ := r.frame.Get("device")
	if v, found := r.take("device"); found {
		parts = append(parts, "device="+printable(v))
	}
	// An action that lasts, as a squeeze does, begins and ends
	parts = add(parts, named(r, "action", action_names), named(r, "state", action_states))
	// How far a tool moved through the air, in units of its own
	if x, y, ok := r.take_pair("dx", "dy"); ok {
		parts = append(parts, fmt.Sprintf("moved=%+d,%+d", x, y))
	}
	if x, y, ok := r.take_pair("x", "y"); ok {
		parts = add(parts, "x="+pixels(x)+"px", "y="+pixels(y)+"px", self.cell(x, y))
	}
	parts = add(parts, mods(r))
	return append(parts, self.time(r, "action/"+device, true)...)
}

// The description of a tool or pad the terminal sends before its first report
func (self *decoder) device(r *reader) []string {
	parts := []string{"device"}
	if v, found := r.take("device"); found {
		parts = append(parts, "device="+printable(v))
	}
	if name := named(r, "kind", report_kinds); name != "" {
		parts = append(parts, "kind="+name)
	}
	if name := named(r, "tool", tool_names); name != "" {
		parts = append(parts, "tool="+name)
	}
	if v, ok := r.take_int("axes"); ok {
		parts = append(parts, "measures="+measurement_names.describe(v, "+", "nothing"))
	}
	if i := r.index("name"); i >= 0 {
		if name, ok := decode_name(r.frame.Fields[i].Value); ok {
			r.used[i] = true
			parts = append(parts, fmt.Sprintf("name=%q", name))
		}
	}
	if v, ok := r.take_int("bat"); ok {
		parts = append(parts, fmt.Sprintf("battery=%d%%", v))
	}
	// The tablet the tool is on or the pad belongs to, and its active surface
	if v, ok := r.take_int("tablet"); ok {
		parts = append(parts, fmt.Sprintf("tablet=%d", v))
	}
	if w, h, ok := r.take_pair("w", "h"); ok {
		parts = append(parts, fmt.Sprintf("surface=%.1fx%.1fmm", float64(w)/256, float64(h)/256))
	}
	parts = add(parts, named(r, "direct", surface_kinds))
	// What is stored in the pen itself
	if i := r.index("pcolor"); i >= 0 {
		if v := r.frame.Fields[i].Value; len(v) == 6 && strings.Trim(v, "0123456789abcdefABCDEF") == "" {
			r.used[i] = true
			parts = append(parts, "color=#"+strings.ToLower(v))
		}
	}
	if v, ok := r.take_int("pwidth"); ok {
		parts = append(parts, fmt.Sprintf("width=%.2fmm", float64(v)/256))
	}
	if name := named(r, "pstyle", line_styles); name != "" {
		parts = append(parts, "style="+name)
	}
	return append(parts, self.ids(r)...)
}

// Names are UTF-8 sent as base64, with or without its padding
func decode_name(value string) (string, bool) {
	raw, err := base64.RawStdEncoding.DecodeString(strings.TrimRight(value, "="))
	if err != nil {
		return "", false
	}
	return printable(string(raw)), true
}

func (self *decoder) gesture(r *reader) []string {
	parts := []string{"gesture"}
	op, _ := r.frame.Get("op")
	switch op {
	case "event":
		r.skip("op")
		kind, _ := r.frame.Int("kind")
		name := named(r, "kind", gesture_kinds)
		if name == "" {
			return append(parts, "event")
		}
		parts = add(parts, name, named(r, "phase", gesture_phases))
		if x, y, ok := r.take_pair("x", "y"); ok {
			parts = add(parts, "x="+pixels(x)+"px", "y="+pixels(y)+"px", self.cell(x, y))
		}
		parts = add(parts, mods(r))
		if v, ok := r.take_int("fingers"); ok {
			parts = append(parts, fmt.Sprintf("fingers=%d", v))
		}
		switch kind {
		case 1:
			if v, ok := r.take_int("scale"); ok {
				parts = append(parts, fmt.Sprintf("scale=%+.1f%%", float64(v)/10))
			}
			if v, ok := r.take_int("total"); ok {
				parts = append(parts, fmt.Sprintf("total=x%.3f", float64(v)/1000))
			}
		case 2:
			if v, ok := r.take_int("angle"); ok {
				parts = append(parts, fmt.Sprintf("angle=%+.2f°", float64(v)/100))
			}
			if v, ok := r.take_int("total"); ok {
				parts = append(parts, fmt.Sprintf("total=%+.2f°", float64(v)/100))
			}
		case 3:
			dx, _ := r.frame.Int("dx")
			dy, _ := r.frame.Int("dy")
			direction := ""
			switch {
			case dx == 1 && dy == 0:
				direction = "right"
			case dx == -1 && dy == 0:
				direction = "left"
			case dx == 0 && dy == 1:
				direction = "down"
			case dx == 0 && dy == -1:
				direction = "up"
			}
			if direction != "" && r.has("dx") && r.has("dy") {
				r.skip("dx", "dy")
				parts = append(parts, "direction="+direction)
			}
		}
	case "cap":
		r.skip("op")
		parts = append(parts, "capabilities")
		if v, ok := r.take_int("caps"); ok {
			parts = append(parts, "can-report="+gesture_cap_names.describe(v, ", ", "nothing"))
		}
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+gesture_short.describe(v, "+", "off"))
		}
	case "mode":
		r.skip("op")
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+gesture_short.describe(v, "+", "off"))
		}
	}
	return parts
}

func (self *decoder) scroll(r *reader) []string {
	parts := []string{"scroll"}
	op, _ := r.frame.Get("op")
	switch op {
	case "event":
		r.skip("op")
		parts = add(parts, named(r, "src", scroll_sources))
		if v, found := r.frame.Get("phase"); found && v == "0" {
			r.skip("phase")
		} else {
			parts = add(parts, named(r, "phase", scroll_phases))
		}
		if dx, dy, ok := r.take_pair("dx", "dy"); ok {
			parts = append(parts, fmt.Sprintf("dx=%+.2fpx", float64(dx)/100), fmt.Sprintf("dy=%+.2fpx", float64(dy)/100))
		}
		// Unlike the other two protocols the position here is in whole pixels
		if x, y, ok := r.take_pair("x", "y"); ok {
			parts = add(parts, fmt.Sprintf("x=%dpx", x), fmt.Sprintf("y=%dpx", y), self.cell(x*256, y*256))
		}
		parts = add(parts, mods(r))
	case "cap":
		r.skip("op")
		parts = append(parts, "capabilities")
		if v, ok := r.take_int("caps"); ok {
			parts = append(parts, "can-report="+scroll_cap_names.describe(v, ", ", "nothing"))
		}
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+on_off.describe(v, "+", "off"))
		}
	case "mode":
		r.skip("op")
		if v, ok := r.take_int("mode"); ok {
			parts = append(parts, "mode="+on_off.describe(v, "+", "off"))
		}
	}
	return parts
}
