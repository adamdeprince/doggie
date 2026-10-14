// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"bytes"
	"fmt"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"

	"github.com/kovidgoyal/kitty/tools/wcswidth"
)

var _ = fmt.Print

// Stands in for the terminal: records what the session does and feeds it
// bytes through the same escape code parser the kitten reads its terminal with
type fake_terminal struct {
	t        *testing.T
	session  *session
	parser   wcswidth.EscapeCodeParser
	sent     string
	statuses []string
	reports  []string
	waits    []int
	keys     string
	exit     int
	has_quit bool
}

func (self *fake_terminal) send(text string)   { self.sent += text }
func (self *fake_terminal) status(text string) { self.statuses = append(self.statuses, text) }
func (self *fake_terminal) report(text string) { self.reports = append(self.reports, text) }
func (self *fake_terminal) wait(round int)     { self.waits = append(self.waits, round) }
func (self *fake_terminal) quit(code int)      { self.exit, self.has_quit = code, true }

func new_fake_terminal(t *testing.T, raw bool, ids bool, only ...string) *fake_terminal {
	ans := &fake_terminal{t: t}
	sources, err := parse_only(only, ids)
	if err != nil {
		t.Fatal(err)
	}
	ans.session = new_session(ans, sources, raw)
	ans.parser.HandleOSC = func(raw []byte) error {
		ans.session.on_osc(raw)
		return nil
	}
	ans.parser.HandleCSI = func(raw []byte) error {
		if bytes.HasPrefix(raw, []byte{'?'}) && bytes.HasSuffix(raw, []byte{'c'}) {
			ans.session.sentinel()
		}
		return nil
	}
	ans.parser.HandleRune = func(r rune) error {
		ans.keys += string(r)
		return nil
	}
	return ans
}

func (self *fake_terminal) feed(chunks ...string) {
	for _, chunk := range chunks {
		if err := self.parser.ParseString(chunk); err != nil {
			self.t.Fatalf("The escape code parser failed on %#v with: %s", chunk, err)
		}
	}
}

// What the session wrote since the last call
func (self *fake_terminal) written() string {
	ans := self.sent
	self.sent = ""
	return ans
}

func osc(selector, fields string) string { return "\x1b]777;" + selector + ";" + fields + "\x1b\\" }

const da1 = "\x1b[?62;c"

// What silkie answers on macOS, with a trackpad
const silkie_discovery = "\x1b]777;caps;v=1:op=cap:id=1:caps=1:ext=caps.1,gesture.1,scroll.1,tablet-pointer.1:media=d,f,t,s:format=24,32,100\x1b\\" +
	"\x1b]777;tablet-pointer;v=1:op=cap:id=2:caps=5:mode=0:w=1200:h=800:cw=12:ch=24\x1b\\" +
	"\x1b]777;gesture;v=1:op=cap:id=3:caps=15:mode=0\x1b\\" +
	"\x1b]777;scroll;v=1:op=cap:id=4:caps=1:mode=0\x07" + da1
const silkie_modes = "\x1b]777;tablet-pointer;v=1:op=mode:mode=3\x1b\\\x1b]777;gesture;v=1:op=mode:mode=1\x1b\\\x1b]777;scroll;v=1:op=mode:mode=1\x1b\\" + da1
const pen_down = "\x1b]777;tablet-pointer;v=1:op=event:kind=1:phase=1:device=3:t=408211:contact=0:x=25600:y=51200:buttons=1:mods=0:tool=1:valid=1:p=32000:serial=4242\x1b\\"
const pen_down_line = "tablet tool down device=3 contact=0 tool=pen x=100.00px y=200.00px cell=8,8 buttons=tip mods=none valid=pressure pressure=0.488 serial=#1 t=408211ms"
const pinch = "\x1b]777;gesture;v=1:op=event:kind=1:phase=2:x=25600:y=51200:mods=0:scale=120:total=1340\x1b\\"
const pinch_line = "gesture pinch update x=100.00px y=200.00px cell=8,8 mods=none scale=+12.0% total=x1.340"

var silkie_statuses = []string{
	"Quit with Ctrl+C, Ctrl+D or q.",
	"The terminal lists these extensions: caps.1, gesture.1, scroll.1, tablet-pointer.1",
	"tablet-pointer: can report tools, fingers on a touchpad. The cell area is 1200x800 pixels and a cell 12x24 pixels.",
	"gesture: can report pinch, rotate, swipe, smart zoom.",
	"scroll: can report pixel distances.",
	"tablet-pointer: reporting tools, fingers (mode=3).",
	"gesture: reporting pinch, rotate, swipe and smart zoom (mode=1).",
	"scroll: reporting on (mode=1).",
	"While this runs, a pen or a finger over this window is reported here instead of acting as a mouse.",
	"While this runs, the wheel and the trackpad do not scroll the scrollback.",
}

func TestShowPointerConversation(t *testing.T) {
	ft := new_fake_terminal(t, false, false)
	ft.session.start()
	if diff := cmp.Diff(
		osc("caps", "v=1:op=query:id=1")+osc("tablet-pointer", "v=1:op=query:id=2")+osc("gesture", "v=1:op=query:id=3")+osc("scroll", "v=1:op=query:id=4")+"\x1b[c",
		ft.written()); diff != "" {
		t.Fatalf("The queries are wrong:\n%s", diff)
	}
	// Nothing is turned on, so there is nothing to turn off, should it end here
	if off := ft.session.turn_off(); off != "" {
		t.Fatalf("Modes are turned off that were never turned on: %#v", off)
	}
	ft.feed(silkie_discovery)
	// Every mode set is followed by a read of it, since setting has no reply
	if diff := cmp.Diff(
		osc("tablet-pointer", "v=1:op=mode:mode=3")+osc("tablet-pointer", "v=1:op=mode")+
			osc("gesture", "v=1:op=mode:mode=1")+osc("gesture", "v=1:op=mode")+
			osc("scroll", "v=1:op=mode:mode=1")+osc("scroll", "v=1:op=mode")+"\x1b[c",
		ft.written()); diff != "" {
		t.Fatalf("The modes asked for are wrong:\n%s", diff)
	}
	ft.feed(silkie_modes, pen_down, pinch)
	if diff := cmp.Diff(silkie_statuses, ft.statuses); diff != "" {
		t.Fatalf("The description of the terminal is wrong:\n%s", diff)
	}
	if diff := cmp.Diff([]string{pen_down_line, pinch_line}, ft.reports); diff != "" {
		t.Fatalf("The reports are wrong:\n%s", diff)
	}
	if diff := cmp.Diff([]int{1, 2}, ft.waits); diff != "" {
		t.Fatalf("A timeout was not armed for every round of queries:\n%s", diff)
	}
	if ft.has_quit {
		t.Fatalf("The session ended by itself")
	}
	if diff := cmp.Diff(
		osc("tablet-pointer", "v=1:op=mode:mode=0")+osc("gesture", "v=1:op=mode:mode=0")+osc("scroll", "v=1:op=mode:mode=0"), ft.session.turn_off()); diff != "" {
		t.Fatalf("Not everything that was turned on is turned off:\n%s", diff)
	}
	// This terminal does not offer to turn every mode off at once
	if ft.session.finalize() != ft.session.turn_off() {
		t.Fatalf("A reset was sent to a terminal that does not offer one")
	}
	if diff := cmp.Diff(
		osc("tablet-pointer", "v=1:op=mode:mode=3")+osc("gesture", "v=1:op=mode:mode=1")+osc("scroll", "v=1:op=mode:mode=1"), ft.session.turn_on()); diff != "" {
		t.Fatalf("Not everything is turned back on after a suspend:\n%s", diff)
	}
	// The window changes size: the cell area is asked for again and used
	ft.session.resized(10, 20)
	if diff := cmp.Diff(osc("tablet-pointer", "v=1:op=query:id=5"), ft.written()); diff != "" {
		t.Fatalf("The geometry was not asked for after a resize:\n%s", diff)
	}
	ft.reports = nil
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=5:caps=5:mode=3:w=2400:h=1600:cw=24:ch=48"), pinch)
	if diff := cmp.Diff([]string{
		"tablet capabilities can-report=tools, fingers on a touchpad mode=tools+fingers area=2400x1600px cell=24x48px id=5",
		strings.Replace(pinch_line, "cell=8,8", "cell=4,4", 1),
	}, ft.reports); diff != "" {
		t.Fatalf("The new geometry was not used:\n%s", diff)
	}
}

// A frame can arrive in any number of pieces, and between key presses
func TestShowPointerSplitReads(t *testing.T) {
	stream := silkie_discovery + silkie_modes + pen_down + pinch
	run := func(chunks ...string) *fake_terminal {
		ft := new_fake_terminal(t, false, false)
		ft.session.start()
		ft.feed(chunks...)
		if diff := cmp.Diff(silkie_statuses, ft.statuses); diff != "" {
			t.Fatalf("The description of the terminal is wrong when read as %#v:\n%s", chunks, diff)
		}
		if diff := cmp.Diff([]string{pen_down_line, pinch_line}, ft.reports); diff != "" {
			t.Fatalf("The reports are wrong when read as %#v:\n%s", chunks, diff)
		}
		return ft
	}
	for i := range len(stream) + 1 {
		run(stream[:i], stream[i:])
	}
	bytewise := make([]string, len(stream))
	for i := range len(stream) {
		bytewise[i] = stream[i : i+1]
	}
	run(bytewise...)

	// Keys typed while frames arrive are neither lost nor taken for frames
	ft := run("a", silkie_discovery, "b", silkie_modes[:20], silkie_modes[20:], "\x03", pen_down[:30], pen_down[30:]+"q"+pinch[:5], pinch[5:], "é")
	if ft.keys != "ab\x03qé" {
		t.Fatalf("The keys typed between frames were read as: %#v", ft.keys)
	}
}

func TestShowPointerUnsupportedTerminal(t *testing.T) {
	// A terminal that knows none of the protocols answers only the last query
	ft := new_fake_terminal(t, false, false)
	ft.session.start()
	ft.feed(da1)
	if !ft.has_quit || ft.exit != 1 {
		t.Fatalf("The session did not end with a failure in a terminal without the protocols")
	}
	if diff := cmp.Diff([]string{
		"Quit with Ctrl+C, Ctrl+D or q.",
		"The terminal did not answer the capabilities listing.",
		"tablet-pointer: not supported by this terminal.",
		"gesture: not supported by this terminal.",
		"scroll: not supported by this terminal.",
		"This terminal speaks none of the protocols asked for, so there is nothing to show.",
	}, ft.statuses); diff != "" {
		t.Fatalf("The explanation is wrong:\n%s", diff)
	}
	if ft.session.turn_off() != "" || strings.Contains(ft.written(), "op=mode") {
		t.Fatalf("A mode was touched in a terminal without the protocols")
	}
	// A terminal that answers nothing at all
	ft = new_fake_terminal(t, false, false)
	ft.session.start()
	ft.session.round_done(1, true)
	if !ft.has_quit || ft.exit != 1 || !strings.Contains(strings.Join(ft.statuses, "\n"), "The terminal did not answer in time.") {
		t.Fatalf("The session did not give up on a terminal that answers nothing: %#v", ft.statuses)
	}
	// Nothing more happens once it is over
	ft.feed(da1, silkie_discovery)
	if strings.Contains(ft.written(), "op=mode") {
		t.Fatalf("A mode was turned on after the session ended")
	}
}

func TestShowPointerSlowTerminal(t *testing.T) {
	// The answer that ends the first round comes after the wait for it ran out.
	// It must not be taken for the end of the second round
	ft := new_fake_terminal(t, false, false, "tools")
	ft.session.start()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=1:mode=0:w=1200:h=800:cw=12:ch=24"))
	ft.session.round_done(1, true)
	if ft.session.stage != enabling {
		t.Fatalf("The session did not go on after the wait ran out")
	}
	ft.feed(da1)
	if ft.session.stage != enabling {
		t.Fatalf("A late answer to the first round ended the second")
	}
	ft.feed(osc("tablet-pointer", "v=1:op=mode:mode=1"), da1)
	if ft.session.stage != running {
		t.Fatalf("The second round did not end")
	}
	// A wait that runs out after its round has ended changes nothing
	ft.session.round_done(1, true)
	ft.session.round_done(2, true)
	if ft.session.stage != running || ft.has_quit {
		t.Fatalf("A stale timeout changed the session")
	}
	// A terminal that does not answer the read of the mode is taken at its word
	ft = new_fake_terminal(t, false, false, "scroll")
	ft.session.start()
	ft.feed(osc("scroll", "v=1:op=cap:id=2:caps=1:mode=0"), da1, da1)
	if diff := cmp.Diff("scroll: asked for on (mode=1). The terminal did not say whether it is on.", ft.statuses[len(ft.statuses)-2]); diff != "" {
		t.Fatalf("An unconfirmed mode was described wrongly:\n%s", diff)
	}
	if ft.session.turn_off() != osc("scroll", "v=1:op=mode:mode=0") {
		t.Fatalf("An unconfirmed mode is not turned off")
	}
}

func TestShowPointerModes(t *testing.T) {
	last := func(ft *fake_terminal, n int) string { return ft.statuses[len(ft.statuses)-n] }
	// Only what the terminal offers and the user wants is asked for
	ft := new_fake_terminal(t, false, false)
	ft.session.start()
	ft.written()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=511:mode=0:w=1200:h=800:cw=12:ch=24"), osc("gesture", "v=1:op=cap:id=3:caps=31:mode=0"), da1)
	// Hardware identifiers are offered, but were not asked for
	if diff := cmp.Diff(
		osc("tablet-pointer", "v=1:op=mode:mode=119")+osc("tablet-pointer", "v=1:op=mode")+osc("gesture", "v=1:op=mode:mode=3")+osc("gesture", "v=1:op=mode")+"\x1b[c",
		ft.written()); diff != "" {
		t.Fatalf("The modes asked for are wrong:\n%s", diff)
	}
	ft.feed(osc("tablet-pointer", "v=1:op=mode:mode=119"), osc("gesture", "v=1:op=mode:mode=3"), da1)
	if diff := cmp.Diff("tablet-pointer: reporting tools, fingers, pads, tool actions, estimated and predicted samples, accidental contacts (mode=119).", last(ft, 3)); diff != "" {
		t.Fatalf("The modes turned on are described wrongly:\n%s", diff)
	}
	if diff := cmp.Diff("gesture: reporting pinch, rotate, swipe and smart zoom, hold (mode=3).", last(ft, 2)); diff != "" {
		t.Fatalf("The modes turned on are described wrongly:\n%s", diff)
	}

	// The contacts a system takes for accidents are asked for only of a terminal that has them
	ft = new_fake_terminal(t, false, false)
	ft.session.start()
	ft.written()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=255:mode=0:w=1200:h=800:cw=12:ch=24"), osc("gesture", "v=1:op=cap:id=3:caps=31:mode=0"), da1)
	if diff := cmp.Diff(
		osc("tablet-pointer", "v=1:op=mode:mode=55")+osc("tablet-pointer", "v=1:op=mode")+osc("gesture", "v=1:op=mode:mode=3")+osc("gesture", "v=1:op=mode")+"\x1b[c",
		ft.written()); diff != "" {
		t.Fatalf("The modes asked for are wrong:\n%s", diff)
	}
	ft.feed(osc("tablet-pointer", "v=1:op=mode:mode=55"), osc("gesture", "v=1:op=mode:mode=3"), da1)
	if diff := cmp.Diff("tablet-pointer: reporting tools, fingers, pads, tool actions, estimated and predicted samples (mode=55).", last(ft, 3)); diff != "" {
		t.Fatalf("The modes turned on are described wrongly:\n%s", diff)
	}
	if diff := cmp.Diff("gesture: reporting pinch, rotate, swipe and smart zoom, hold (mode=3).", last(ft, 2)); diff != "" {
		t.Fatalf("The modes turned on are described wrongly:\n%s", diff)
	}

	ft = new_fake_terminal(t, false, true, "tools,pads")
	ft.session.start()
	if diff := cmp.Diff(osc("caps", "v=1:op=query:id=1")+osc("tablet-pointer", "v=1:op=query:id=2")+"\x1b[c", ft.written()); diff != "" {
		t.Fatalf("A protocol none of whose sources is wanted was queried:\n%s", diff)
	}
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=255:mode=0:w=1200:h=800:cw=12:ch=24"), osc("gesture", "v=1:op=cap:id=3:caps=31:mode=0"), da1)
	if diff := cmp.Diff(osc("tablet-pointer", "v=1:op=mode:mode=13")+osc("tablet-pointer", "v=1:op=mode")+"\x1b[c", ft.written()); diff != "" {
		t.Fatalf("The modes asked for are wrong:\n%s", diff)
	}

	// A terminal that knows fewer bits than it was asked for says what it turned on
	ft = new_fake_terminal(t, false, false)
	ft.session.start()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=19:mode=0:w=1200:h=800:cw=12:ch=24"), da1, osc("tablet-pointer", "v=1:op=mode:mode=3"), da1)
	if diff := cmp.Diff("tablet-pointer: asked for tools, fingers, pads (mode=7), the terminal turned on tools, fingers (mode=3).", last(ft, 2)); diff != "" {
		t.Fatalf("A mode the terminal reduced was described wrongly:\n%s", diff)
	}
	if diff := cmp.Diff(osc("tablet-pointer", "v=1:op=mode:mode=3"), ft.session.turn_on()); diff != "" {
		t.Fatalf("After a suspend the mode the terminal accepted is not the one asked for again:\n%s", diff)
	}

	// A terminal that rejects a mode with bits it does not know is asked again
	// for the bits every implementation has
	ft = new_fake_terminal(t, false, false)
	ft.session.start()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=19:mode=0:w=1200:h=800:cw=12:ch=24"), da1)
	ft.written()
	ft.feed(osc("tablet-pointer", "v=1:op=mode:mode=0"), da1)
	if diff := cmp.Diff(osc("tablet-pointer", "v=1:op=mode:mode=3")+osc("tablet-pointer", "v=1:op=mode")+"\x1b[c", ft.written()); diff != "" {
		t.Fatalf("A rejected mode was not asked for again without the newer bits:\n%s", diff)
	}
	ft.feed(osc("tablet-pointer", "v=1:op=mode:mode=3"), da1)
	if diff := cmp.Diff("tablet-pointer: reporting tools, fingers (mode=3).", last(ft, 2)); diff != "" {
		t.Fatalf("The mode turned on at the second attempt was described wrongly:\n%s", diff)
	}
	// And if it rejects that too, it is asked no more
	ft = new_fake_terminal(t, false, false, "tools")
	ft.session.start()
	ft.feed(osc("tablet-pointer", "v=1:op=cap:id=2:caps=1:mode=0:w=1200:h=800:cw=12:ch=24"), da1, osc("tablet-pointer", "v=1:op=mode:mode=0"), da1)
	if diff := cmp.Diff("tablet-pointer: the terminal did not turn the reports on.", last(ft, 1)); diff != "" {
		t.Fatalf("A mode the terminal refused was described wrongly:\n%s", diff)
	}

	// A mode some earlier program left on is pointed out
	ft = new_fake_terminal(t, false, false, "scroll")
	ft.session.start()
	ft.feed(osc("scroll", "v=1:op=cap:id=2:caps=1:mode=1"), da1)
	if diff := cmp.Diff("scroll: reports were already on (mode=1) when this program started, left on by an earlier program.", last(ft, 1)); diff != "" {
		t.Fatalf("A mode that was already on was not pointed out:\n%s", diff)
	}

	// A terminal that speaks a protocol but can report nothing for it
	ft = new_fake_terminal(t, false, false, "gesture")
	ft.session.start()
	ft.feed(osc("gesture", "v=1:op=cap:id=2:caps=0:mode=0"), da1)
	if !ft.has_quit || ft.exit != 1 || ft.session.turn_off() != "" {
		t.Fatalf("The session went on with nothing to turn on")
	}
	if diff := cmp.Diff([]string{
		"gesture: supported, but the terminal can report nothing for it on this system.",
		"The terminal offers none of the reports asked for, so there is nothing to turn on.",
	}, ft.statuses[len(ft.statuses)-2:]); diff != "" {
		t.Fatalf("The explanation is wrong:\n%s", diff)
	}

	for _, bad := range []string{"tool", "ids", "tools,,nonsense"} {
		if _, err := parse_only([]string{bad}, false); err == nil {
			t.Fatalf("The value %#v of --only was accepted", bad)
		}
	}
	if sources, err := parse_only([]string{" Gesture ", "scroll,tools"}, true); err != nil || !sources["gestures"] || !sources["hold"] || !sources["scroll"] || !sources["tools"] ||
		sources["fingers"] || sources["pads"] || !sources["ids"] {
		t.Fatalf("The sources of --only were read wrongly: %v %v", sources, err)
	}
}

func TestShowPointerReset(t *testing.T) {
	// A terminal that offers to turn every mode off at once is asked to at the
	// end, but only when something was turned on and never for a suspend
	ft := new_fake_terminal(t, false, false, "scroll")
	ft.session.start()
	ft.feed(osc("caps", "v=1:op=cap:id=1:caps=3:ext=caps.1,scroll.1"))
	if ft.session.finalize() != "" {
		t.Fatalf("A reset was sent though nothing was turned on")
	}
	ft.feed(osc("scroll", "v=1:op=cap:id=2:caps=1:mode=0"), da1, osc("scroll", "v=1:op=mode:mode=1"), da1)
	if diff := cmp.Diff(osc("scroll", "v=1:op=mode:mode=0")+osc("caps", "v=1:op=reset"), ft.session.finalize()); diff != "" {
		t.Fatalf("The modes are not reset at the end:\n%s", diff)
	}
	if diff := cmp.Diff(osc("scroll", "v=1:op=mode:mode=0"), ft.session.turn_off()); diff != "" {
		t.Fatalf("Suspending turns off more than this program turned on:\n%s", diff)
	}
}

func TestShowPointerRaw(t *testing.T) {
	ft := new_fake_terminal(t, true, false)
	ft.session.start()
	ft.feed(silkie_discovery, silkie_modes, pen_down, osc("display", "v=1:op=event:kind=lcd"), "\x1b]52;c;aGVsbG8=\x1b\\")
	// Every frame is shown as it came, the replies to the queries too, except
	// that a serial number is not. An escape code that is not a frame is not shown
	if diff := cmp.Diff([]string{
		"777;caps;v=1:op=cap:id=1:caps=1:ext=caps.1,gesture.1,scroll.1,tablet-pointer.1:media=d,f,t,s:format=24,32,100",
		"777;tablet-pointer;v=1:op=cap:id=2:caps=5:mode=0:w=1200:h=800:cw=12:ch=24",
		"777;gesture;v=1:op=cap:id=3:caps=15:mode=0",
		"777;scroll;v=1:op=cap:id=4:caps=1:mode=0",
		"777;tablet-pointer;v=1:op=mode:mode=3",
		"777;gesture;v=1:op=mode:mode=1",
		"777;scroll;v=1:op=mode:mode=1",
		"777;tablet-pointer;v=1:op=event:kind=1:phase=1:device=3:t=408211:contact=0:x=25600:y=51200:buttons=1:mods=0:tool=1:valid=1:p=32000:serial=#1",
		"777;display;v=1:op=event:kind=lcd",
	}, ft.reports); diff != "" {
		t.Fatalf("The raw output is wrong:\n%s", diff)
	}
	ft = new_fake_terminal(t, true, true, "tools")
	ft.session.start()
	ft.feed(pen_down)
	if diff := cmp.Diff([]string{pen_down[2 : len(pen_down)-2]}, ft.reports); diff != "" {
		t.Fatalf("The serial number was hidden though it was asked for:\n%s", diff)
	}
}
