# Preview CLI + First End-to-End Preview (Plan 4b) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the preview-environments effort: unblock dashboard-only previews (CORS), give the terminal `ib preview up/down/list`, update the runbook, and create + verify + tear down the first real preview environment end to end.

**Architecture:** `ib preview` is a thin client of bifrost's already-shipped API — no new logic, no new dependencies (stdlib `urllib.request`, matching ib.py's hand-rolled argv style and stdlib-only imports). Bearer token read from Secret Manager via `gcloud` at call time (never stored on disk). `up` polls `GET /api/previews/{tag}` until phase leaves `creating`, because the API's 202 is deliberately non-authoritative (coalescing semantics, documented in 3c).

**Tech Stack:** Python 3 stdlib (infra repo, `ib.py`), gcloud CLI, kubectl (smoke verification), real GKE/Neon/Cloud Build infrastructure.

**Repos:** footstrike-api (Task 1, branch `preview-cors` → PR), infra (Tasks 2–3, branch `preview-cli` → PR), ibormeith/.claude + bifrost spec (Task 3, direct commits), no repo (Task 4 — imperative smoke).

## Global Constraints

- `ib.py` is stdlib-only with hand-rolled `sys.argv` parsing and a module docstring that IS the help text — match that style exactly; no argparse, no `requests`, no new deps in `pyproject.toml`.
- The bearer token comes from `gcloud secrets versions access latest --secret=bifrost_prod_preview_api_token`; never printed, never written to a file, never placed in a URL or argv (Authorization header only).
- Bifrost prod base URL `https://bifrost.ethanswan.com`, overridable via `BIFROST_URL` env var. It sits behind Cloudflare Tunnel and is publicly reachable; preview hostnames themselves are tailnet-only.
- API contract facts (from 3b/3c, binding): `GET /api/previews` → `{"previews":[...]}`; `GET /api/previews/{tag}` → a record or 404 `{"error":...}`; `POST /api/previews {"branch"}` → 202 `{"tag","phase"}`; `DELETE /api/previews/{tag}` → 202; 409 = busy; 503 = preview config absent; non-2xx bodies are JSON; a trailing slash yields a plain-text 404 (never build URLs with one); send canonical `Bearer` casing.
- Task 4 mutates real infrastructure and costs real build minutes; it ends by tearing the preview down.

---

### Task 1: Unblock dashboard-only previews (footstrike-api CORS)

**Repo:** `~/Develop/footstrike/footstrike-api`, branch `preview-cors` from up-to-date main; PR at the end.

**Why:** `envConfigFor` points a dashboard-only preview's `APP_API_URL` at `https://api.staging.footstrike.run`. Staging's CORS allowlist is `PUBLIC_DASHBOARD_BASE_URL` + local dev + `EXTRA_CORS_ORIGINS` (unset today), so every XHR from a preview dashboard is blocked while login still appears to work — a confusing first smoke. Two-member previews are unaffected (their `APP_API_URL` is their own preview API, whose `PUBLIC_DASHBOARD_BASE_URL` is the preview dashboard).

**Files:**
- Modify: `k8s/staging/configmap-env.yaml`
- Read first: `footstrike/app/app.py` (the CORS middleware — confirm how `EXTRA_CORS_ORIGINS` is parsed before choosing the value's shape)

- [ ] **Step 1: Read the CORS setup.** In `footstrike/app/app.py`, find the CORSMiddleware construction (~line 181). Confirm: `EXTRA_CORS_ORIGINS` is a comma-separated exact-origin list appended to the defaults, and whether `allow_origin_regex` is already passed. Record what you find in your report — the next step's choice depends on it.

- [ ] **Step 2: Add preview origins.** Preview dashboard origins are dynamic (`https://footstrike-dashboard-<tag>.preview.footstrike.run`), so an exact list can't cover them.
  - **If** the middleware already accepts `allow_origin_regex` from config (or trivially can via an existing env var): prefer that, with `https://[a-z0-9-]+\.preview\.footstrike\.run` — one line, covers every future preview.
  - **Else** (exact-list only): add to `k8s/staging/configmap-env.yaml` an `EXTRA_CORS_ORIGINS` entry and, in the same PR, extend `app.py` to also read `CORS_ORIGIN_REGEX` (optional, empty disables) and pass it as `allow_origin_regex` — following the app's existing config conventions (`footstrike/config/`), with a unit test asserting a preview origin is allowed and an unrelated origin is not.
  Whichever path: staging only. Do NOT touch `k8s/prod/` — prod previews are out of scope by design.

- [ ] **Step 3: Gates + PR.** `make lint && make ty && make test` (unit tests need `JWT_ISSUER` set — see the repo's CLAUDE.md). Then commit, push, and open the PR titled "Allow preview-environment origins in staging CORS", body explaining the dashboard-only-preview case, ending after a blank line with: `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

---

### Task 2: `ib preview up/down/list`

**Repo:** `~/Develop/ibormeith/infra`, branch `preview-cli` from up-to-date main.

**Files:**
- Modify: `ib.py` (docstring, new functions, `main()` dispatch)

**Interfaces produced (the terminal UX):**

```
ib preview list                  # table: TAG  BRANCH  PHASE  HEALTH  AGE  APPS
ib preview up <branch>           # create/update, poll to ready, print URLs
ib preview up <branch> --no-wait # fire and return the tag
ib preview down <tag>            # tear down (confirm unless -y/--yes)
```

- [ ] **Step 1: Helpers.** Add near the existing `run()`:

```python
BIFROST_URL = os.environ.get("BIFROST_URL", "https://bifrost.ethanswan.com")
PREVIEW_TOKEN_SECRET = "bifrost_prod_preview_api_token"


def preview_token() -> str:
    """Fetch the preview API bearer token from Secret Manager."""
    return run([
        "gcloud", "secrets", "versions", "access", "latest",
        f"--secret={PREVIEW_TOKEN_SECRET}",
    ])


def preview_api(method: str, path: str, body: dict | None = None) -> dict:
    """Call bifrost's preview API. Exits with a clear message on failure."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{BIFROST_URL}{path}", data=data, method=method,
        headers={
            "Authorization": f"Bearer {preview_token()}",
            "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("error", "")
        except Exception:
            pass
        if e.code == 503:
            print("Preview API unavailable — bifrost has no preview config.", file=sys.stderr)
        elif e.code == 409:
            print("That preview is busy — another up/down is in flight.", file=sys.stderr)
        elif e.code == 401:
            print("Unauthorized — check the preview API token.", file=sys.stderr)
        else:
            print(f"Preview API error {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"Cannot reach bifrost at {BIFROST_URL}: {e.reason}", file=sys.stderr)
        sys.exit(1)
```

Add `import os`, `import time`, `import urllib.error`, `import urllib.request` to the existing import block (keep the file's existing import ordering style).

**Note on `run()`:** it exits the process on non-zero return, which is the right behavior for a missing/denied gcloud secret — no special handling needed.

- [ ] **Step 2: Commands.**

```python
def preview_list() -> None:
    previews = preview_api("GET", "/api/previews").get("previews") or []
    if not previews:
        print("No preview environments.")
        return
    print(f"{'TAG':<24} {'BRANCH':<24} {'PHASE':<10} {'HEALTH':<12} APPS")
    for p in previews:
        apps = ",".join(p.get("apps") or [])
        print(f"{p['tag']:<24} {p['branch']:<24} {p['phase']:<10} {p['health']:<12} {apps}")


def preview_up(branch: str, wait: bool = True) -> None:
    created = preview_api("POST", "/api/previews", {"branch": branch})
    tag = created["tag"]
    print(f"Creating preview {tag} from {branch}...")
    if not wait:
        print(f"Not waiting. Check with: ib preview list")
        return
    deadline = time.time() + 30 * 60
    phase = created.get("phase", "creating")
    while time.time() < deadline:
        time.sleep(10)
        rec = preview_api("GET", f"/api/previews/{tag}")
        if rec["phase"] != phase:
            phase = rec["phase"]
            print(f"  {phase}")
        if phase == "ready":
            for app, url in sorted((rec.get("urls") or {}).items()):
                print(f"  {app}: {url}")
            return
        if phase == "failed":
            print(f"Preview {tag} failed: {rec.get('error', '(no detail)')}", file=sys.stderr)
            sys.exit(1)
    print(f"Timed out waiting for {tag}; check `ib preview list`.", file=sys.stderr)
    sys.exit(1)


def preview_down(tag: str, yes: bool = False) -> None:
    if not yes:
        answer = input(f"Tear down preview {tag}? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return
    preview_api("DELETE", f"/api/previews/{tag}")
    print(f"Tearing down {tag}.")
```

**Adaptation note:** the record's error field is whatever 3b's `previewRecord` exposes — check `internal/web/previews.go`'s struct tags in the merged bifrost main before writing `rec.get('error')`; if the JSON has no error field, print the phase and point at the Previews tab instead. Record what you found in your report.

- [ ] **Step 3: Dispatch + docstring.** Add a `preview` branch to `main()`'s `if/elif` chain in the file's existing style (manual flag stripping like `promote`'s `-y/--yes`; subcommand in `sys.argv[2]`, argument in `sys.argv[3]`; usage message on missing args). Extend the module docstring's Usage and Examples sections with the four new invocations — it is the CLI's only help text.

- [ ] **Step 4: Verify against the live API.** `uv run python ib.py preview list` — expect the empty-state line (no previews exist yet) and a clean exit 0. Then a negative check: `BIFROST_URL=https://bifrost.ethanswan.com uv run python ib.py preview down nonexistent-tag -y` — expect the API's 404 surfaced as a clear message and exit 1, no traceback. Paste both outputs in your report.

- [ ] **Step 5: Commit + PR.** Commit `ib.py`, push, open a PR titled "Add ib preview up/down/list" with a body showing the four usages, ending after a blank line with the attribution line.

---

### Task 3: Runbook + spec close-out

**Repos:** `~/Develop/ibormeith` (`.claude/CLAUDE.md` — direct commit; the folder is not a repo, so commit in whichever repo tracks it — check `git -C ~/Develop/ibormeith/.claude rev-parse --show-toplevel`; if untracked, edit in place and note that in the report) and `~/Develop/ibormeith/bifrost` (spec; direct commit to main, docs-only).

- [ ] **Step 1: Runbook.** In `~/Develop/ibormeith/.claude/CLAUDE.md`, add a "Preview environments" section after the "Deploy workflow" section: what a preview is (ephemeral namespace `preview-<tag>` per branch, apps whose repos carry that branch, overlaid on shared staging); the three commands; where it runs (bifrost prod orchestrates; `*.preview.footstrike.run`, tailnet-only); the moving parts (per-repo `cloudbuild-preview.yaml` + manual `{repo}-preview-build` triggers, Neon branch per stateful app, wildcard cert copied from the `previews` namespace, wildcard OAuth redirect on the staging dashboard client); and the two things that bite: preview builds are manual-only (nothing auto-fires on push/PR), and a stuck `creating` phase means re-running `up` (the recovery path). Keep the file's terse, factual voice.

- [ ] **Step 2: Spec status.** In `bifrost/docs/superpowers/specs/2026-07-26-preview-environments-design.md`, update the Status line to record that the design shipped across plans 1–4 (identity wildcard redirects, build pipeline, control plane 3a/3b/3c, provisioning + CLI), with the date. Do not restructure the rest.

- [ ] **Step 3: Commit both.**

---

### Task 4: First end-to-end preview (imperative; real infrastructure)

**Prereq:** Tasks 1–2's PRs merged; bifrost prod running the 3c image (`ib status bifrost` shows prod on the post-merge SHA — if not, `ib promote bifrost` first and say so in the report).

This task creates a real preview, verifies it, and tears it down. It pushes two throwaway branches and deletes them afterward.

- [ ] **Step 1: Create matching branches.** In `~/Develop/footstrike/footstrike-api` and `~/Develop/footstrike/footstrike-dashboard`, create branch `preview-smoke` from up-to-date main with one trivial, obviously-temporary commit each (e.g. a comment line in the README noting the smoke test). Push both. Do NOT open PRs.

- [ ] **Step 2: Create the preview.** `cd ~/Develop/ibormeith/infra && uv run python ib.py preview up preview-smoke`. Expected: `Creating preview preview-smoke...`, phase transitions, then two URLs. Builds dominate the runtime (several minutes each, run serially). If it fails, capture the phase/error and STOP — report BLOCKED with the failure and `kubectl get events -n preview-preview-smoke --sort-by=.lastTimestamp | tail -20`.

- [ ] **Step 3: Verify the environment.**
  - `uv run python ib.py preview list` — one row, phase `ready`.
  - `kubectl get all,ingress,secret,cm -n preview-preview-smoke` — deployments 1/1, the copied `*-preview-secrets`, the wildcard TLS secret, the generated `*-preview-env` configmap, two ingresses; CronJob (if present) shows SUSPEND=True.
  - `kubectl get deploy -n preview-preview-smoke -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.template.spec.containers[0].image}{"\n"}{end}'` — both images are `preview-<sha>` tags (NOT `latest`/`prod`/`{sha}-staging`).
  - `kubectl get ns preview-preview-smoke -o jsonpath='{.metadata.annotations}'` — branch/apps/phase annotations as expected.
  - From the tailnet: `curl -sS -o /dev/null -w '%{http_code}\n' https://footstrike-api-preview-smoke.preview.footstrike.run/health` → 200, and the same for the dashboard's `/index.html`. (If this machine isn't on the tailnet, say so and skip these two with a note — the in-cluster checks above still stand.)
  - **Staging untouched:** `uv run python ib.py status footstrike-api` and `... footstrike-dashboard` — staging tags unchanged, no `preview-*` anywhere.
  - Neon: confirm a `preview-preview-smoke` branch exists in the footstrike-api project (`aged-river-81935268`) — via the Neon API with the key from Secret Manager (`gcloud secrets versions access latest --secret=bifrost_prod_neon_api_key`), never printing the key.

- [ ] **Step 4: Browser check (optional, only if on the tailnet).** Open the dashboard preview URL; confirm it loads and the OAuth redirect reaches identity (the wildcard redirect URI is registered). Full login only works if you have staging credentials handy; a successful redirect to the identity login page is sufficient evidence. Capture what you observed.

- [ ] **Step 5: Tear down + verify.** `uv run python ib.py preview down preview-smoke -y`, then after ~30s: namespace gone (`kubectl get ns preview-preview-smoke` → NotFound), `ib preview list` empty, and the Neon branch deleted. Delete both remote `preview-smoke` branches (`git push origin --delete preview-smoke` in each repo) and the local ones.

- [ ] **Step 6: Report.** Timings per phase, every verification's actual output, anything surprising. This report is the effort's acceptance evidence.

---

## Self-review notes

- **Ordering:** 1 and 2 are independent (different repos) and can run in parallel; 3 is docs-only anytime; 4 needs 1+2 merged and bifrost prod promoted.
- **Why CORS is Task 1, not part of the smoke:** the smoke uses a two-member preview (api + dashboard) which doesn't hit the CORS gap — but a dashboard-only preview is the more common day-to-day shape, and shipping the CLI without it would hand the user a broken first solo-dashboard preview.
- **Adaptation points named:** the api's CORS middleware shape (Task 1 Step 1), `previewRecord`'s error field (Task 2 Step 2), the `.claude` folder's repo membership (Task 3), tailnet availability (Task 4).
- **Not doing:** UI create/teardown buttons (the Previews tab stays read-only — CLI-first per spec), auto-teardown/TTL, prod-flavored previews, per-PR automation.
