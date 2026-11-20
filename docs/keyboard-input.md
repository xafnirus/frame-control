# Type from your computer into the Frame

Open **Keyboard and trackpad**, turn it on, then focus the app or panel you want
to control in the headset. Click the trackpad area to capture your computer's
keyboard and mouse. Press **Esc** to stop capture.

| Keys | Forwarding |
|---|---|
| Ctrl, Alt, Shift, Super/Windows/Meta | Left and right keys send separate press and release events during capture. Mac Command sends Linux Super. |
| Tab, arrows, F1–F12 | Send physical key events during capture. |
| Esc | Physical Esc exits capture. Use the **Esc** button to send Escape to the headset. In the text field, Escape also sends a tap. |
| Ctrl+C, Ctrl+V, Ctrl+Z | Forward to the focused headset app; also available in **Send shortcut**. Ctrl+V uses the headset's clipboard. |
| Alt+Tab, Ctrl+Alt+T | Forward when the browser receives them; **Send shortcut** sends a complete chord without relying on host interception. |
| Super and F1–F12 fallback | Choose the key in **Send shortcut**, then click **Send shortcut**. |

Capture sends the modifier down before the chord key, and releases the chord
key before the modifier. Leaving capture, switching windows, hiding the page
or losing focus queues releases for all held keys and mouse buttons. Releases
are retained across a connection error for retry. A disconnected or closed
browser cannot guarantee immediate delivery; reconnect and use **Try again**
if the tool reports an error.

The text field keeps ordinary typing, pasted Unicode and input-method text on
the existing text route. It also forwards received Ctrl/Alt/Meta chords as
complete taps, including Shift when held. Use capture for standalone modifier
holds. AltGr and composing text remain text input in the field. Capture uses
physical key positions and the headset's layout; use the text field for accents,
emoji and other layout-dependent text.

Your computer or browser can keep Alt+Tab, Command/Super combinations, function
keys and other system shortcuts. Frame Control cannot forward an event it never
receives. The shortcut menu and Esc/Tab/arrow buttons provide explicit remote
input without changing your computer's system shortcuts. The menu and entry
into capture wait for queued input to finish so a modifier cannot be held over
pending Unicode text.

Sending the right events does not mean every headset app implements the action:
Ctrl+Alt+T needs a desktop terminal shortcut, for example. Browser/OS interception,
focus and app bindings still apply. The separate Capture viewer retains its
existing Command-to-Ctrl mapping; this page describes **Keyboard and trackpad**.

## Windows: video works but input fails

If **Keyboard and trackpad** reports `[WinError 206] The filename or extension
is too long`, update to **v0.4.62 or later**, quit Frame Control, and reopen
the updated app. That release shortened the SSH commands used to start the
keyboard and touch helpers. The older touch-helper command exceeded Windows'
process command-line limit. This is the command-size repair relevant to
[issue #559](https://github.com/saphid/frame-control/issues/559); successful
video streaming alone does not establish that the separate input helper started.

After updating, turn **Keyboard and trackpad** on and check its status before
capturing input. If it still reports an error, include the exact error and the
installed Frame Control version in a bug report. If it becomes ready, focus
the headset app you want to control and try the explicit key or click buttons
before using capture. Focus, the headset's input path, and app bindings still
need to work independently of helper startup.

The command-size and helper-payload tests pass offline; a physical Windows
PC controlling the real Frame has not been verified for this repair. See the
[Windows command verification](evidence/windows-input-command-size-2026-11-20.md)
for the measurements and test limits.

Automated coverage executes the production browser handlers, server validation,
translation and gamescope input dispatch through the libei key-call boundary.
HTTP/SSH transport and the final device are test doubles. These tests establish event sequences and
focus-loss cleanup, not real-headset or wearer-visible usability. See the
[keyboard verification record](evidence/keyboard-chords-2026-10-31.md).
