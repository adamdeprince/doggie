// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"bytes"
	"fmt"
	"strconv"
	"strings"
)

var _ = fmt.Print

// The OSC number shared by the family of extensions this kitten speaks
const osc_code = "777"

// A field of a frame. A field that is not key=value has an empty Key and its
// whole text as Value, so that it is shown rather than dropped
type Field struct {
	Key, Value string
}

func (self Field) String() string {
	if self.Key == "" {
		return self.Value
	}
	return self.Key + "=" + self.Value
}

// A frame of the OSC 777 family: a selector naming the extension followed by
// fields, kept in the order they were received
type Frame struct {
	Selector string
	Fields   []Field
}

// Parses the body of an OSC escape code, without the leading ESC ] and the
// terminator. Returns false when the body is not an OSC 777 frame. Nothing in
// the body can make this fail, since a terminal under test may send anything
func parse_frame(raw []byte) (ans Frame, ok bool) {
	code, rest, found := bytes.Cut(raw, []byte{';'})
	if !found || string(code) != osc_code {
		return
	}
	selector, fields, _ := bytes.Cut(rest, []byte{';'})
	ans.Selector = string(selector)
	if len(fields) > 0 {
		for field := range strings.SplitSeq(string(fields), ":") {
			if key, val, found := strings.Cut(field, "="); found && key != "" {
				ans.Fields = append(ans.Fields, Field{key, val})
			} else {
				ans.Fields = append(ans.Fields, Field{"", field})
			}
		}
	}
	return ans, true
}

// The value of the first field with the specified key
func (self *Frame) Get(key string) (string, bool) {
	for _, f := range self.Fields {
		if f.Key == key {
			return f.Value, true
		}
	}
	return "", false
}

func (self *Frame) Int(key string) (int64, bool) {
	if val, found := self.Get(key); found {
		return parse_int(val)
	}
	return 0, false
}

// The integers of the protocols are decimal, with no leading plus sign
func parse_int(val string) (int64, bool) {
	if val == "" || val[0] == '+' {
		return 0, false
	}
	ans, err := strconv.ParseInt(val, 10, 64)
	return ans, err == nil
}

// The frame as the terminal sent it, without the escape code framing. The
// replace function, when not nil, substitutes the value of a field
func (self *Frame) Raw(replace func(Field) (string, bool)) string {
	sb := strings.Builder{}
	sb.WriteString(osc_code)
	sb.WriteByte(';')
	sb.WriteString(self.Selector)
	for i, f := range self.Fields {
		if i == 0 {
			sb.WriteByte(';')
		} else {
			sb.WriteByte(':')
		}
		if replace != nil {
			if val, changed := replace(f); changed {
				f.Value = val
			}
		}
		sb.WriteString(f.String())
	}
	return printable(sb.String())
}

// Makes text from the terminal safe to print back to it
func printable(text string) string {
	return strings.Map(func(r rune) rune {
		if r < ' ' || r == 0x7f || (0x80 <= r && r < 0xa0) {
			return 0xfffd
		}
		return r
	}, strings.ToValidUTF8(text, "�"))
}

// Reads the fields of a frame by name, remembering which were read, so that
// whatever is left over can be shown as it came
type reader struct {
	frame *Frame
	used  []bool
}

func new_reader(frame *Frame) *reader {
	return &reader{frame: frame, used: make([]bool, len(frame.Fields))}
}

func (self *reader) index(key string) int {
	for i, f := range self.frame.Fields {
		if !self.used[i] && f.Key == key {
			return i
		}
	}
	return -1
}

func (self *reader) has(key string) bool { return self.index(key) >= 0 }

func (self *reader) take(key string) (string, bool) {
	if i := self.index(key); i >= 0 {
		self.used[i] = true
		return self.frame.Fields[i].Value, true
	}
	return "", false
}

// An integer field. A value that is not an integer is left unread, to be shown
// as it came
func (self *reader) take_int(key string) (int64, bool) {
	if i := self.index(key); i >= 0 {
		if ans, ok := parse_int(self.frame.Fields[i].Value); ok {
			self.used[i] = true
			return ans, true
		}
	}
	return 0, false
}

// Reads two fields that only make sense together, or neither of them
func (self *reader) take_pair(a, b string) (x, y int64, ok bool) {
	i, j := self.index(a), self.index(b)
	if i < 0 || j < 0 {
		return
	}
	var ok_x, ok_y bool
	x, ok_x = parse_int(self.frame.Fields[i].Value)
	y, ok_y = parse_int(self.frame.Fields[j].Value)
	if ok = ok_x && ok_y; ok {
		self.used[i], self.used[j] = true, true
	}
	return
}

func (self *reader) skip(keys ...string) {
	for _, key := range keys {
		self.take(key)
	}
}

// The fields not read so far, as they came
func (self *reader) rest() (ans []string) {
	for i, f := range self.frame.Fields {
		if !self.used[i] {
			ans = append(ans, printable(f.String()))
		}
	}
	return
}
