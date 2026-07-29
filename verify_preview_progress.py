"""Manual verification for wait_for_preview (Task 3) and preview expiry
rendering (Task 4) in ib.py.

Not wired into CI and not a pytest suite -- this repo has no test harness
(no tests/ dir, no test framework in pyproject.toml's dependency groups,
and .github/workflows/pull_request.yaml runs only `ruff check` and
`ty check`). Real bifrost isn't reachable from a plain checkout either, so
this drives wait_for_preview's poll/sleep/is_tty seam with canned records
instead, and prints what it saw so a human can also eyeball it.

Run manually from the repo root: uv run python verify_preview_progress.py
"""

import contextlib
import io
from datetime import datetime, timedelta, timezone

import ib


def ts(seconds_ago: float) -> str:
    """RFC3339 timestamp `seconds_ago` seconds in the past, like bifrost emits."""
    when = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return when.isoformat().replace("+00:00", "Z")


def run(tag, initial_phase, records, is_tty):
    poll = iter(records).__next__
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.wait_for_preview(
                tag, initial_phase, poll=poll, sleep=lambda s: None, is_tty=is_tty
            )
        except SystemExit as e:
            exit_code = e.code
    return out.getvalue(), err.getvalue(), exit_code


def show(label, stdout, stderr, exit_code):
    print(f"\n=== {label} ===")
    print(f"exit_code={exit_code!r}")
    for line in stdout.replace("\r", "\n").splitlines():
        if line:
            print(line)
    if stderr:
        print("--- stderr ---")
        print(stderr, end="")


# 1. Normal creating -> ready, several step transitions, TTY vs non-TTY.
records_ok = [
    {
        "phase": "creating",
        "step": "resolving members: footstrike-api",
        "stepSince": ts(2),
    },
    {"phase": "creating", "step": "building footstrike-api (1/2)", "stepSince": ts(47)},
    {"phase": "creating", "step": "applying manifests", "stepSince": ts(4)},
    {
        "phase": "ready",
        "urls": {
            "footstrike-api": "https://pr-42-footstrike-api.preview.ethanswan.com"
        },
    },
]
out, err, code = run("pr-42", "creating", list(records_ok), is_tty=True)
assert code is None
assert "\r" in out and "✓ " in out and "47s" in out
assert "footstrike-api: https://" in out
show("1. TTY creating -> ready", out, err, code)

out, err, code = run("pr-42", "creating", list(records_ok), is_tty=False)
assert code is None
assert "\r" not in out and "\x1b" not in out
assert not any(f in out for f in ib.SPINNER_FRAMES)
assert "building footstrike-api (1/2)" in out
show("1b. Non-TTY creating -> ready (plain lines, no \\r/ANSI)", out, err, code)

# 2. step absent throughout -- pre-Task-1 server, phase-change-only fallback.
records_old_server = [
    {"phase": "creating"},
    {
        "phase": "ready",
        "urls": {"footstrike-api": "https://pr-9.preview.ethanswan.com"},
    },
]
out, err, code = run("pr-9", "creating", list(records_old_server), is_tty=True)
assert code is None and "\r" not in out and "  ready" in out
show("2. Old-server fallback (no step key), TTY", out, err, code)

# 3. Failed run, step + error present -> richer stderr message.
records_failed = [
    {"phase": "creating", "step": "building footstrike-api (1/2)", "stepSince": ts(1)},
    {
        "phase": "failed",
        "step": "building footstrike-api (1/2)",
        "stepSince": ts(12),
        "error": "docker build exited 1: no space left on device",
    },
]
out, err, code = run("pr-77", "creating", list(records_failed), is_tty=True)
assert code == 1
assert "failed while building footstrike-api (1/2): docker build exited 1" in err
assert "Check the Previews tab in bifrost for details." in err
show("3. Failed run, step + error present, TTY", out, err, code)

# Legacy failed run, no step/error at all.
out, err, code = run(
    "pr-3", "creating", [{"phase": "creating"}, {"phase": "failed"}], is_tty=False
)
assert code == 1 and "Preview pr-3 failed (phase: failed)." in err
show("3b. Failed run, no step/error (old server), non-TTY", out, err, code)

# 4. Malformed/naive stepSince must degrade to the local fallback anchor,
#    not raise. This is exactly the bug a Fix-round-1 review caught: a
#    timezone-naive ISO8601 string parses without ValueError but then
#    can't be subtracted from an aware `datetime.now(timezone.utc)`.
fallback_start_5s_ago = ib.time.time() - 5
for bad_step_since in ("2026-07-29T12:00:00", "2026-07-29", "not-a-timestamp", ""):
    elapsed = ib.step_elapsed_seconds(bad_step_since or None, fallback_start_5s_ago)
    assert 4.5 < elapsed < 6, (
        f"expected ~5s fallback for {bad_step_since!r}, got {elapsed}"
    )
print(
    "\n=== 4. step_elapsed_seconds degrades on naive/malformed stepSince (no raise) ==="
)
print(
    "all of '2026-07-29T12:00:00', '2026-07-29', 'not-a-timestamp', '' -> ~5s fallback, OK"
)

# Same bug, exercised through the real poll loop end-to-end: a naive
# stepSince must not crash wait_for_preview mid-run.
records_naive_ts = [
    {
        "phase": "creating",
        "step": "branching databases",
        "stepSince": "2026-07-29T12:00:00",
    },
    {"phase": "creating", "step": "copying secrets", "stepSince": ts(2)},
    {
        "phase": "ready",
        "urls": {"footstrike-api": "https://pr-5.preview.ethanswan.com"},
    },
]
out, err, code = run("pr-5", "creating", list(records_naive_ts), is_tty=True)
assert code is None, "a naive stepSince must not crash the poll loop"
show("4b. wait_for_preview survives a naive stepSince mid-run", out, err, code)

# 5. Preview expiry rendering (ib.py, Task 4): `expiresAt` absent, a future
# expiry, and one already past due but not yet reaped (the hourly sweep can
# lag by up to an hour, so that's an expected state, not a bug).
no_ttl = {"tag": "pr-10", "branch": "no-ttl", "phase": "ready", "health": "healthy"}
assert "expiresAt" not in no_ttl
assert ib.preview_expiry_display(no_ttl) == "-"

# 8h5s in the future -- the few extra seconds are slack against the moment
# this assertion actually runs, so the result reliably floors to "8h0m"
# rather than flapping to "7h59m" on a slow tick.
future_ttl = {
    "tag": "pr-11",
    "branch": "future-ttl",
    "phase": "ready",
    "health": "healthy",
    "expiresAt": ts(-(8 * 3600 + 5)),
}
assert ib.preview_expiry_display(future_ttl) == "8h0m", ib.preview_expiry_display(
    future_ttl
)

past_due_ttl = {
    "tag": "pr-12",
    "branch": "past-due",
    "phase": "ready",
    "health": "healthy",
    "expiresAt": ts(3600),  # expired an hour ago, not yet reaped by the sweep
}
assert ib.preview_expiry_display(past_due_ttl) == "expired"

print("\n=== 5. preview_expiry_display: absent / future / past-due ===")
print(f"no expiresAt         -> {ib.preview_expiry_display(no_ttl)!r}")
print(f"expires in ~8h       -> {ib.preview_expiry_display(future_ttl)!r}")
print(f"expired ~1h ago      -> {ib.preview_expiry_display(past_due_ttl)!r}")

# Same three cases through the real `preview list` table, so the rendering
# that actually reaches a user's terminal is what's checked, not just the
# helper. Drives ib.preview_list via its injectable `previews` seam (same
# pattern as wait_for_preview's poll/sleep/is_tty) rather than reaching for
# the network -- no monkeypatching needed.
canned_previews = [
    {**no_ttl, "apps": ["footstrike-api"]},
    {**future_ttl, "apps": ["footstrike-api"]},
    {**past_due_ttl, "apps": ["footstrike-api"]},
]
list_out = io.StringIO()
with contextlib.redirect_stdout(list_out):
    ib.preview_list(canned_previews)
list_output = list_out.getvalue()
rows = {line.split()[0]: line for line in list_output.splitlines() if line}
assert "None" not in list_output, "no-TTL row must never render the literal 'None'"
assert "-" in rows["pr-10"]
assert "8h0m" in rows["pr-11"]
assert "expired" in rows["pr-12"]
print("\n=== 5b. `ib preview list` EXPIRES column, same three cases ===")
print(list_output)


# 6. `ib preview up` argument parsing (Task 4, fix round 1): --ttl must
# never be silently dropped. A prior version matched only the exact token
# "--ttl", so "--ttl=8h" (or any other unrecognized token) sat unconsumed
# in args and was thrown away with no error -- the user asked for an 8h
# lifetime and silently got a preview that never expires. parse_up_args now
# requires the leftover args to reduce to exactly one token (the branch);
# anything else -- including a leftover flag it doesn't recognize -- is a
# usage error instead of a silent no-op.
def parse_up(argv_tail: list[str]):
    out, err = io.StringIO(), io.StringIO()
    result = None
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            result = ib.parse_up_args(list(argv_tail))
        except SystemExit as e:
            exit_code = e.code
    return result, out.getvalue(), err.getvalue(), exit_code


cases = [
    ("mybranch", "bare branch, no flags"),
    ("mybranch --ttl 8h", "--ttl 8h (space form)"),
    ("mybranch --ttl 8h --no-wait", "--ttl 8h --no-wait"),
    ("mybranch --ttl=8h", "--ttl=8h (unsupported equals form)"),
    ("mybranch --ttl", "bare --ttl, no value"),
    ("mybranch --typo=x", "unknown leftover flag"),
]
results = {argv: parse_up(argv.split()) for argv, _ in cases}

assert results["mybranch"][0] == (False, None, "mybranch")
assert results["mybranch --ttl 8h"][0] == (False, "8h", "mybranch")
assert results["mybranch --ttl 8h --no-wait"][0] == (True, "8h", "mybranch")
for argv in ("mybranch --ttl=8h", "mybranch --ttl", "mybranch --typo=x"):
    result, out, _err, code = results[argv]
    assert result is None and code == 1, (argv, result, code)
    assert "Usage: ib preview up" in out, (argv, out)

print("\n=== 6. ib preview up argument parsing: --ttl never silently dropped ===")
for argv, label in cases:
    result, out, _err, code = results[argv]
    outcome = result if code is None else f"exit {code}: {out.strip()}"
    print(f"{label:<36} {argv!r:<32} -> {outcome}")

print("\nAll scenarios passed.")
