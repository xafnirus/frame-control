# Historical ARM64 Terminal buffer-wait failure

The original hosted Terminal browser run failed its 90-second frontend
subscription/buffer wait. Its buffer request later returned HTTP 200 with
`true`, after the failed wait had ended. That late reply does not qualify the
run or establish a cause or repair.

This is an offline audit of an existing artifact, with no new runtime execution.
It supplements [#746](https://github.com/saphid/frame-control/issues/746);
the older startup failures in that issue remain separate and unresolved.

## Provenance

- Source: `1d8154b31097f4a1d1a8aa8fa956583a0cb19f5d`, the original head of
  [#793](https://github.com/saphid/frame-control/pull/793).
- [Original failed job](https://github.com/saphid/frame-control/actions/runs/44763171823/job/136380748641),
  attempt 1, `terminal-browser (ubuntu-24.04-arm)`.
- [Diagnostic artifact](https://github.com/saphid/frame-control/actions/runs/44763171823/artifacts/14645980830):
  `terminal-browser-ubuntu-24.04-arm`, 402,330 bytes.
- Artifact ZIP SHA-256:
  `72f91a69496c9581a044fd093fcb7e45943b94b9a5623965a0b537a3f3aead52`.
  The download matched GitHub's artifact digest. All 177 recorded source-file
  bindings matched the source commit.
- [Bounded derived summary](framey-terminal-buffer-wait-2026-11-20.json)
  retains original file digests, wait boundaries, method timings and cleanup.
  It omits raw console output, screenshots and process inventories. The original
  artifact remains the source for those details, subject to GitHub retention.

The guest used native `aarch64` binaries under QEMU TCG, CPU model `max`, with
6,144 MiB of memory. It had no network device or host bus. The test used the
published pinned loader and Terminal archive, an actual guest Decky user
service and production HTTP handlers. CEF, the managed receipt and DOM input
were fixtures. This provides no physical Frame or wearer proof.

## Recorded sequence

Times below are seconds from the replay's shared monotonic origin. Completion
times are sums of the recorded start and elapsed values, rounded to milliseconds.

| Observation | Start | End | Result |
| --- | ---: | ---: | --- |
| Terminal DOM stage wait | 148.896 | 188.507 | Passed |
| Subscription/buffer wait | 188.507 | 278.599 | Failed, 90-second budget |
| `get_config` HTTP request | 196.879 | 208.231 | HTTP 200 |
| `get_terminal` HTTP request | 208.669 | 226.719 | HTTP 200 |
| `unsubscribe_terminal` HTTP request | 209.176 | 228.692 | HTTP 200 |
| `subscribe_terminal` HTTP request | 244.849 | 262.004 | HTTP 200 |
| `send_terminal_buffer` HTTP request | 265.126 | 287.455 | HTTP 200, `true` |

The buffer request began 76.619 seconds after the wait began. Its reply took
22.329 seconds and completed about 8.856 seconds after the recorded failed-wait
boundary. Cleanup drained the pending handlers before the trace was read, so
the final successful request list cannot be substituted for the earlier failed
wait. The captured parent reported no JavaScript errors or explicit panel
failure; the Terminal input/output/removal sequence did not complete.

These records locate the missed wait boundary. They do not explain the earlier
frontend work, each request's latency, guest scheduling or host conditions.
They do not establish that the behavior is harmless or repaired. No timeout,
retry policy, production source or compatibility rating changes in this audit.

## Cleanup and qualification limits

The artifact records the owned browser target and browser process closed,
HTTP server stopped, zero pending handlers after drain, SSH observer removed,
Decky service and user manager stopped, fixture unit restored, bundle removed
and QEMU reaped. No real Frame was contacted.

The original run remains failed. A later retry, if performed, must be assessed
separately against its exact sources. This audit adds no live settings
persistence, VR visibility, physical controller, scrolling or VR keyboard proof.
