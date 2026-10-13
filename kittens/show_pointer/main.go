// License: GPLv3 Copyright: 2026, Adam DePrince

package show_pointer

import (
	"bytes"
	"fmt"
	"os"
	"strings"
	"time"

	"golang.org/x/sys/unix"

	"github.com/kovidgoyal/kitty/tools/cli"
	"github.com/kovidgoyal/kitty/tools/cli/markup"
	"github.com/kovidgoyal/kitty/tools/tty"
	"github.com/kovidgoyal/kitty/tools/tui/loop"
)

var _ = fmt.Print

// Runs a session in the terminal this program was started in
type terminal_host struct {
	lp      *loop.Loop
	ctx     *markup.Context
	session *session
	raw     bool
	timeout time.Duration
	// STDOUT when it is not the terminal, the output then goes there
	file *os.File
}

func (self *terminal_host) send(text string) { self.lp.QueueWriteString(text) }

func (self *terminal_host) status(text string) {
	if self.file != nil {
		fmt.Fprintln(self.file, "# "+text)
	}
	if self.raw {
		text = "# " + text
	}
	self.lp.Println(self.ctx.Dim(text))
}

func (self *terminal_host) report(text string) {
	if self.file != nil {
		fmt.Fprintln(self.file, text)
		return
	}
	if !self.raw {
		// What reported, and what it reported, stand out from the measurements
		if what, rest, found := strings.Cut(text, " "); found {
			kind, measurements, _ := strings.Cut(rest, " ")
			text = self.ctx.Green(what) + " " + self.ctx.Yellow(kind) + " " + measurements
		}
	}
	self.lp.Println(text)
}

func (self *terminal_host) wait(round int) {
	_, _ = self.lp.AddTimer(self.timeout, false, func(loop.IdType) error {
		self.session.round_done(round, true)
		return nil
	})
}

func (self *terminal_host) quit(exit_code int) { self.lp.Quit(exit_code) }

// Stops the program as Ctrl+Z does, with the reports off while it is stopped,
// as the protocols ask of a program that is suspended
func (self *terminal_host) suspend() error {
	self.lp.QueueWriteString(self.session.turn_off())
	err := self.lp.SuspendAndRun(func() error {
		_ = unix.Kill(os.Getpid(), unix.SIGSTOP)
		time.Sleep(20 * time.Millisecond)
		return nil
	})
	if err == nil {
		self.lp.QueueWriteString(self.session.turn_on())
	}
	return err
}

func main(_ *cli.Command, opts *Options, args []string) (rc int, err error) {
	if len(args) > 0 {
		return 1, fmt.Errorf("This kitten takes no arguments, see --help for its options")
	}
	only, err := parse_only(opts.Only, opts.Ids)
	if err != nil {
		return 1, err
	}
	lp, err := loop.New(loop.NoAlternateScreen, loop.NoMouseTracking, loop.NoFocusTracking, loop.NoRestoreColors, loop.OnlyDisambiguateKeys)
	if err != nil {
		return 1, err
	}
	h := &terminal_host{lp: lp, ctx: markup.New(true), raw: opts.Raw, timeout: time.Duration(max(0.1, opts.Timeout) * float64(time.Second))}
	if !tty.IsTerminal(os.Stdout.Fd()) {
		h.file = os.Stdout
	}
	h.session = new_session(h, only, opts.Raw)

	lp.OnInitialize = func() (string, error) {
		lp.SetWindowTitle("Pointer reports")
		if sz, err := lp.ScreenSize(); err == nil {
			h.session.set_cell_size(int64(sz.CellWidth), int64(sz.CellHeight))
		}
		h.session.start()
		return "", nil
	}
	// Runs however the loop ends, be it a key, a signal or a panic
	lp.OnFinalize = func() string { return h.session.finalize() }

	lp.OnEscapeCode = func(etype loop.EscapeCodeType, raw []byte) error {
		switch etype {
		case loop.OSC:
			h.session.on_osc(raw)
		case loop.CSI:
			if bytes.HasPrefix(raw, []byte{'?'}) && bytes.HasSuffix(raw, []byte{'c'}) {
				h.session.sentinel()
			}
		}
		return nil
	}
	lp.OnKeyEvent = func(e *loop.KeyEvent) error {
		switch {
		case e.MatchesPressOrRepeat("ctrl+c"), e.MatchesPressOrRepeat("ctrl+d"), e.MatchesPressOrRepeat("q"):
			e.Handled = true
			lp.Quit(0)
		case e.MatchesPressOrRepeat("ctrl+z"):
			e.Handled = true
			return h.suspend()
		}
		return nil
	}
	// Terminals without the kitty keyboard protocol send keys as plain bytes
	lp.OnText = func(text string, from_key_event bool, in_bracketed_paste bool) error {
		if from_key_event || in_bracketed_paste {
			return nil
		}
		switch text {
		case "\x03", "\x04", "q", "Q":
			lp.Quit(0)
		case "\x1a":
			return h.suspend()
		}
		return nil
	}
	lp.OnResize = func(_, size loop.ScreenSize) error {
		h.session.resized(int64(size.CellWidth), int64(size.CellHeight))
		return nil
	}
	lp.OnResumeFromStop = func() error {
		lp.QueueWriteString(h.session.turn_on())
		return nil
	}

	err = lp.Run()
	if err != nil {
		return 1, err
	}
	if ds := lp.DeathSignalName(); ds != "" {
		fmt.Println("Killed by signal: ", ds)
		lp.KillIfSignalled()
		return 1, nil
	}
	return lp.ExitCode(), nil
}

func EntryPoint(parent *cli.Command) {
	create_cmd(parent, main)
}
