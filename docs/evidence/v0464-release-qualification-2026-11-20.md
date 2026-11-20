# Frame Control v0.4.64 qualification hold

As of **20 November 2026**, v0.4.64 is tagged and built, with a draft release.
It is **not published**. The latest public release remains
[v0.4.62](https://github.com/saphid/frame-control/releases/tag/v0.4.62).

The immutable candidate commit is
`fe929cafed5f2940cd61ca8b7ae38bfa65806d76`, tree
`295d452b6575281ccaadeab8ba6bcb94a4302b66`, with package version `0.4.64`.
The qualification ran from its clean checkout. The rejected v0.4.63 tag and
draft remain untouched. PR #769 merged after the v0.4.64 tag and is excluded.

## Exact-source hosted gates

The repository's `exact_runs` and `successful_jobs` functions independently
checked every matching run and attempt at the candidate commit. All required
jobs passed on their original attempt:

| Gate | Run | Required jobs |
|---|---|---|
| Main checks and fake-Frame e2e | [44653122358](https://github.com/saphid/frame-control/actions/runs/44653122358) | 7 |
| Native AMD64/ARM64 Decky runtime | [44653122360](https://github.com/saphid/frame-control/actions/runs/44653122360) | 2 |
| Ownership/watchdog | [44653281531](https://github.com/saphid/frame-control/actions/runs/44653281531) | 2 |
| Signed packages: both architectures, browser HTTP and production parent | [44653122508](https://github.com/saphid/frame-control/actions/runs/44653122508) | 5 |
| Native sample persistence | [44653122371](https://github.com/saphid/frame-control/actions/runs/44653122371) | 2 |
| Browser sample persistence | [44653122331](https://github.com/saphid/frame-control/actions/runs/44653122331) | 1 |
| Tagged installers and checksums | [44662886623](https://github.com/saphid/frame-control/actions/runs/44662886623) | 6 |

The ownership workflow was explicitly dispatched on main at the candidate
commit because its path filter omitted it. The other software runs were main
pushes; the installer run was the tag push. A later main commit or PR result
was not substituted for the candidate.

The tagged installer run completed Windows, both macOS architectures and
Linux builds, then generated checksums. Its Windows check installs the package
and compares resources; the macOS jobs inspect their delivered DMG/ZIP payloads.
These hosted checks do not establish acceptance on physical desktop machines.

Independent inspection also checked the source-bound native, ownership,
sample-persistence, Terminal browser and five signed-package artifacts,
including strict clocks and owned cleanup. This qualifies those isolated
fixtures, not managed installation or a live headset. Historical failed ARM64
runs remain failed; these later passes do not identify their cause or establish
a repair. Managed Syncthing and official Terminal installation remain disabled.

## Independent installer audit

After the tagged workflow completed, `scripts/audit-release-assets.py`
downloaded all ten installers by asset ID. Every downloaded size and SHA-256
matched GitHub metadata. Downloaded `SHA256SUMS` matched the ten digests byte
for byte. Package format and available version/architecture checks passed.
The [saved audit](v0464-release-assets-2026-11-20.json) records the hashes and
inspection results for draft release ID `452204366`.

The x86_64 AppImage launched with an isolated Xvfb display and temporary profile.
Its bundled server returned HTTP 200 with `FrameControl/1` and stopped when the
app exited. This does not test a physical display, FUSE mount or headset.
The repository's asset-report verifier accepted the report against the draft's
current assets. A short release summary was saved and read back exactly.

For a fresh audit, use an output file that does not already exist:

```sh
python3 scripts/audit-release-assets.py v0.4.64 \
  --report /tmp/frame-v0464-fresh-audit.json --launch-x86-appimage
```

## Hardware gate and publication decision

A bounded, read-only `ssh frame true` probe timed out. No shared-device lock
was acquired, remote input sent, smoke run or wearer check performed. There
was no confirmed wearer. Worn Framey visibility, physical controllers,
scrolling, the VR keyboard and live-headset settings persistence remain
unverified.

**Decision: retain the draft and hold publication.**
[The release procedure](../releasing.md#steps) requires a saved, successful
locked smoke from the exact clean candidate, including verified cleanup and
lock release. Its rule is to hold for any unverified gate. The
[v0.4.62 hardware exception](v0462-release-2026-11-14.md#hardware-and-runtime-limits)
was explicitly specific to that release; it does not authorize a v0.4.64 waiver.

With the installer audit supplied and no `FRAME_SMOKE_RESULT`, the normal
publisher dry run exited with:

```text
release gate failed: FRAME_SMOKE_RESULT is required for the locked real Frame smoke gate
```

That refusal happened before release mutation. The dry run did not pass; no
smoke result was fabricated, updater manifest uploaded or publication attempted.

When the Frame is reachable, follow the shared-device lock and battery
procedure, run the smoke from the clean v0.4.64 commit, and save its result with
confirmed cleanup and lock release. Validate both smoke and installer evidence,
rerun the normal publisher dry run, and publish only if all gates pass. Then
independently audit the published installers and `update.json`. Use
`scripts/framey-worn-check.py` only with an actual confirmed wearer, and retain
any remaining physical-input limits in the report.
