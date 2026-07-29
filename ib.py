"""
Deployment status and promotion helper for GKE services.

Usage:
    ib status               # Show status for all services
    ib status <app>         # Show current images for staging and prod
    ib status -q            # List out-of-sync services (* = mid-deploy)
    ib status <app> -q      # Exit 0 if in sync, 1 if not (minimal output)
    ib promote <app>        # Compare staging vs prod, offer to promote
    ib promote <app> -y     # Promote without confirmation
    ib preview list                     # Table of preview environments, TTL remaining
    ib preview up <branch>              # Create/update, show live progress, print URLs
    ib preview up <branch> --ttl 8h     # Same, but auto-expire (and get reaped) after 8h
    ib preview up <branch> --no-wait    # Fire and return the tag
    ib preview up <branch> --auto-update  # Same, but redeploy automatically when the branch moves
    ib preview down <tag>               # Tear down (confirm unless -y/--yes)

    Preview concepts (membership, the registry, the resolution cascade,
    onboarding a new previewable app) live in bifrost's
    docs/preview-environments.md, not here -- this is just the CLI surface.

    `--ttl` takes a Go duration string like `8h` or `90m`. bifrost owns
    parsing and validation (rejects a non-positive or unparseable value, or
    one over the 720h/30-day cap) and its error message is shown verbatim
    on a bad value -- this CLI does not re-validate it. Expiry is opt-in:
    omitting `--ttl`, including on a re-run of `up` for an existing
    preview, means the preview never expires, and a bare re-run clears a
    TTL set earlier. `preview list` shows the remaining time per preview,
    `-` for one with no TTL, and `expired` for one whose TTL has passed but
    hasn't been reaped yet by bifrost's hourly sweep (up to an hour of lag
    is normal, not a bug). If `--ttl` was requested but the created preview
    comes back with no expiry -- e.g. an older bifrost that predates `ttl`
    support and silently ignores the field -- `preview up` prints a warning
    to stderr and still exits 0: the preview was created and is usable,
    just without the lifetime that was asked for.

    `--auto-update` opts a preview into bifrost's watcher: every 2 minutes
    it checks whether the preview's branch has moved and, if so, redeploys
    it -- exactly what a manual `ib preview up <branch>` does, just on a
    timer. It's opt-in on purpose: a redeploy rebuilds every member of the
    preview, and a failing build marks a previously-working preview
    `failed`. Composes with `--ttl` and `--no-wait` in any order. `preview
    list` marks an auto-updating preview with a `✓` in the AUTO column; one
    without it renders `-`, same convention as EXPIRES. If `--auto-update`
    was requested but the created preview comes back without the flag --
    e.g. an older bifrost that predates `autoUpdate` support and silently
    ignores the field -- `preview up` prints a warning to stderr and still
    exits 0: the preview was created and is usable, it just won't follow
    the branch on its own.

    `preview up` polls every 3s while a preview is being created. On a
    terminal it redraws a single line with a spinner, the current build
    step, and elapsed time; piped or redirected output (CI logs, `| tee`)
    instead prints one plain line per step, no spinner or carriage returns.
    Against an older bifrost that doesn't report steps yet, it falls back
    to printing only on phase changes.

Examples:
    ib status
    ib status footstrike-api
    ib status -q
    ib promote footstrike-dashboard
    ib preview list
    ib preview up my-feature-branch
    ib preview up my-feature-branch --ttl 8h
    ib preview up my-feature-branch --no-wait
    ib preview up my-feature-branch --auto-update
    ib preview up my-feature-branch --ttl 8h --auto-update --no-wait
    ib preview down my-feature-branch -y

    # Preview a branch that spans two repos: push the SAME branch name to
    # each repo whose changes belong together, then bring up one preview.
    # `up` includes only the repos where that branch actually exists --
    # anything else in the preview resolves to shared staging.
    #   (in footstrike-api/)      git push origin my-feature
    #   (in footstrike-dashboard/) git push origin my-feature
    ib preview up my-feature
"""

import json
import subprocess
import sys
import re
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

REGISTRY = "us-central1-docker.pkg.dev/ethans-services/containers"

BIFROST_URL = os.environ.get("BIFROST_URL", "https://bifrost.ethanswan.com")
PREVIEW_TOKEN_SECRET = "bifrost_prod_preview_api_token"

SERVICES = [
    "asset-manager",
    "bifrost",
    "comms",
    "footstrike-api",
    "footstrike-dashboard",
    "forecasting",
    "identity",
]


def run(cmd: list[str]) -> str:
    """Run a command and return stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def preview_token() -> str:
    """Fetch the preview API bearer token from Secret Manager."""
    return run(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            f"--secret={PREVIEW_TOKEN_SECRET}",
        ]
    )


def preview_api(method: str, path: str, body: dict | None = None) -> dict:
    """Call bifrost's preview API. Exits with a clear message on failure."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BIFROST_URL}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {preview_token()}",
            "Accept": "application/json",
            # Cloudflare's WAF bans the default "Python-urllib/x.y" signature
            # outright (error 1010, browser_signature_banned) before the
            # request ever reaches bifrost -- a real User-Agent is required.
            "User-Agent": "ib-preview-cli",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err_body = e.read()
        try:
            detail = json.loads(err_body).get("error", "")
        except Exception:
            # Not a JSON body (e.g. a plain-text 404/405 from the router
            # itself, before it reaches bifrost's handlers) -- fall back to
            # the raw text rather than printing an empty detail.
            detail = err_body.decode(errors="replace").strip()
        if e.code == 503:
            print(
                "Preview API unavailable — bifrost has no preview config.",
                file=sys.stderr,
            )
        elif e.code == 409:
            print(
                "That preview is busy — another up/down is in flight.", file=sys.stderr
            )
        elif e.code == 401:
            print("Unauthorized — check the preview API token.", file=sys.stderr)
        else:
            print(f"Preview API error {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach bifrost at {BIFROST_URL}: {e.reason}", file=sys.stderr)
        sys.exit(1)


def images_from_pods(pods: list[dict]) -> set[str]:
    """Unique container images across a namespace's long-running pods.

    Job-owned pods (cron/one-off jobs) are excluded: a completed job pod
    keeps the image it ran with, which would read as a deployment forever
    in progress once the deployment moves to a newer image. Everything
    else counts regardless of phase, since mid-deploy detection relies on
    seeing old and new pods side by side.
    """
    images: set[str] = set()
    for pod in pods:
        owners = pod.get("metadata", {}).get("ownerReferences") or []
        if any(o.get("kind") == "Job" for o in owners if o.get("controller")):
            continue
        for container in pod.get("spec", {}).get("containers", []):
            images.add(container["image"])
    return images


def get_deployed_images(namespace: str) -> set[str]:
    """Get all unique images currently deployed in a namespace."""
    try:
        output = run(["kubectl", "get", "pods", "-n", namespace, "-o", "json"])
    except SystemExit:
        return set()
    if not output:
        return set()
    return images_from_pods(json.loads(output).get("items", []))


def extract_tag(image: str) -> str:
    """Extract the tag from a full image URL."""
    if ":" in image:
        return image.split(":")[-1]
    return "latest"


def extract_sha(tag: str) -> str | None:
    """Extract the SHA from a tag. Handles 'abc123-staging', 'abc123-prod', or plain 'abc123'."""
    # Try suffixed format first
    match = re.match(r"^([a-f0-9]+)-(staging|prod)$", tag)
    if match:
        return match.group(1)
    # Try plain SHA
    match = re.match(r"^([a-f0-9]{7,})$", tag)
    if match:
        return match.group(1)
    return None


def new_prod_tag_for(staging_tag: str, prod_tag: str | None, staging_sha: str) -> str:
    """Compute the prod tag to deploy when promoting `staging_sha`.

    The tag scheme must follow the artifact actually being promoted, which is
    the staging image -- NOT the current prod image. A service can migrate to
    environment-agnostic builds (plain `{sha}` + `latest`, no `-prod`/`-staging`
    suffix) while prod still runs a legacy `{sha}-prod` image. Keying off the
    stale prod tag in that window synthesizes a `{sha}-prod` reference that was
    never built, causing ImagePullBackOff (forecasting prod outage, June 2026).
    """
    uses_suffix = "-staging" in staging_tag
    return f"{staging_sha}-prod" if uses_suffix else staging_sha


def status(app: str, quiet: bool = False) -> bool | None:
    """Show current deployment status for an app.

    Returns True if in sync, False if out of sync, None if indeterminate.
    """
    staging_images = get_deployed_images(f"{app}-staging")
    prod_images = get_deployed_images(f"{app}-prod")

    if quiet:
        if not staging_images or not prod_images:
            return None
        if len(staging_images) > 1 or len(prod_images) > 1:
            print(f"{app}*")
            return None
        staging_sha = extract_sha(extract_tag(next(iter(staging_images))))
        prod_sha = extract_sha(extract_tag(next(iter(prod_images))))
        if not staging_sha or not prod_sha:
            return None
        if staging_sha == prod_sha:
            return True
        print(app)
        return False

    print(f"\n{app} deployment status:")
    print("-" * 50)

    # Display staging images
    if not staging_images:
        print("  staging: (no pods found)")
        staging_tag = None
    elif len(staging_images) == 1:
        staging_tag = extract_tag(next(iter(staging_images)))
        print(f"  staging: {staging_tag}")
    else:
        staging_tag = None
        print("  staging:")
        for img in sorted(staging_images):
            print(f"    - {extract_tag(img)}")

    # Display prod images
    if not prod_images:
        print("  prod:    (no pods found)")
        prod_tag = None
    elif len(prod_images) == 1:
        prod_tag = extract_tag(next(iter(prod_images)))
        print(f"  prod:    {prod_tag}")
    else:
        prod_tag = None
        print("  prod:")
        for img in sorted(prod_images):
            print(f"    - {extract_tag(img)}")

    # Check for mismatches within environments
    if len(staging_images) > 1:
        print("\n⚠ Staging has an image mismatch (deployment in progress?)")
        return None
    elif len(prod_images) > 1:
        print("\n⚠ Prod has an image mismatch (deployment in progress?)")
        return None
    elif staging_tag and prod_tag:
        staging_sha = extract_sha(staging_tag)
        prod_sha = extract_sha(prod_tag)
        if staging_sha and prod_sha:
            if staging_sha == prod_sha:
                print("\n✓ In sync")
                return True
            else:
                # Determine what the new prod tag would be
                new_prod_tag = new_prod_tag_for(staging_tag, prod_tag, staging_sha)
                print("\n✗ Out of sync")
                print(f"  To promote: ib promote {app}")
                print(f"  This will deploy {new_prod_tag} to prod")
                return False
    print()
    return None


def promote(app: str, yes: bool = False) -> None:
    """Compare staging vs prod and offer to promote."""
    staging_ns = f"{app}-staging"
    prod_ns = f"{app}-prod"

    staging_images = get_deployed_images(staging_ns)
    prod_images = get_deployed_images(prod_ns)

    if not staging_images:
        print(f"Error: Could not find staging deployment in {staging_ns}")
        sys.exit(1)

    if not prod_images:
        print(f"Error: Could not find prod deployment in {prod_ns}")
        sys.exit(1)

    # Check for image mismatches
    if len(staging_images) > 1:
        print("Error: Staging has an image mismatch (deployment in progress?)")
        print("  Images found:")
        for img in sorted(staging_images):
            print(f"    - {extract_tag(img)}")
        print("\nWait for the deployment to complete before promoting.")
        sys.exit(1)

    if len(prod_images) > 1:
        print("Warning: Prod has an image mismatch (deployment in progress?)")
        print("  Images found:")
        for img in sorted(prod_images):
            print(f"    - {extract_tag(img)}")
        print()

    staging_image = next(iter(staging_images))
    prod_image = next(iter(prod_images))
    staging_tag = extract_tag(staging_image)
    prod_tag = extract_tag(prod_image)

    staging_sha = extract_sha(staging_tag)
    prod_sha = extract_sha(prod_tag)

    print(f"\n{app} promotion check:")
    print("-" * 50)
    print(f"  staging: {staging_tag}")
    print(f"  prod:    {prod_tag}")

    if staging_sha and prod_sha and staging_sha == prod_sha:
        print(f"\n✓ Already in sync (both on {staging_sha})")
        return

    if not staging_sha:
        print(f"\nWarning: Could not parse staging SHA from '{staging_tag}'")
        return

    # Determine the prod tag from the artifact being promoted (staging),
    # not the current prod tag -- see new_prod_tag_for.
    new_prod_tag = new_prod_tag_for(staging_tag, prod_tag, staging_sha)

    image_base = f"{REGISTRY}/{app}"
    new_prod_image = f"{image_base}:{new_prod_tag}"

    print(f"\n→ Promote prod to: {new_prod_tag}")

    if not yes:
        response = input("\nProceed? [y/N] ").strip().lower()
        if response != "y":
            print("Aborted.")
            return

    # Run argocd app set
    argocd_app = f"{app}-prod"
    patch = json.dumps(
        {
            "spec": {
                "source": {
                    "kustomize": {
                        "images": [f"{image_base}={new_prod_image}"],
                    }
                }
            }
        }
    )
    cmd = [
        "kubectl",
        "patch",
        "application",
        argocd_app,
        "-n",
        "argocd",
        "--type=merge",
        "-p",
        patch,
    ]

    print(f"\nRunning: kubectl patch application {argocd_app} -n argocd")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("\n✗ Promotion failed")
        error_output = result.stderr or result.stdout
        if error_output:
            print(f"  {error_output.strip()}")
        sys.exit(1)

    print(f"\n✓ Promoted {app} prod to {new_prod_tag}")
    print("  (ArgoCD will sync automatically)")


def validate_app(app: str) -> None:
    """Validate that the app name is a known service."""
    if app not in SERVICES:
        print(f"Unknown service: {app}")
        print(f"Known services: {', '.join(SERVICES)}")
        sys.exit(1)


def format_ttl_remaining(expires_at: datetime, now: datetime | None = None) -> str:
    """Render time remaining until `expires_at`, like '8h0m' or '3d2h'.

    bifrost's sweep for reaping past-due previews runs hourly, so a preview
    can sit expired-but-alive for up to an hour -- that's rendered as
    'expired' rather than a misleading negative duration.
    """
    now = now or datetime.now(timezone.utc)
    remaining = (expires_at - now).total_seconds()
    if remaining <= 0:
        return "expired"
    total_minutes = int(remaining // 60)
    if total_minutes < 1:
        return "<1m"
    days, rem_minutes = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem_minutes, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{minutes}m"
    return f"{minutes}m"


def preview_expiry_display(p: dict) -> str:
    """Remaining-TTL cell for a `preview list` row.

    `expiresAt` is `omitzero` server-side, so it's plain *absent* (never ""
    or null) on a preview with no TTL -- `.get()` with a default renders
    that as '-', never the string 'None'. Also falls back to '-' on a
    malformed or timezone-naive timestamp instead of raising, same
    tolerance `parse_rfc3339`/`step_elapsed_seconds` already have.
    """
    expires_at = p.get("expiresAt")
    if not expires_at:
        return "-"
    try:
        return format_ttl_remaining(parse_rfc3339(expires_at))
    except (ValueError, TypeError):
        return "-"


def preview_auto_update_display(p: dict) -> str:
    """AUTO column for a `preview list` row.

    `autoUpdate` is `omitempty` server-side, so it's plain *absent* (never
    `false` or null) on a preview that doesn't have it enabled -- `.get()`
    with a default renders that as '-', never the string 'False'. Same
    tolerance pattern as `preview_expiry_display`/EXPIRES.
    """
    return "✓" if p.get("autoUpdate", False) else "-"


def preview_list(previews: list[dict] | None = None) -> None:
    """Print the preview table.

    `previews` is normally fetched live; overridable so callers (tests) can
    drive rendering off canned records instead of the real API -- same
    seam pattern as `wait_for_preview`'s `poll`/`sleep`/`is_tty`.
    """
    if previews is None:
        previews = preview_api("GET", "/api/previews").get("previews") or []
    if not previews:
        print("No preview environments.")
        return
    print(
        f"{'TAG':<24} {'BRANCH':<24} {'PHASE':<10} {'HEALTH':<12} {'EXPIRES':<10} "
        f"{'AUTO':<5} APPS"
    )
    for p in previews:
        apps = ",".join(p.get("apps") or [])
        expires = preview_expiry_display(p)
        auto = preview_auto_update_display(p)
        print(
            f"{p['tag']:<24} {p['branch']:<24} {p['phase']:<10} {p['health']:<12} "
            f"{expires:<10} {auto:<5} {apps}"
        )


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner_frame(tick: int) -> str:
    """The spinner glyph for poll tick `tick` (cycles through SPINNER_FRAMES)."""
    return SPINNER_FRAMES[tick % len(SPINNER_FRAMES)]


def format_elapsed(seconds: float) -> str:
    """Render a non-negative second count like '47s' or '2m03s'."""
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m{secs:02d}s"


def parse_rfc3339(ts: str) -> datetime:
    """Parse an RFC3339 timestamp like bifrost's `stepSince` field.

    Tolerates a trailing 'Z' (UTC) and sub-microsecond fractional seconds --
    Go can emit nanosecond precision, but datetime.fromisoformat tops out at
    microseconds.
    """
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    s = re.sub(r"(\.\d{6})\d+", r"\1", s)
    return datetime.fromisoformat(s)


def step_elapsed_seconds(step_since: str | None, fallback_start: float) -> float:
    """Seconds elapsed in the current step.

    Prefers the server's `stepSince`, recomputed fresh against wall-clock
    time on every call (never cached) so the number doesn't go stale
    between polls. Falls back to a locally-tracked start time if
    `stepSince` is missing, malformed (ValueError), or -- though bifrost
    should always emit an offset -- timezone-naive (TypeError, from
    subtracting it against an aware `now`). A naive timestamp is treated
    as unusable rather than silently assumed to be UTC, same as any other
    malformed input.
    """
    if step_since:
        try:
            started = parse_rfc3339(step_since)
            return (datetime.now(timezone.utc) - started).total_seconds()
        except (ValueError, TypeError):
            pass
    return time.time() - fallback_start


def wait_for_preview(
    tag: str,
    initial_phase: str,
    poll=None,
    sleep=None,
    is_tty: bool | None = None,
) -> dict:
    """Poll `tag` until it reaches ready/failed/terminating, rendering progress.

    On a TTY this redraws a single line with a spinner, the current step,
    and elapsed time computed from `stepSince`; piped/redirected output
    instead gets one plain line per step change, no `\\r`. Both degrade to
    today's phase-change-only output whenever a record has no `step` --
    either because the phase itself carries none (e.g. `ready`), or because
    the server predates step-narration entirely.

    `poll`, `sleep`, and `is_tty` are overridable so callers (tests) can
    drive this off canned records instead of the real API / a real
    terminal. Defaults are the real API, time.sleep, and sys.stdout.isatty().
    """
    poll = poll or (lambda: preview_api("GET", f"/api/previews/{tag}"))
    sleep = sleep or time.sleep
    if is_tty is None:
        is_tty = sys.stdout.isatty()

    deadline = time.time() + 30 * 60
    phase = initial_phase
    known_phases = {"creating", "ready", "failed", "terminating"}
    noted_unknown_phase = False

    current_step: str | None = None
    current_step_since: str | None = None
    current_step_start = time.time()
    tick = 0
    line_len = 0  # width of whatever's currently drawn on the TTY progress line

    def tty_write(text: str) -> None:
        nonlocal line_len
        sys.stdout.write("\r" + text + " " * max(0, line_len - len(text)))
        sys.stdout.flush()
        line_len = len(text)

    def tty_finish(text: str) -> None:
        nonlocal line_len
        sys.stdout.write("\r" + text + " " * max(0, line_len - len(text)) + "\n")
        sys.stdout.flush()
        line_len = 0

    def tty_clear() -> None:
        nonlocal line_len
        if line_len:
            sys.stdout.write("\r" + " " * line_len + "\r")
            sys.stdout.flush()
            line_len = 0

    while time.time() < deadline:
        sleep(3)
        rec = poll()
        new_phase = rec["phase"]
        step = rec.get("step")
        step_since = rec.get("stepSince")

        if step is None:
            # No step-level detail available -- an older bifrost that
            # predates this field, or a phase (like `ready`) that
            # legitimately carries none. Degrade to the original
            # phase-change-only behavior.
            tty_clear()
            current_step = None
            if new_phase != phase:
                print(f"  {new_phase}")
        else:
            if step != current_step:
                if current_step is not None and is_tty:
                    elapsed = step_elapsed_seconds(
                        current_step_since, current_step_start
                    )
                    tty_finish(f"  ✓ {current_step} — {format_elapsed(elapsed)}")
                current_step = step
                current_step_start = time.time()
                if not is_tty:
                    print(f"  {step}")
            current_step_since = step_since
            if is_tty:
                elapsed = step_elapsed_seconds(current_step_since, current_step_start)
                frame = spinner_frame(tick)
                tick += 1
                tty_write(f"  {frame} {step} — {format_elapsed(elapsed)}")

        phase = new_phase

        if new_phase == "ready":
            tty_clear()
            for app, url in sorted((rec.get("urls") or {}).items()):
                print(f"  {app}: {url}")
            return rec
        if new_phase == "failed":
            # Deliberate: unlike the `step is None` branch above, we don't
            # also print a bare "  failed" stdout line here. When step-level
            # detail exists, the richer "failed while <step>: <error>"
            # message below is strictly more useful and a generic phase
            # line would just be redundant noise ahead of it.
            tty_clear()
            err = rec.get("error")
            fail_step = rec.get("step")
            if fail_step and err:
                print(f"Preview {tag} failed while {fail_step}: {err}", file=sys.stderr)
            elif err:
                print(f"Preview {tag} failed: {err}", file=sys.stderr)
            else:
                print(f"Preview {tag} failed (phase: failed).", file=sys.stderr)
            print("Check the Previews tab in bifrost for details.", file=sys.stderr)
            sys.exit(1)
        if new_phase == "terminating":
            tty_clear()
            print(
                f"Preview {tag} is being torn down (concurrent `preview down`?).",
                file=sys.stderr,
            )
            sys.exit(1)
        if new_phase not in known_phases and not noted_unknown_phase:
            print(f"  (unrecognized phase {new_phase!r}; continuing to poll)")
            noted_unknown_phase = True

    tty_clear()
    print(f"Timed out waiting for {tag}; check `ib preview list`.", file=sys.stderr)
    sys.exit(1)


def warn_if_ttl_dropped(ttl: str | None, record: dict, tag: str) -> None:
    """Warn on stderr if a requested TTL didn't make it into the server's record.

    Go's json.Decoder ignores unknown request fields by default, and
    bifrost's handler doesn't set DisallowUnknownFields -- so a server that
    predates `ttl` support accepts the field, returns success, and creates
    a preview with no `expiresAt` at all. No error anywhere; the only place
    left to catch it is here, by checking whether the field the user asked
    for actually shows up on the record. Deliberately not an error: the
    preview really was created and is usable, just without the expiry that
    was requested, so this never raises SystemExit or changes the exit
    code.
    """
    if ttl is None or record.get("expiresAt"):
        return
    print(
        f"Warning: --ttl {ttl} was requested for {tag}, but the preview has "
        "no expiry and will NOT expire automatically. This bifrost may "
        "predate --ttl support and silently ignored it. Tear it down "
        f"manually when done: ib preview down {tag}",
        file=sys.stderr,
    )


def warn_if_auto_update_dropped(
    auto_update: bool, record: dict, tag: str, branch: str
) -> None:
    """Warn on stderr if a requested auto-update didn't make it into the server's record.

    Same failure mode as warn_if_ttl_dropped, and a sibling rather than a
    shared helper because the message content differs (what didn't take
    effect, and the consequence): Go's json.Decoder ignores unknown request
    fields by default, and bifrost's handler doesn't set
    DisallowUnknownFields -- so a server that predates `autoUpdate` support
    accepts the field, returns success, and creates a preview with no
    `autoUpdate` key at all. It's `omitempty` on the record, so absence
    means off, same as `.get()`'s default here. Deliberately not an error:
    the preview really was created and is usable, it just won't follow the
    branch on its own, so this never raises SystemExit or changes the exit
    code.
    """
    if not auto_update or record.get("autoUpdate"):
        return
    print(
        f"Warning: --auto-update was requested for {tag}, but the preview "
        "has no autoUpdate flag and will NOT follow the branch. This "
        "bifrost may predate --auto-update support and silently ignored "
        "it. Re-run manually to pick up new commits: "
        f"ib preview up {branch} --auto-update",
        file=sys.stderr,
    )


def preview_up(
    branch: str,
    wait: bool = True,
    ttl: str | None = None,
    auto_update: bool = False,
) -> None:
    body: dict = {"branch": branch}
    if ttl is not None:
        # Sent through verbatim whenever --ttl was given at all -- even an
        # explicit empty string. bifrost owns parsing/validation of the
        # duration string and its 400 error message is what the caller sees
        # on a bad value (see preview_api's error handling); a deliberately
        # empty value should get the same server-owned 400 as any other bad
        # value, not be silently treated the same as omitting --ttl.
        body["ttl"] = ttl
    if auto_update:
        # Only ever sent as `true` -- the contract wants the key entirely
        # absent when the flag isn't given (mirrors the record's own
        # `omitempty`), never an explicit `"autoUpdate": false`.
        body["autoUpdate"] = True
    created = preview_api("POST", "/api/previews", body)
    tag = created["tag"]
    print(f"Creating preview {tag} from {branch}...")
    if not wait:
        # No poll loop to piggyback a TTL/auto-update check on here, so
        # this does one extra GET instead of skipping verification -- a
        # flag silently dropped by an old server (see warn_if_ttl_dropped /
        # warn_if_auto_update_dropped) is exactly the kind of thing a
        # --no-wait/CI caller is least likely to notice on their own, and a
        # single request is cheap next to the POST that already just ran.
        record = preview_api("GET", f"/api/previews/{tag}")
        warn_if_ttl_dropped(ttl, record, tag)
        warn_if_auto_update_dropped(auto_update, record, tag, branch)
        print("Not waiting. Check with: ib preview list")
        return
    record = wait_for_preview(tag, created.get("phase", "creating"))
    warn_if_ttl_dropped(ttl, record, tag)
    warn_if_auto_update_dropped(auto_update, record, tag, branch)


USAGE_PREVIEW_UP = (
    "Usage: ib preview up <branch> [--ttl <duration>] [--no-wait] [--auto-update]"
)


def parse_up_args(args: list[str]) -> tuple[bool, str | None, bool, str]:
    """Parse the arguments after `ib preview up`. Returns (no_wait, ttl, auto_update, branch).

    Exits with a usage message unless what's left after pulling out
    `--no-wait`, `--auto-update`, and `--ttl <value>` reduces to exactly
    one token (the branch). That's deliberate, not just a missing-branch
    check: it's also what catches a leftover unrecognized token -- an
    `--ttl=8h` or `--auto-update=true` (this file doesn't parse the equals
    form) or any typo'd flag -- which would otherwise sit unconsumed in
    `args` and get silently dropped, leaving the flag the user asked for
    silently ignored (a TTL that never got set, or an auto-update that
    never got enabled).
    """
    no_wait = "--no-wait" in args
    args = [a for a in args if a != "--no-wait"]
    auto_update = "--auto-update" in args
    args = [a for a in args if a != "--auto-update"]
    ttl = None
    if "--ttl" in args:
        idx = args.index("--ttl")
        if idx + 1 >= len(args):
            print(USAGE_PREVIEW_UP)
            sys.exit(1)
        ttl = args[idx + 1]
        del args[idx : idx + 2]
    if len(args) != 1:
        print(USAGE_PREVIEW_UP)
        sys.exit(1)
    return no_wait, ttl, auto_update, args[0]


def preview_down(tag: str, yes: bool = False) -> None:
    if not yes:
        answer = input(f"Tear down preview {tag}? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return
    preview_api("DELETE", f"/api/previews/{tag}")
    print(f"Tearing down {tag}.")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "status":
        args = sys.argv[2:]
        quiet = "-q" in args or "--quiet" in args
        args = [a for a in args if a not in ("-q", "--quiet")]

        if args:
            validate_app(args[0])
            result = status(args[0], quiet=quiet)
            if result is False:
                sys.exit(1)
        else:
            results = [status(app, quiet=quiet) for app in SERVICES]
            if any(r is False for r in results):
                sys.exit(1)
    elif command == "promote":
        args = sys.argv[2:]
        yes = "-y" in args or "--yes" in args
        args = [a for a in args if a not in ("-y", "--yes")]
        if not args:
            print("Usage: ib promote <app> [-y/--yes]")
            sys.exit(1)
        validate_app(args[0])
        promote(args[0], yes=yes)
    elif command == "preview":
        if len(sys.argv) < 3:
            print("Usage: ib preview <list|up|down> ...")
            sys.exit(1)
        subcommand = sys.argv[2]
        args = sys.argv[3:]
        if subcommand == "list":
            preview_list()
        elif subcommand == "up":
            no_wait, ttl, auto_update, branch = parse_up_args(args)
            preview_up(branch, wait=not no_wait, ttl=ttl, auto_update=auto_update)
        elif subcommand == "down":
            yes = "-y" in args or "--yes" in args
            args = [a for a in args if a not in ("-y", "--yes")]
            if not args:
                print("Usage: ib preview down <tag> [-y/--yes]")
                sys.exit(1)
            preview_down(args[0], yes=yes)
        else:
            print(f"Unknown preview subcommand: {subcommand}")
            print("Available subcommands: list, up, down")
            sys.exit(1)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: status, promote, preview")
        sys.exit(1)


if __name__ == "__main__":
    main()
