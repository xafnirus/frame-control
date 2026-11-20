# Windows input helper command-size verification

Checked on Linux on 20 November 2026 against main
`80bf522f150ddbb515d2e6408b7af35ac3bf3d2a`. The repair is commit
[`d750976e`](https://github.com/saphid/frame-control/commit/d750976e6de94b26e9eea4915cfb15dac4ba46a2),
which is included in published v0.4.62. Both helpers' `command` methods are
unchanged between that release and the checked main.

## Command-size comparison

The exact pre-repair `command` methods from `d750976e^` were evaluated with
the unchanged helper source bytes. Each resulting SSH argument list was
serialized with Python's `subprocess.list2cmdline` and measured in UTF-16
code units. The fixed argument prefix was:

```python
[r'C:\Program Files\Frame Control\resources\ssh.exe',
 '-o', 'BatchMode=yes', 'frame.example.test', command]
```

| Helper | Before repair | After repair |
|---|---:|---:|
| `frame_input_agent.py` | 25,501 | 9,419 |
| `frame_touch.py` | 36,167 | 12,173 |

The older touch command exceeds Windows' 32,767-character process
command-line limit even before allowing for its terminating null. Both fixed
commands fit below the regression test's 16,384-code-unit ceiling, leaving
room for longer installation paths and additional SSH arguments. Actual
command sizes depend on those arguments.

## Regression checks and limits

```sh
python3 -m unittest discover -s tests -p test_input_command_size.py -v
```

Both tests passed. One measures the production commands with a Windows-style
SSH executable path. The other executes the production compressed bootstrap
with only its final helper compilation replaced by an inert recorder. It
checks the helper source hash, arguments including spaces and quotes, and
that the first Unicode/click input event remains available on standard input.

This check runs on Linux. It does not reproduce Windows' `CreateProcess`
error, start the Windows SSH client, connect to the Frame, or dispatch input
to a device. The bounded Frame SSH probe timed out; no physical Windows/Frame
or worn-headset acceptance check ran. Keep
[issue #559](https://github.com/saphid/frame-control/issues/559) open for live
acceptance or further failure evidence; the command-size repair does not
establish every reported symptom's cause or resolution.
