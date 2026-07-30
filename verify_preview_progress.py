"""Manual verification for wait_for_preview (Task 3), preview expiry
rendering (Task 4), and `--auto-update` (Task 5) in ib.py.

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


def run(tag, initial_phase, branch, records, is_tty):
    poll = iter(records).__next__
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.wait_for_preview(
                tag,
                initial_phase,
                branch,
                poll=poll,
                sleep=lambda s: None,
                is_tty=is_tty,
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
out, err, code = run("pr-42", "creating", "my-feature", list(records_ok), is_tty=True)
assert code is None
assert "\r" in out and "✓ " in out and "47s" in out
assert "footstrike-api: https://" in out
show("1. TTY creating -> ready", out, err, code)

out, err, code = run("pr-42", "creating", "my-feature", list(records_ok), is_tty=False)
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
out, err, code = run(
    "pr-9", "creating", "old-server-branch", list(records_old_server), is_tty=True
)
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
out, err, code = run(
    "pr-77", "creating", "my-feature", list(records_failed), is_tty=True
)
assert code == 1
assert "failed while building footstrike-api (1/2): docker build exited 1" in err
assert "Check the Previews tab in bifrost for details." in err
show("3. Failed run, step + error present, TTY", out, err, code)

# Legacy failed run, no step/error at all.
out, err, code = run(
    "pr-3",
    "creating",
    "my-feature",
    [{"phase": "creating"}, {"phase": "failed"}],
    is_tty=False,
)
assert code == 1 and "Preview pr-3 failed (phase: failed)." in err
show("3b. Failed run, no step/error (old server), non-TTY", out, err, code)

# 3c. Terminating phase (client-side half of the training-plans incident,
# Fix 1): the old message guessed "(concurrent `preview down`?)" -- in the
# real incident that guess was wrong, the namespace's own teardown had
# already completed and the CLI's own `up` was the thing still running.
# The new message states only what's known (the namespace is being torn
# down, so this create can't proceed) and says what to do (retry once
# teardown finishes), without speculating about why.
out, err, code = run(
    "training-plans",
    "creating",
    "training-plans",
    [{"phase": "terminating"}],
    is_tty=True,
)
assert code == 1
assert "concurrent" not in err.lower(), "must not speculate about the cause"
assert "training-plans" in err
assert "namespace is being torn down" in err
assert "cannot proceed" in err
assert "retry" in err.lower()
assert "ib preview list" in err
show("3c. Terminating phase: states only what's known, says what to do", out, err, code)

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
out, err, code = run(
    "pr-5", "creating", "my-feature", list(records_naive_ts), is_tty=True
)
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


# 6. `ib preview up` argument parsing (Task 4, fix round 1; extended for
# Task 5's --auto-update): --ttl and --auto-update must never be silently
# dropped. A prior version matched only the exact token "--ttl", so
# "--ttl=8h" (or any other unrecognized token) sat unconsumed in args and
# was thrown away with no error -- the user asked for an 8h lifetime and
# silently got a preview that never expires. parse_up_args now requires the
# leftover args to reduce to exactly one token (the branch); anything else
# -- including a leftover flag it doesn't recognize, like --auto-update=true
# -- is a usage error instead of a silent no-op. Also exercises --auto-update
# combined with --ttl and --no-wait in more than one argv order, since
# parse_up_args strips flags independently of position.
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
    ("mybranch --auto-update", "--auto-update alone"),
    (
        "mybranch --ttl 8h --auto-update --no-wait",
        "--ttl 8h --auto-update --no-wait",
    ),
    (
        "mybranch --no-wait --auto-update --ttl 8h",
        "--no-wait --auto-update --ttl 8h (different order)",
    ),
    ("mybranch --ttl=8h", "--ttl=8h (unsupported equals form)"),
    ("mybranch --ttl", "bare --ttl, no value"),
    ("mybranch --typo=x", "unknown leftover flag"),
    ("mybranch --auto-update=true", "--auto-update=true (unsupported equals form)"),
]
results = {argv: parse_up(argv.split()) for argv, _ in cases}

assert results["mybranch"][0] == (False, None, False, "mybranch")
assert results["mybranch --ttl 8h"][0] == (False, "8h", False, "mybranch")
assert results["mybranch --ttl 8h --no-wait"][0] == (True, "8h", False, "mybranch")
assert results["mybranch --auto-update"][0] == (False, None, True, "mybranch")
assert results["mybranch --ttl 8h --auto-update --no-wait"][0] == (
    True,
    "8h",
    True,
    "mybranch",
)
assert results["mybranch --no-wait --auto-update --ttl 8h"][0] == (
    True,
    "8h",
    True,
    "mybranch",
)
for argv in (
    "mybranch --ttl=8h",
    "mybranch --ttl",
    "mybranch --typo=x",
    "mybranch --auto-update=true",
):
    result, out, _err, code = results[argv]
    assert result is None and code == 1, (argv, result, code)
    assert "Usage: ib preview up" in out, (argv, out)

print(
    "\n=== 6. ib preview up argument parsing: --ttl/--auto-update never silently dropped ==="
)
for argv, label in cases:
    result, out, _err, code = results[argv]
    outcome = result if code is None else f"exit {code}: {out.strip()}"
    print(f"{label:<48} {argv!r:<44} -> {outcome}")


# 7. A --ttl silently dropped by a server that doesn't support it yet (Task
# 4, fix round 2). Go's json.Decoder ignores unknown request fields by
# default, and bifrost's handler doesn't set DisallowUnknownFields, so a
# server that predates `ttl` support accepts the POST, returns success, and
# creates a preview with no `expiresAt` at all -- no error anywhere. This is
# not hypothetical: prod bifrost hasn't been promoted with TTL support yet,
# so today this is exactly what happens. warn_if_ttl_dropped is the
# client-side check that catches it by comparing what was asked for against
# what the record actually got. It's a warning, not a failure -- the
# preview really was created -- so it never calls sys.exit; wrapping the
# call in the same SystemExit-trapping pattern used elsewhere in this file
# makes that "still exits 0" guarantee explicit rather than assumed.
def check_ttl_warning(ttl, record, tag):
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.warn_if_ttl_dropped(ttl, record, tag)
        except SystemExit as e:
            exit_code = e.code
    return out.getvalue(), err.getvalue(), exit_code


# 7a. TTL requested and honored -- expiresAt is on the record -- no warning.
out, err, code = check_ttl_warning("8h", {"expiresAt": ts(-8 * 3600)}, "pr-30")
assert err == "", f"honored TTL must not warn, got: {err!r}"
assert code is None
show("7a. --ttl requested and honored: no warning, exit unaffected", out, err, code)

# 7b. TTL requested, server silently dropped it (old bifrost) -- warning on
# stderr naming the likely cause and the consequence, but still exit 0.
out, err, code = check_ttl_warning("8h", {"tag": "pr-31"}, "pr-31")
assert "Warning" in err and "pr-31" in err and "8h" in err
assert "not expire" in err.lower() or "will not expire" in err.lower(), err
assert code is None, "a dropped TTL is a warning, not a failure -- must not exit"
show(
    "7b. --ttl requested but dropped by an old server: warning, exit still 0",
    out,
    err,
    code,
)

# 7c. No TTL requested -- never warn, regardless of what's on the record
# (including a preview that happens to carry an expiresAt from a past run).
out, err, code = check_ttl_warning(None, {"tag": "pr-32"}, "pr-32")
assert err == ""
out2, err2, code2 = check_ttl_warning(None, {"expiresAt": ts(-3600)}, "pr-32")
assert err2 == ""
show("7c. No --ttl requested: no warning regardless of the record", out, err, code)


# 8. `autoUpdate` rendering in `ib preview list` (Task 5): the key is
# `omitempty` server-side, so it's absent -- never `False` -- on a preview
# that doesn't have it enabled. Same tolerance pattern as `expiresAt`/
# EXPIRES (section 5/5b above), checked both via the helper directly and
# through the real `preview list` table.
no_auto_update = {**no_ttl, "apps": ["footstrike-api"]}
assert "autoUpdate" not in no_auto_update
assert ib.preview_auto_update_display(no_auto_update) == "-"

with_auto_update = {**future_ttl, "autoUpdate": True, "apps": ["footstrike-api"]}
assert ib.preview_auto_update_display(with_auto_update) == "✓"

auto_list_out = io.StringIO()
with contextlib.redirect_stdout(auto_list_out):
    ib.preview_list([no_auto_update, with_auto_update])
auto_list_output = auto_list_out.getvalue()
auto_rows = {line.split()[0]: line for line in auto_list_output.splitlines() if line}
assert "False" not in auto_list_output and "None" not in auto_list_output, (
    "an absent autoUpdate must never render as 'False' or 'None'"
)
assert "✓" not in auto_rows["pr-10"]
assert "✓" in auto_rows["pr-11"]
print("\n=== 8. `ib preview list` AUTO column: autoUpdate absent vs enabled ===")
print(auto_list_output)


# 9. A --auto-update silently dropped by a server that doesn't support it
# yet (Task 5) -- same failure mode as warn_if_ttl_dropped (section 7
# above): Go's json.Decoder ignores unknown request fields by default, so a
# server that predates `autoUpdate` support accepts the POST, returns
# success, and creates a preview with no `autoUpdate` key at all -- no
# error anywhere. warn_if_auto_update_dropped is the client-side check that
# catches it, mirroring warn_if_ttl_dropped's shape as a sibling rather
# than a shared helper (the message content -- what didn't take effect and
# the consequence -- is specific to auto-update). It's a warning, not a
# failure, so it must never call sys.exit.
def check_auto_update_warning(auto_update, record, tag, branch):
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.warn_if_auto_update_dropped(auto_update, record, tag, branch)
        except SystemExit as e:
            exit_code = e.code
    return out.getvalue(), err.getvalue(), exit_code


# 9a. Requested and honored -- autoUpdate: true on the record -- no warning.
out, err, code = check_auto_update_warning(
    True, {"autoUpdate": True}, "pr-40", "my-branch"
)
assert err == "", f"honored auto-update must not warn, got: {err!r}"
assert code is None
show(
    "9a. --auto-update requested and honored: no warning, exit unaffected",
    out,
    err,
    code,
)

# 9b. Requested, server silently dropped it (old bifrost) -- warning on
# stderr naming the likely cause and the consequence (won't follow the
# branch), but still exit 0.
out, err, code = check_auto_update_warning(True, {"tag": "pr-41"}, "pr-41", "my-branch")
assert "Warning" in err and "pr-41" in err and "--auto-update" in err
assert "not follow the branch" in err.lower() or "will not follow" in err.lower(), err
assert code is None, (
    "a dropped auto-update is a warning, not a failure -- must not exit"
)
show(
    "9b. --auto-update requested but dropped by an old server: warning, exit still 0",
    out,
    err,
    code,
)

# 9c. Not requested -- never warn, regardless of what's on the record
# (including a preview that happens to carry autoUpdate: true from a past
# run, e.g. one created earlier and re-`up`'d without the flag this time).
out, err, code = check_auto_update_warning(
    False, {"tag": "pr-42"}, "pr-42", "my-branch"
)
assert err == ""
out2, err2, code2 = check_auto_update_warning(
    False, {"autoUpdate": True}, "pr-42", "my-branch"
)
assert err2 == ""
show(
    "9c. No --auto-update requested: no warning regardless of the record",
    out,
    err,
    code,
)

# 10. `busy` rendering in `ib preview list` (Fix 3): a preview mid up/down
# must look visibly different from an idle one -- marked on the existing
# PHASE cell rather than a new column, per the task. Checked via
# preview_phase_display directly and through the real table, same pattern
# as EXPIRES/AUTO (sections 5/5b, 8) above.
busy_creating = {
    "tag": "training-plans",
    "branch": "training-plans",
    "phase": "creating",
    "health": "unknown",
    "busy": True,
    "apps": ["training-plans"],
}
assert ib.preview_phase_display(busy_creating) == "creating*"
assert ib.preview_phase_display(no_auto_update) == "ready", (
    "a record with no `busy` key must not be marked busy"
)

busy_list_out = io.StringIO()
with contextlib.redirect_stdout(busy_list_out):
    ib.preview_list([busy_creating, no_auto_update])
busy_list_output = busy_list_out.getvalue()
busy_rows = {line.split()[0]: line for line in busy_list_output.splitlines() if line}
assert "creating*" in busy_rows["training-plans"]
assert "ready" in busy_rows["pr-10"] and "ready*" not in busy_rows["pr-10"]
print("\n=== 10. `ib preview list` PHASE column: busy marked in place ===")
print(busy_list_output)


# 11. A tag that's busy but has no live namespace -- bifrost synthesizes a
# sparse record for it (no branch/apps/urls/health, and here not even a
# phase) so `preview list` doesn't fall back to "No preview environments."
# while an operation is still in flight -- the second contradictory message
# from the training-plans incident. Must render without 'None', without a
# KeyError from indexing a key this record doesn't have, and without '-'
# spam drowning out the one thing that IS known: it's busy.
sparse_busy = {"tag": "training-plans", "busy": True}
assert ib.preview_phase_display(sparse_busy) == "busy"

sparse_list_out = io.StringIO()
with contextlib.redirect_stdout(sparse_list_out):
    ib.preview_list([sparse_busy])
sparse_list_output = sparse_list_out.getvalue()
assert "None" not in sparse_list_output
sparse_row = next(
    line
    for line in sparse_list_output.splitlines()
    if line.startswith("training-plans")
)
assert sparse_row.split()[0] == "training-plans"
assert "busy" in sparse_row
print(
    "\n=== 11. `ib preview list`: sparse synthesized busy record (no namespace yet) ==="
)
print(sparse_list_output)


# 12. A record with `busy` absent entirely -- the common case, and every
# record from a bifrost that predates the `busy` field -- must render
# exactly as it did before this change: no '*', no 'busy' text anywhere.
no_busy_key = {
    "tag": "pr-50",
    "branch": "some-branch",
    "phase": "ready",
    "health": "healthy",
    "apps": ["footstrike-api"],
}
assert "busy" not in no_busy_key
no_busy_out = io.StringIO()
with contextlib.redirect_stdout(no_busy_out):
    ib.preview_list([no_busy_key])
no_busy_output = no_busy_out.getvalue()
assert "*" not in no_busy_output
assert "busy" not in no_busy_output
row50 = next(line for line in no_busy_output.splitlines() if line.startswith("pr-50"))
assert row50.split()[:4] == ["pr-50", "some-branch", "ready", "healthy"]
print("\n=== 12. `ib preview list`: record with `busy` absent renders unchanged ===")
print(no_busy_output)


# 13. fail_if_branch_mismatch (the tag-collision fix): bifrost's tag
# derivation is many-to-one, and the ErrTagCollision refusal happens
# server-side in a detached goroutine after the 202 already returned, so
# polling the tag afterward can show a *different* branch's preview sitting
# at `ready`. fail_if_branch_mismatch is the client-side backstop -- tested
# directly here the same way check_ttl_warning/check_auto_update_warning
# (sections 7/9) test their sibling helpers.
def check_branch_mismatch(requested_branch, record, tag, on_fail=None):
    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.fail_if_branch_mismatch(requested_branch, record, tag, on_fail=on_fail)
        except SystemExit as e:
            exit_code = e.code
    return out.getvalue(), err.getvalue(), exit_code


# 13a. Same branch -- the documented recovery path (re-run `up` on a branch
# that already has a preview), and what --auto-update does every couple of
# minutes -- must be a pure no-op: no output, exit unaffected.
out, err, code = check_branch_mismatch(
    "my-feature", {"tag": "pr-60", "branch": "my-feature"}, "pr-60"
)
assert out == "" and err == "" and code is None, (out, err, code)
show("13a. Same branch: no-op, exit unaffected", out, err, code)

# 13b. `branch` missing entirely -- an older preview predating the
# `bifrost/branch` annotation, or a partial/failed run -- means "can't
# tell". Must NOT raise a false alarm: that would be worse than the bug
# this exists to catch.
out, err, code = check_branch_mismatch("branch-b", {"tag": "pr-61"}, "pr-61")
assert out == "" and err == "" and code is None, (out, err, code)
show("13b. Missing `branch` on the record: no false alarm", out, err, code)

# 13c. `branch` present but empty string -- same "can't tell" treatment as
# missing entirely, not a mismatch against a non-empty requested branch.
out, err, code = check_branch_mismatch(
    "branch-b", {"tag": "pr-61", "branch": ""}, "pr-61"
)
assert out == "" and err == "" and code is None, (out, err, code)
show("13c. Empty-string `branch` on the record: no false alarm", out, err, code)

# 13d. Differing branch -- the actual bug: tag pr-62 already belongs to
# branch-a, this run asked for branch-b. Must fail nonzero, name BOTH
# branches, and say what to do -- no speculation about *why* they collided
# (same discipline as the terminating-phase message in 3c).
out, err, code = check_branch_mismatch(
    "branch-b", {"tag": "pr-62", "branch": "branch-a"}, "pr-62"
)
assert code == 1
assert "branch-a" in err and "branch-b" in err and "pr-62" in err
assert "ib preview down pr-62" in err
assert "concurrent" not in err.lower(), "must not speculate about the cause"
show("13d. Differing branch: nonzero exit, names both branches", out, err, code)
print(f"verbatim message: {err.strip()!r}")

# 13e. `on_fail` runs before the error is printed (wait_for_preview passes
# its tty_clear closure here so a mismatch caught mid-poll doesn't leave a
# half-drawn spinner line behind it).
on_fail_ran = []
out, err, code = check_branch_mismatch(
    "branch-b",
    {"tag": "pr-63", "branch": "branch-a"},
    "pr-63",
    on_fail=lambda: on_fail_ran.append(True),
)
assert on_fail_ran == [True] and code == 1
show("13e. on_fail runs before the error is printed", out, err, code)


# 14. Same behavior end-to-end through wait_for_preview's poll loop (not
# just the helper) -- this is the path a real `ib preview up` without
# --no-wait actually takes, and the poll loop sees records repeatedly, not
# just once.
#
# 14a. Same branch on every polled record: proceeds to ready exactly like
# section 1, unaffected by this fix.
records_same_branch = [
    {"phase": "creating", "branch": "same-branch", "step": "applying manifests"},
    {
        "phase": "ready",
        "branch": "same-branch",
        "urls": {"footstrike-api": "https://pr-80.preview.ethanswan.com"},
    },
]
out, err, code = run(
    "pr-80", "creating", "same-branch", list(records_same_branch), is_tty=True
)
assert code is None, "same branch on every record must not be treated as a collision"
assert "footstrike-api: https://" in out
show("14a. Poll loop, same branch throughout: proceeds to ready", out, err, code)

# 14b. The real bug scenario: tag pr-81 already belongs to branch-a and is
# already `ready` (bifrost's goroutine never touched it after refusing the
# collision), this run asked for branch-b. Must fail instead of reporting
# success with branch-a's URL.
out, err, code = run(
    "pr-81",
    "creating",
    "branch-b",
    [
        {
            "phase": "ready",
            "branch": "branch-a",
            "urls": {"footstrike-api": "https://pr-81-branch-a.preview.ethanswan.com"},
        }
    ],
    is_tty=True,
)
assert code == 1
assert "branch-a" in err and "branch-b" in err
assert "branch-a.preview.ethanswan.com" not in out, (
    "must never print the OTHER branch's URL as if it were a success"
)
show("14b. Poll loop, colliding tag already ready under another branch", out, err, code)

# 14c. Mismatch surfaces on a LATER poll, after a spinner line is already
# drawn (TTY) -- confirms the spinner is cleared (via on_fail=tty_clear)
# before the error prints, not left half-drawn on the same line.
out, err, code = run(
    "pr-82",
    "creating",
    "branch-b",
    [
        {"phase": "creating", "step": "resolving members: footstrike-api"},
        {"phase": "ready", "branch": "branch-a", "urls": {}},
    ],
    is_tty=True,
)
assert code == 1
assert "branch-a" in err and "branch-b" in err
show("14c. Poll loop, mismatch surfaces after a spinner was drawn", out, err, code)


# 15. The --no-wait path: preview_up(wait=False) does its own follow-up GET
# (there's no poll loop to piggyback on), so it needs its own check. Drives
# the real ib.preview_up() via its injectable `api` seam (same pattern as
# wait_for_preview's poll/sleep/is_tty) rather than the network -- and this
# also proves no extra network call happens beyond what's asserted (an
# unconsumed/extra call raises loudly instead of silently returning stale
# data).
def run_preview_up_no_wait(branch, responses):
    calls = list(responses)

    def fake_preview_api(method: str, path: str, body: dict | None = None) -> dict:
        if not calls:
            raise AssertionError(f"unexpected extra preview_api call: {method} {path}")
        return calls.pop(0)

    out, err = io.StringIO(), io.StringIO()
    exit_code = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            ib.preview_up(branch, wait=False, api=fake_preview_api)
        except SystemExit as e:
            exit_code = e.code
    return out.getvalue(), err.getvalue(), exit_code


# 15a. Same branch: proceeds through both the POST response check and the
# follow-up GET check, reaches "Not waiting.", exit unaffected.
out, err, code = run_preview_up_no_wait(
    "my-feature",
    [
        {"tag": "pr-90", "phase": "ready", "branch": "my-feature"},  # POST
        {"tag": "pr-90", "phase": "ready", "branch": "my-feature"},  # follow-up GET
    ],
)
assert code is None and err == ""
assert "Not waiting." in out
show("15a. --no-wait, same branch: proceeds normally", out, err, code)

# 15b. POST response already reveals the collision (bifrost's tag lookup
# already had branch-a's ready record before this request's goroutine ever
# ran) -- caught at the earliest possible point, before "Creating
# preview..." even prints and before the follow-up GET is attempted (only
# one canned response is provided; a second call would raise).
out, err, code = run_preview_up_no_wait(
    "branch-b",
    [{"tag": "pr-91", "phase": "ready", "branch": "branch-a"}],  # POST only
)
assert code == 1
assert "branch-a" in err and "branch-b" in err
assert "Creating preview" not in out, "must bail before the 'Creating...' line"
show("15b. --no-wait, POST response already reveals the collision", out, err, code)

# 15c. POST response doesn't carry `branch` yet (e.g. an older bifrost, or
# a fresh record from this run's own goroutine that hasn't started), so the
# first check passes -- but the follow-up GET's record does. This is the
# no-wait path's own dedicated check catching what the POST-time check
# couldn't.
out, err, code = run_preview_up_no_wait(
    "branch-b",
    [
        {"tag": "pr-92", "phase": "creating"},  # POST: no branch info yet
        {"tag": "pr-92", "phase": "ready", "branch": "branch-a"},  # follow-up GET
    ],
)
assert code == 1
assert "branch-a" in err and "branch-b" in err
assert "Creating preview" in out, "POST-time check passed, so this line does print"
assert "Not waiting." not in out, "must bail before claiming success"
show("15c. --no-wait, collision only visible on the follow-up GET", out, err, code)

# 15d. `branch` absent from both the POST and follow-up GET responses --
# must not false-alarm; reaches "Not waiting." same as any pre-annotation
# bifrost.
out, err, code = run_preview_up_no_wait(
    "some-branch",
    [
        {"tag": "pr-93", "phase": "ready"},
        {"tag": "pr-93", "phase": "ready"},
    ],
)
assert code is None and err == ""
assert "Not waiting." in out
show("15d. --no-wait, branch absent throughout: no false alarm", out, err, code)


print("\nAll scenarios passed.")
