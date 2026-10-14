// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"fmt"
	"math/rand"
	"strings"
	"testing"

	"github.com/google/go-cmp/cmp"
)

var _ = fmt.Print

func TestShowPointerParseFrame(t *testing.T) {
	if _, ok := parse_frame([]byte("52;c;aGVsbG8=")); ok {
		t.Fatalf("An OSC that is not 777 was taken for a frame")
	}
	if _, ok := parse_frame([]byte("777")); ok {
		t.Fatalf("An OSC 777 with no selector was taken for a frame")
	}
	for _, c := range []struct {
		raw      string
		expected Frame
	}{
		{"777;scroll;v=1:op=mode:mode=1", Frame{"scroll", []Field{{"v", "1"}, {"op", "mode"}, {"mode", "1"}}}},
		{"777;scroll;", Frame{"scroll", nil}},
		{"777;scroll", Frame{"scroll", nil}},
		// A value may itself contain an equals sign, as base64 does
		{"777;tablet-pointer;name=YQ==", Frame{"tablet-pointer", []Field{{"name", "YQ=="}}}},
		// What is not key=value is kept, to be shown
		{"777;x;a:=b::c=", Frame{"x", []Field{{"", "a"}, {"", "=b"}, {"", ""}, {"c", ""}}}},
		// The notification escape code of other terminals shares the number
		{"777;notify;title;body", Frame{"notify", []Field{{"", "title;body"}}}},
	} {
		actual, ok := parse_frame([]byte(c.raw))
		if !ok {
			t.Fatalf("Failed to parse: %#v", c.raw)
		}
		if diff := cmp.Diff(c.expected, actual); diff != "" {
			t.Fatalf("Parsing %#v failed:\n%s", c.raw, diff)
		}
	}
	f, _ := parse_frame([]byte("777;x;a=1:a=2:b=+3:c=x:d=-7"))
	if v, ok := f.Int("a"); !ok || v != 1 {
		t.Fatalf("The first of two fields with one key was not used")
	}
	if _, ok := f.Int("b"); ok {
		t.Fatalf("An integer with a leading plus sign was accepted")
	}
	if _, ok := f.Int("c"); ok {
		t.Fatalf("A value that is not a number was accepted as one")
	}
	if v, ok := f.Int("d"); !ok || v != -7 {
		t.Fatalf("A negative integer was not parsed")
	}
	if _, ok := f.Int("missing"); ok {
		t.Fatalf("A missing field was found")
	}
}

func TestShowPointerDecode(t *testing.T) {
	d := new_decoder(false)
	d.geometry = geometry{1200, 800, 12, 24}
	for _, c := range []struct{ raw, expected string }{
		// The example of the specification
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=1:device=3:t=408211:contact=0:x=25600:y=51200:buttons=1:mods=0:tool=1:valid=3:p=32000:tx=-1200:ty=600:serial=4242",
			"tablet tool down device=3 contact=0 tool=pen x=100.00px y=200.00px cell=8,8 buttons=tip mods=none valid=pressure+tilt pressure=0.488 tilt=-12.00°,6.00° serial=#1 t=408211ms"},
		// Microseconds, and the time since the previous sample of the stroke
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=2:device=3:t=408215:tu=167:contact=0:x=25856:y=51200:buttons=3:mods=5:tool=2:valid=127:p=65535:tx=0:ty=0:twist=9000:tangent=-65535:z=12:dist=0:wheel=1500:wclicks=1",
			"tablet tool move device=3 contact=0 tool=eraser x=101.00px y=200.00px cell=8,8 buttons=tip+barrel mods=shift+ctrl valid=pressure+tilt+twist+tangent+z+distance+wheel pressure=1.000 tilt=0.00°,0.00° twist=90.00° tangent=-1.000 z=12 distance=0.000 wheel=15.00° clicks=1 t=408215.167ms dt=4.167ms"},
		{"777;tablet-pointer;v=1:op=event:kind=2:phase=2:device=0:t=1016:contact=3:x=256:y=512:buttons=1:mods=0:tool=0:valid=128:major=1280:minor=768:angle=4500",
			"tablet finger move device=0 contact=3 tool=finger x=1.00px y=2.00px cell=0,0 buttons=tip mods=none valid=shape shape=5.00x3.00px@45.00° t=1016ms"},
		{"777;tablet-pointer;v=1:op=event:kind=2:phase=6:device=0:t=1016", "tablet finger frame device=0 t=1016ms"},
		// A finger on a touchpad is placed on the pad, not on the window
		{"777;tablet-pointer;v=1:op=event:kind=2:phase=1:device=0:t=2000:contact=0:x=32768:y=65535:buttons=1:mods=0:tool=0:valid=1:src=1:w=40960:h=25600:p=30000:stage=1",
			"tablet finger down device=0 contact=0 tool=finger touchpad at=50.0%,100.0% pad=160.0x100.0mm buttons=tip mods=none valid=pressure pressure=0.458 stage=1 t=2000ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=100:button=3:state=1", "tablet pad device=5 button=3 pressed t=100ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=104:ring=0:angle=12345:src=1", "tablet pad device=5 ring=0 angle=123.45° by-finger t=104ms dt=4ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=110:ring=0:stop=1", "tablet pad device=5 ring=0 stopped t=110ms dt=6ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=120:strip=1:pos=16384", "tablet pad device=5 strip=1 position=0.250 t=120ms dt=10ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=130:dial=0:delta=-180", "tablet pad device=5 dial=0 turned=-1.50detents t=130ms dt=10ms"},
		{"777;tablet-pointer;v=1:op=event:kind=3:device=5:t=140:group=0:mode=2", "tablet pad device=5 t=140ms dt=10ms group=0 mode=2"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=3:t=408211:action=1:x=25600:y=51200:mods=0",
			"tablet action device=3 double-tap x=100.00px y=200.00px cell=8,8 mods=none t=408211ms"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=0:t=600:action=2:state=1:x=0:y=0:mods=1",
			"tablet action device=0 squeeze began x=0.00px y=0.00px cell=0,0 mods=shift t=600ms"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=0:t=700:action=2:state=0", "tablet action device=0 squeeze ended t=700ms"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=0:t=800:action=9:state=5", "tablet action device=0 t=800ms action=9 state=5"},
		{"777;tablet-pointer;v=1:op=device:device=3:kind=1:tool=1:axes=7:name=V2Fjb20gUGVu:bat=80:serial=99:hwid=2082:vid=1386:pid=855",
			`tablet device device=3 kind=tool tool=pen measures=pressure+tilt+twist name="Wacom Pen" battery=80% serial=#2 hwid=0x822 usb=056a:0357`},
		{"777;tablet-pointer;v=1:op=cap:id=42:caps=5:mode=0:w=1200:h=800:cw=12:ch=24",
			"tablet capabilities can-report=tools, fingers on a touchpad mode=off area=1200x800px cell=12x24px id=42"},
		{"777;tablet-pointer;v=1:op=mode:mode=7", "tablet mode=tools+fingers+pads"},
		{"777;tablet-pointer;v=1:op=cap:id=43:caps=357:mode=66:w=1200:h=800:cw=12:ch=24",
			"tablet capabilities can-report=tools, fingers on a touchpad, tool actions, hardware identifiers, accidental contacts mode=fingers+accidental area=1200x800px cell=12x24px id=43"},
		// What this program does not know is shown as it came
		{"777;tablet-pointer;v=1:op=event:kind=9:foo=bar", "tablet event kind=9 foo=bar"},
		{"777;tablet-pointer;v=1:op=future:x=1", "tablet op=future x=1"},
		// A sample whose pressure and tilt are still estimates, and its correction
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=2:device=1:t=5:contact=0:x=0:y=0:tool=8:valid=3:p=100:tx=0:ty=0:seq=4:est=3:glow=3",
			"tablet tool move device=1 contact=0 tool=totem x=0.00px y=0.00px cell=0,0 valid=pressure+tilt pressure=0.002 tilt=0.00°,0.00° estimated=pressure+tilt t=5ms seq=4 glow=3"},
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=7:device=1:t=5:contact=0:x=0:y=0:tool=8:valid=3:p=200:tx=0:ty=0:seq=4",
			"tablet tool correction device=1 contact=0 tool=totem x=0.00px y=0.00px cell=0,0 valid=pressure+tilt pressure=0.003 tilt=0.00°,0.00° t=5ms dt=0ms seq=4"},
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=2:device=1:t=9:contact=0:x=0:y=0:tool=8:pred=1",
			"tablet tool move device=1 contact=0 tool=totem x=0.00px y=0.00px cell=0,0 predicted t=9ms dt=4ms"},
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=0:device=1:t=9:contact=0:x=-256:y=-1:tool=42:valid=3072:buttons=65",
			"tablet tool hover device=1 contact=0 x=-1.00px y=0.00px cell=-1,-1 buttons=tip+0x40 valid=0xc00 t=9ms dt=0ms tool=42"},
		// What a tablet says of itself: where a tool is on it, the grip on the barrel, whether a finger is meant
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=0:device=1:t=9:contact=0:x=0:y=0:tool=1:valid=769:p=0:rx=32768:ry=65535:grip=65535",
			"tablet tool hover device=1 contact=0 tool=pen x=0.00px y=0.00px cell=0,0 valid=pressure+place+grip pressure=0.000 on-tablet=50.0%,100.0% grip=1.000 t=9ms dt=0ms"},
		{"777;tablet-pointer;v=1:op=event:kind=2:phase=2:device=0:t=1020:contact=3:x=256:y=512:buttons=1:mods=0:tool=0:valid=0:conf=0",
			"tablet finger move device=0 contact=3 tool=finger x=1.00px y=2.00px cell=0,0 buttons=tip mods=none valid=none accidental t=1020ms dt=4ms"},
		{"777;tablet-pointer;v=1:op=event:kind=2:phase=2:device=0:t=1024:contact=3:x=256:y=512:buttons=1:mods=0:tool=0:valid=0:conf=7",
			"tablet finger move device=0 contact=3 tool=finger x=1.00px y=2.00px cell=0,0 buttons=tip mods=none valid=none t=1024ms dt=4ms conf=7"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=3:t=408300:action=6:x=0:y=0:mods=0", "tablet action device=3 docked x=0.00px y=0.00px cell=0,0 mods=none t=408300ms"},
		{"777;tablet-pointer;v=1:op=event:kind=4:device=3:t=408400:action=8:state=2:dx=-120:dy=40:x=0:y=0:mods=0",
			"tablet action device=3 air-motion moving moved=-120,+40 x=0.00px y=0.00px cell=0,0 mods=none t=408400ms"},
		{"777;tablet-pointer;v=1:op=device:device=3:kind=1:tool=1:axes=769:w=57344:h=37888:direct=1:bat=80:pcolor=FF8000:pwidth=128:pstyle=3:tablet=2",
			"tablet device device=3 kind=tool tool=pen measures=pressure+place+grip battery=80% tablet=2 surface=224.0x148.0mm display color=#ff8000 width=0.50mm style=highlighter"},
		{"777;tablet-pointer;v=1:op=device:device=5:kind=3:buttons=6:rings=1:strips=1:dials=0:groups=2:modes=3,2:bgroups=0,0,0,-,1,1:rgroups=0:sgroups=1:tablet=2:direct=0:pcolor=red:pstyle=9",
			"tablet device device=5 kind=pad tablet=2 not-a-display buttons=6 rings=1 strips=1 dials=0 groups=2 modes=3,2 bgroups=0,0,0,-,1,1 rgroups=0 sgroups=1 pcolor=red pstyle=9"},
		{"777;tablet-pointer;v=1:op=event:kind=1:phase=x:garbage:=3:t=abc:name=!!", "tablet tool phase=x garbage =3 t=abc name=!!"},
		{"777;tablet-pointer;v=2:op=event:kind=3:device=5:button=1:state=7", "tablet pad device=5 button=1 v=2 state=7"},
		{"777;gesture;v=1:op=event:kind=1:phase=2:x=25600:y=51200:mods=0:scale=120:total=1340",
			"gesture pinch update x=100.00px y=200.00px cell=8,8 mods=none scale=+12.0% total=x1.340"},
		{"777;gesture;v=1:op=event:kind=2:phase=2:x=0:y=0:mods=4:angle=-150:total=1200",
			"gesture rotate update x=0.00px y=0.00px cell=0,0 mods=ctrl angle=-1.50° total=+12.00°"},
		{"777;gesture;v=1:op=event:kind=3:phase=1:x=0:y=0:mods=0:dx=-1:dy=0:fingers=3",
			"gesture swipe begin x=0.00px y=0.00px cell=0,0 mods=none fingers=3 direction=left"},
		{"777;gesture;v=1:op=event:kind=3:phase=3:x=0:y=0:mods=0:dx=2:dy=0", "gesture swipe end x=0.00px y=0.00px cell=0,0 mods=none dx=2 dy=0"},
		{"777;gesture;v=1:op=event:kind=4:phase=1:x=0:y=0:mods=8", "gesture smart-zoom begin x=0.00px y=0.00px cell=0,0 mods=super"},
		{"777;gesture;v=1:op=event:kind=5:phase=4:x=0:y=0:mods=0:fingers=4", "gesture hold cancel x=0.00px y=0.00px cell=0,0 mods=none fingers=4"},
		{"777;gesture;v=1:op=event:kind=6:phase=1", "gesture event kind=6 phase=1"},
		{"777;gesture;v=1:op=cap:id=3:caps=31:mode=3", "gesture capabilities can-report=pinch, rotate, swipe, smart zoom, hold mode=gestures+hold id=3"},
		// The position of a scroll report is in whole pixels
		{"777;scroll;v=1:op=event:dx=0:dy=250:x=33:y=12:mods=1:src=1:phase=2", "scroll precise moving dx=+0.00px dy=+2.50px x=33px y=12px cell=2,0 mods=shift"},
		{"777;scroll;v=1:op=event:dx=-5000:dy=0:x=0:y=0:mods=0:src=0:phase=0", "scroll wheel dx=-50.00px dy=+0.00px x=0px y=0px cell=0,0 mods=none"},
		{"777;scroll;v=1:op=event:dx=1:dy=2:src=7:phase=9", "scroll dx=+0.01px dy=+0.02px src=7 phase=9"},
		{"777;scroll;v=1:op=cap:id=4:caps=1:mode=1", "scroll capabilities can-report=pixel distances mode=on id=4"},
		// A selector this program does not know
		{"777;display;v=1:op=event:kind=lcd:gamut=p3", "display op=event kind=lcd gamut=p3"},
		{"777;notify;title;body", "notify title;body"},
		{"777;;", ""},
	} {
		f, ok := parse_frame([]byte(c.raw))
		if !ok {
			t.Fatalf("Failed to parse: %#v", c.raw)
		}
		if diff := cmp.Diff(c.expected, d.describe(&f)); diff != "" {
			t.Fatalf("Decoding %#v failed:\n%s", c.raw, diff)
		}
	}
	// Without the size of a cell there is no cell to name
	d.geometry = geometry{}
	f, _ := parse_frame([]byte("777;gesture;v=1:op=event:kind=4:phase=1:x=256:y=256:mods=0"))
	if diff := cmp.Diff("gesture smart-zoom begin x=1.00px y=1.00px mods=none", d.describe(&f)); diff != "" {
		t.Fatalf("Decoding without a geometry failed:\n%s", diff)
	}
}

func TestShowPointerSerialNumbers(t *testing.T) {
	const a = "777;tablet-pointer;v=1:op=device:device=3:serial=4242:hwid=2082"
	const b = "777;tablet-pointer;v=1:op=device:device=4:serial=77:hwid=2082"
	parse := func(raw string) *Frame {
		f, _ := parse_frame([]byte(raw))
		return &f
	}
	// A serial number is replaced by a counter that still tells pens apart
	d := new_decoder(false)
	for _, c := range []struct{ raw, expected string }{
		{a, "777;tablet-pointer;v=1:op=device:device=3:serial=#1:hwid=2082"},
		{b, "777;tablet-pointer;v=1:op=device:device=4:serial=#2:hwid=2082"},
		{a, "777;tablet-pointer;v=1:op=device:device=3:serial=#1:hwid=2082"},
	} {
		if diff := cmp.Diff(c.expected, d.raw(parse(c.raw))); diff != "" {
			t.Fatalf("Hiding the serial number of %#v failed:\n%s", c.raw, diff)
		}
	}
	if diff := cmp.Diff("tablet device device=4 serial=#2 hwid=0x822", d.describe(parse(b))); diff != "" {
		t.Fatalf("The decoded and the raw output disagree about a pen:\n%s", diff)
	}
	d = new_decoder(true)
	if diff := cmp.Diff(a, d.raw(parse(a))); diff != "" {
		t.Fatalf("The serial number was changed though it was asked for:\n%s", diff)
	}
	if diff := cmp.Diff("tablet device device=3 serial=4242 hwid=0x822", d.describe(parse(a))); diff != "" {
		t.Fatalf("The serial number was hidden though it was asked for:\n%s", diff)
	}
}

// Whatever a terminal sends, it must be shown, and must do no harm when shown
func TestShowPointerMalformedFrames(t *testing.T) {
	d := new_decoder(false)
	d.geometry = geometry{1200, 800, 12, 24}
	check := func(raw string) {
		f, ok := parse_frame([]byte(raw))
		if !ok {
			return
		}
		for _, line := range []string{d.describe(&f), d.raw(&f)} {
			if i := strings.IndexFunc(line, func(r rune) bool { return r < ' ' || r == 0x7f || (0x80 <= r && r < 0xa0) }); i >= 0 {
				t.Fatalf("A control character of %#v reached the output: %#v", raw, line)
			}
		}
	}
	for _, raw := range []string{
		"777;tablet-pointer;", "777;tablet-pointer;:::", "777;tablet-pointer;=", "777;tablet-pointer;op=event:kind=1:x=1",
		"777;tablet-pointer;op=event:kind=1:x=99999999999999999999:y=1", "777;tablet-pointer;op=event:kind=1:t=-9223372036854775808:tu=5",
		"777;tablet-pointer;op=event:kind=3:ring=1:angle=-9223372036854775808", "777;tablet-pointer;op=device:name=\x1b[2J:serial=\x07",
		"777;tablet-pointer;op=device:name=G1syShtd", "777;tablet-pointer;op=event:kind=1:valid=-1:buttons=-9223372036854775808",
		"777;\x1b]52;c;\x07;op=event", "777;gesture;op=event:kind=3:dx=x:dy=1", "777;scroll;op=event:x=9223372036854775807:y=9223372036854775807",
		"777;tablet-pointer;op=event:kind=1:\xff\xfe=\xc3\x28",
	} {
		check(raw)
	}
	// The name of a device is text from outside, escape codes in it are defused
	f, _ := parse_frame([]byte("777;tablet-pointer;op=device:name=G1syShtd"))
	if diff := cmp.Diff(`tablet device name="�[2J�]"`, d.describe(&f)); diff != "" {
		t.Fatalf("An escape code in a device name was not defused:\n%s", diff)
	}
	r := rand.New(rand.NewSource(1))
	const alphabet = "0123456789-+=:;abcopkindevtxyz\x00\x1b\xff"
	keys := []string{"op", "kind", "phase", "device", "contact", "t", "tu", "x", "y", "p", "tx", "ty", "ring", "angle", "stop", "dx", "dy", "src", "mode", "caps", "name", "serial", "v"}
	vals := []string{"event", "cap", "mode", "device", "0", "1", "2", "3", "4", "5", "-1", "65535", "x", ""}
	for range 20000 {
		sb := strings.Builder{}
		sb.WriteString("777;")
		sb.WriteString([]string{"tablet-pointer", "gesture", "scroll", "caps", "other"}[r.Intn(5)])
		sb.WriteByte(';')
		for range r.Intn(12) {
			if r.Intn(4) == 0 {
				for range r.Intn(8) {
					sb.WriteByte(alphabet[r.Intn(len(alphabet))])
				}
			} else {
				sb.WriteString(keys[r.Intn(len(keys))] + "=" + vals[r.Intn(len(vals))])
			}
			sb.WriteByte(':')
		}
		check(sb.String())
	}
}
