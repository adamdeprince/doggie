// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"fmt"
	"strings"
)

var _ = fmt.Print

// What the kitten needs of the terminal it runs in. The logic below talks to
// this rather than to the terminal, so that it can be tested without one
type host interface {
	// Write escape codes to the terminal
	send(text string)
	// Print a line about the program itself
	status(text string)
	// Print a line for something the terminal reported
	report(text string)
	// Call round_done() with this round if the terminal has not answered in time
	wait(round int)
	quit(exit_code int)
}

// Something the terminal can report, turned on by one bit of the mode of a
// protocol
type source struct {
	name, selector string
	mode_bit       int64
	// The capability bits any of which mean the terminal can produce these reports
	cap_bits int64
	// In the protocol as first published. A terminal that rejects a mode with
	// bits it does not know is asked again for these alone
	basic bool
}

var sources = []source{
	{"tools", "tablet-pointer", 1, 1, true},
	{"fingers", "tablet-pointer", 2, 2 | 4, true},
	{"pads", "tablet-pointer", 4, 16, false},
	{"ids", "tablet-pointer", 8, 64, false},
	{"actions", "tablet-pointer", 16, 32, false},
	{"estimates", "tablet-pointer", 32, 128, false},
	{"accidental", "tablet-pointer", 64, 256, false},
	{"gestures", "gesture", 1, 1 | 2 | 4 | 8, true},
	{"hold", "gesture", 2, 16, false},
	{"scroll", "scroll", 1, 1, true},
}

var selector_names = []string{"tablet-pointer", "gesture", "scroll"}

// The sources named by the --only option, all of them when it was not given.
// Hardware identifiers are asked for with --ids alone
func parse_only(values []string, ids bool) (map[string]bool, error) {
	ans := make(map[string]bool)
	all := true
	for _, value := range values {
		for name := range strings.SplitSeq(value, ",") {
			if name = strings.ToLower(strings.TrimSpace(name)); name == "" {
				continue
			}
			all = false
			matched := false
			for _, s := range sources {
				if s.name != "ids" && (s.name == name || s.selector == name) {
					ans[s.name] = true
					matched = true
				}
			}
			if !matched {
				if name == "ids" {
					return nil, fmt.Errorf("Hardware identifiers are asked for with --ids, not with --only")
				}
				var known []string
				for _, s := range sources {
					if s.name != "ids" {
						known = append(known, s.name)
					}
				}
				return nil, fmt.Errorf("Unknown source: %s. The sources are: %s. The names %s stand for all the sources of that protocol.",
					name, strings.Join(known, ", "), strings.Join(selector_names, ", "))
			}
		}
	}
	if all {
		for _, s := range sources {
			ans[s.name] = true
		}
	}
	ans["ids"] = ids && (ans["tools"] || ans["pads"])
	return ans, nil
}

// What is known about one protocol in this terminal
type selector struct {
	name string
	// Whether any of its sources is wanted, otherwise it is left alone
	wanted   bool
	query_id int
	answered bool
	caps     int64
	has_caps bool
	// The mode when this program started
	prior_mode int64
	// The mode to ask for, and the part of it every implementation knows
	want, basic int64
	// The mode last asked for, zero when nothing was turned on
	asked int64
	// What the terminal said is on after being asked
	confirmed bool
	mode      int64
}

type stage int

const (
	discovering stage = iota
	enabling
	retrying
	running
	finished
)

type session struct {
	host      host
	raw       bool
	only      map[string]bool
	dec       *decoder
	selectors []*selector
	// The reply to the capabilities listing
	listing *Frame
	stage   stage
	// Counts the batches of queries sent. Each ends with a query every terminal
	// answers, so the answer to the n-th of those ends the n-th round
	round, sentinels int
	next_id          int
}

func new_session(h host, only map[string]bool, raw bool) *session {
	ans := &session{host: h, raw: raw, only: only, dec: new_decoder(only["ids"])}
	for _, name := range selector_names {
		s := &selector{name: name}
		for _, src := range sources {
			if src.selector == name && only[src.name] {
				s.wanted = true
			}
		}
		ans.selectors = append(ans.selectors, s)
	}
	return ans
}

func (self *session) selector(name string) *selector {
	for _, s := range self.selectors {
		if s.name == name {
			return s
		}
	}
	return nil
}

func frame(selector, fields string) string {
	return "\x1b]" + osc_code + ";" + selector + ";v=1:" + fields + "\x1b\\"
}

// Primary device attributes, which every terminal answers. Replies come in
// order, so its answer means the replies to everything sent before it have
// come or never will
const sentinel_query = "\x1b[c"

func (self *session) begin_round(queries string) {
	self.round++
	self.host.send(queries + sentinel_query)
	self.host.wait(self.round)
}

func (self *session) new_id() int {
	self.next_id++
	return self.next_id
}

func (self *session) start() {
	self.host.status("Quit with Ctrl+C, Ctrl+D or q.")
	self.stage = discovering
	queries := frame("caps", fmt.Sprintf("op=query:id=%d", self.new_id()))
	for _, s := range self.selectors {
		if s.wanted {
			s.query_id = self.new_id()
			queries += frame(s.name, fmt.Sprintf("op=query:id=%d", s.query_id))
		}
	}
	self.begin_round(queries)
}

// The terminal answered the query that ends a round
func (self *session) sentinel() {
	self.sentinels++
	self.round_done(self.sentinels, false)
}

func (self *session) round_done(round int, timed_out bool) {
	if round != self.round {
		return
	}
	switch self.stage {
	case discovering:
		self.discovered(timed_out)
	case enabling, retrying:
		self.enabled()
	}
}

// The body of an OSC escape code from the terminal
func (self *session) on_osc(raw []byte) {
	if f, ok := parse_frame(raw); ok {
		self.on_frame(&f)
	}
}

func (self *session) on_frame(f *Frame) {
	op, _ := f.Get("op")
	if f.Selector == "caps" && op == "cap" && self.stage == discovering {
		self.listing = f
		if self.raw {
			self.host.report(self.dec.raw(f))
		}
		return
	}
	if s := self.selector(f.Selector); s != nil {
		switch op {
		case "cap":
			if id, ok := f.Int("id"); ok && int(id) == s.query_id {
				if self.stage == discovering {
					s.answered = true
					s.caps, s.has_caps = f.Int("caps")
					s.prior_mode, _ = f.Int("mode")
				}
				self.read_geometry(f)
				if self.raw || self.stage == running {
					self.print(f)
				}
				return
			}
		case "mode":
			if self.stage == enabling || self.stage == retrying {
				if mode, ok := f.Int("mode"); ok {
					s.confirmed, s.mode = true, mode
				}
				if self.raw {
					self.host.report(self.dec.raw(f))
				}
				return
			}
		}
	}
	self.print(f)
}

func (self *session) print(f *Frame) {
	if self.raw {
		self.host.report(self.dec.raw(f))
	} else {
		self.host.report(self.dec.describe(f))
	}
}

// The reply to a tablet pointer query has the size of the cell area and of a cell
func (self *session) read_geometry(f *Frame) {
	if f.Selector != "tablet-pointer" {
		return
	}
	g := geometry{}
	var a, b, c, d bool
	g.width, a = f.Int("w")
	g.height, b = f.Int("h")
	g.cell_width, c = f.Int("cw")
	g.cell_height, d = f.Int("ch")
	if a && b && c && d {
		self.dec.geometry = g
	}
}

// The size of a cell as the kernel reports it, used when the terminal has not
// said itself
func (self *session) set_cell_size(width, height int64) {
	if g := &self.dec.geometry; g.width == 0 && width > 0 && height > 0 {
		g.cell_width, g.cell_height = width, height
	}
}

// The window changed size, so positions have to be related to the new cell area
func (self *session) resized(cell_width, cell_height int64) {
	if self.stage != running {
		return
	}
	if s := self.selector("tablet-pointer"); s.answered {
		s.query_id = self.new_id()
		self.host.send(frame(s.name, fmt.Sprintf("op=query:id=%d", s.query_id)))
	} else {
		self.dec.geometry = geometry{cell_width: cell_width, cell_height: cell_height}
	}
}

func (self *session) discovered(timed_out bool) {
	if self.listing != nil {
		ext, _ := self.listing.Get("ext")
		self.host.status("The terminal lists these extensions: " + printable(strings.ReplaceAll(ext, ",", ", ")))
	} else {
		self.host.status("The terminal did not answer the capabilities listing.")
	}
	supported := 0
	for _, s := range self.selectors {
		if !s.wanted {
			continue
		}
		if !s.answered {
			self.host.status(s.name + ": not supported by this terminal.")
			continue
		}
		supported++
		self.host.status(s.name + ": " + self.describe_capabilities(s))
		if s.prior_mode != 0 {
			self.host.status(fmt.Sprintf(
				"%s: reports were already on (mode=%d) when this program started, left on by an earlier program.", s.name, s.prior_mode))
		}
	}
	if supported == 0 {
		if timed_out {
			self.host.status("The terminal did not answer in time.")
		}
		self.host.status("This terminal speaks none of the protocols asked for, so there is nothing to show.")
		self.finish(1)
		return
	}
	self.enable()
}

func (self *session) describe_capabilities(s *selector) string {
	var names bit_names
	switch s.name {
	case "tablet-pointer":
		names = tablet_cap_names
	case "gesture":
		names = gesture_cap_names
	case "scroll":
		names = scroll_cap_names
	}
	ans := "supported."
	if s.has_caps {
		if s.caps == 0 {
			ans = "supported, but the terminal can report nothing for it on this system."
		} else {
			ans = "can report " + names.describe(s.caps, ", ", "") + "."
		}
	}
	if g := self.dec.geometry; s.name == "tablet-pointer" && g.width > 0 {
		ans += fmt.Sprintf(" The cell area is %dx%d pixels and a cell %dx%d pixels.", g.width, g.height, g.cell_width, g.cell_height)
	}
	return ans
}

// Works out the mode to ask each protocol for: every wanted source the
// terminal says it can produce
func (self *session) choose_modes() {
	for _, s := range self.selectors {
		s.want, s.basic = 0, 0
		if !s.answered {
			continue
		}
		for _, src := range sources {
			if src.selector != s.name || !self.only[src.name] {
				continue
			}
			// A terminal that does not say what it can report is asked for
			// what every implementation has
			offered := s.caps&src.cap_bits != 0
			if !s.has_caps {
				offered = src.basic
			}
			if offered {
				s.want |= src.mode_bit
				if src.basic {
					s.basic |= src.mode_bit
				}
			}
		}
	}
}

func (self *session) enable() {
	self.choose_modes()
	queries := ""
	for _, s := range self.selectors {
		if s.want != 0 {
			s.asked = s.want
			// Setting the mode has no reply, reading it back does
			queries += frame(s.name, fmt.Sprintf("op=mode:mode=%d", s.asked)) + frame(s.name, "op=mode")
		}
	}
	if queries == "" {
		self.host.status("The terminal offers none of the reports asked for, so there is nothing to turn on.")
		self.finish(1)
		return
	}
	self.stage = enabling
	self.begin_round(queries)
}

// The terminal has said, or failed to say, what is on now
func (self *session) enabled() {
	if self.stage == enabling {
		// A terminal that rejects a mode because of bits it does not know has
		// turned nothing on. Ask it once more for the bits it must know
		queries := ""
		for _, s := range self.selectors {
			if s.asked != 0 && s.confirmed && s.mode == 0 && s.basic != 0 && s.basic != s.asked {
				s.asked, s.confirmed = s.basic, false
				queries += frame(s.name, fmt.Sprintf("op=mode:mode=%d", s.asked)) + frame(s.name, "op=mode")
			}
		}
		if queries != "" {
			self.stage = retrying
			self.begin_round(queries)
			return
		}
	}
	self.stage = running
	on := func(s *selector) int64 {
		if s.confirmed {
			return s.mode
		}
		return s.asked
	}
	for _, s := range self.selectors {
		if s.asked == 0 {
			continue
		}
		names := on_off
		switch s.name {
		case "tablet-pointer":
			names = tablet_mode_names
		case "gesture":
			names = gesture_modes
		}
		switch {
		case !s.confirmed:
			self.host.status(fmt.Sprintf("%s: asked for %s (mode=%d). The terminal did not say whether it is on.",
				s.name, names.describe(s.asked, ", ", ""), s.asked))
		case s.mode == 0:
			self.host.status(s.name + ": the terminal did not turn the reports on.")
		case s.mode != s.asked:
			self.host.status(fmt.Sprintf("%s: asked for %s (mode=%d), the terminal turned on %s (mode=%d).",
				s.name, names.describe(s.asked, ", ", ""), s.asked, names.describe(s.mode, ", ", ""), s.mode))
		default:
			self.host.status(fmt.Sprintf("%s: reporting %s (mode=%d).", s.name, names.describe(s.mode, ", ", ""), s.mode))
		}
	}
	if on(self.selector("tablet-pointer"))&3 != 0 {
		self.host.status("While this runs, a pen or a finger over this window is reported here instead of acting as a mouse.")
	}
	if on(self.selector("scroll")) != 0 {
		self.host.status("While this runs, the wheel and the trackpad do not scroll the scrollback.")
	}
}

func (self *session) finish(exit_code int) {
	self.stage = finished
	self.host.quit(exit_code)
}

// The escape codes that turn off everything this program turned on
func (self *session) turn_off() string {
	ans := ""
	for _, s := range self.selectors {
		if s.asked != 0 {
			ans += frame(s.name, "op=mode:mode=0")
		}
	}
	return ans
}

// What to send when the program ends. A terminal that offers to turn every
// mode off at once is asked to, after the modes turned on here have been
// turned off one by one, which also clears a mode an earlier program left on
func (self *session) finalize() string {
	ans := self.turn_off()
	if ans != "" && self.listing != nil {
		if caps, ok := self.listing.Int("caps"); ok && caps&2 != 0 {
			ans += frame("caps", "op=reset")
		}
	}
	return ans
}

// The escape codes that turn it back on after the program was suspended
func (self *session) turn_on() string {
	ans := ""
	for _, s := range self.selectors {
		if mode := s.asked; mode != 0 {
			if s.confirmed && s.mode != 0 {
				mode = s.mode
			}
			ans += frame(s.name, fmt.Sprintf("op=mode:mode=%d", mode))
		}
	}
	return ans
}
