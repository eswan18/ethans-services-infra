"""Manual verification for wait_for_preview's rendering (ib.py, Task 3).

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

print("\nAll scenarios passed.")
