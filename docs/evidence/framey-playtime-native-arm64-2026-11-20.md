# PlayTime native ARM64 persistence audit, 20 November 2026

PlayTime 3.2.5's compatibility entry still described its ARM64 backend as
unverified. The completed [Decky runtime run 44664045875](https://github.com/saphid/frame-control/actions/runs/44664045875)
contains passing native AMD64 and ARM64 private-session probes at source
`ef41bbb2d85256a73f2aecb98f2de7cefb4f455a`. This change audits those existing
artifacts and updates that one entry. It does not run another backend trial.

The [audit summary](framey-playtime-native-arm64-2026-11-20.json) records artifact,
report, native loader and database hashes. The [compressed case evidence](framey-playtime-native-arm64-2026-11-20.json.gz)
retains each exact PlayTime case, including its RPC results, console, source
fingerprints and serialized SQLite snapshots. Other plugin cases are omitted;
the original full-report hashes remain in the summary. Gzip uses `mtime=0`.
All users, game names and timestamps in these probes are synthetic fixtures.

## Independent audit

Downloaded each artifact ZIP through GitHub and checked its SHA-256 against
GitHub's artifact metadata before reading `decky-runtime.json`. Both reported
native architectures and loader hashes match the pinned published Decky 3.3.0
binaries. All 62 recorded runtime source fingerprints per report match current
main's runtime inputs. The official PlayTime archive digest is
`10fc3beea48991c77cb02867e919b618d4cd6d5e9c6a6d0ccd5266c13214039f`;
all 40 retained Python member hashes match that archive directly.

Checked the literal method order and all 22 RPC results per architecture against
the probe's expected values, rather than relying on its pass flags. Six SQL
readbacks per architecture show a 300-second first-user session, refusal to add
time while paused, a separate 600-second second-user session, and the same
per-user results after a full loader restart. The restarted backend initially
has no selected user and retrieves each user's data after explicit selection.

Decoded all four saved database snapshots into disposable files and opened them
with SQLite `mode=ro`. `PRAGMA integrity_check` returned `ok`. Independent queries
of `game_dict`, `play_time`, `overall_time` and `game_tracking_status` returned
exactly the expected game, single session, total and empty final tracking rows.
The first user's database contains only its 300-second result; the second has
only its 600-second result. Database bytes and SHA-256 stayed unchanged during
the independent read. No existing user database was accessed.

Each architecture records two parent-only SIGTERM stops, both exiting zero in
about 0.214 seconds, with recorded process identities reaped and adopted children
exiting zero. Both specialized loader consoles contain two complete shutdowns
and no forced-kill, shutdown-error, pending-task, cancellation or bad-descriptor
markers. Console hashes match their text.

The outer generic recorder's `cleanShutdownVerified` field remains `false` in
the retained evidence: the specialized PlayTime probe already stopped both
loaders. It is not changed into a positive claim. The explicit parent-stop and
console observations above support the narrower lifecycle result.

## Compatibility scope

The catalog keeps PlayTime **partial**, with the same version, archive digest
and install policy. This evidence covers explicit backend session RPCs and
private SQLite persistence on native AMD64 and ARM64. It does not prove
automatic recording through the unsupported private MobX running-app observer,
a live Steam library, migration of existing user data, frontend/backend settings
integration, real Frame persistence, worn UI visibility, physical controller
input, scrolling or the VR keyboard.

The headset SSH retry timed out during this audit. No wearer was confirmed and
`scripts/framey-worn-check.py` did not run. Earlier browser and real Frame
observations retain their original scope; this audit adds no hardware result.
