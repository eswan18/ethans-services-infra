# Preview Build Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every previewable repo (footstrike-api, footstrike-dashboard, identity) can produce a preview image from any pushed branch via a manual Cloud Build trigger, without touching the staging/prod pipelines — and the dashboard becomes runtime-configurable so one env-agnostic preview image serves any preview environment.

**Architecture:** Each repo gets a `cloudbuild-preview.yaml` that tags images `preview-{SHORT_SHA}` (a format matching neither ImageUpdater `allowTags` pattern, so staging can never scoop a branch build). The dashboard drops its per-env build-arg baking for previews: a new `src/lib/appConfig.ts` reads `window.__APP_CONFIG__` (written at container start by an nginx `/docker-entrypoint.d/` script from `APP_*` env vars) and falls back to `import.meta.env.VITE_*`, so existing staging/prod images and local dev behave identically. Pulumi gains three manual-invocation triggers. No per-run substitutions anywhere — that's the point: Cloud Build's RunBuildTrigger API can't pass them.

**Tech Stack:** Cloud Build YAML, Docker (nginx:alpine entrypoint.d), Vite/React/TypeScript + Vitest (dashboard), Pulumi GCP (infra, Python).

**Multi-repo execution note:** Each task names its repo. Do the work on a branch named `preview-build-pipeline` in that repo (create it from up-to-date `main` the first time the repo appears; identity's `main` is push-protected and the others follow the same PR flow). Tasks 1–3 (dashboard) form one PR; Task 4 (api), Task 5 (identity), Task 6 (infra) are one PR each. Task 7 (spec update, bifrost) commits directly to bifrost main. Verification steps that run `gcloud builds triggers run` require the repo PRs to be merged first — they are marked accordingly.

**Design spec:** `~/Develop/ibormeith/bifrost/docs/superpowers/specs/2026-07-26-preview-environments-design.md` (sections "Builds", "Preview anatomy"). Task 7 updates the spec to match two decisions made during this plan: tag scheme `preview-{SHORT_SHA}` (was `preview-<tag>-<sha>` — the image is branch-content-addressed and env-agnostic, so the preview tag has no business in it) and runtime config replacing build-time substitutions (un-deferring what the spec had parked).

## Global Constraints

- Preview image tags are exactly `preview-$SHORT_SHA`. Never `latest`, never a bare SHA, never `{sha}-{env}` — staging ImageUpdater CRs auto-deploy tags matching `regexp:^[a-f0-9]{7,}$` (footstrike-api, identity) or `regexp:^[a-f0-9]+-staging$` (footstrike-dashboard) with `newest-build`, and a preview build must never match.
- Existing `cloudbuild.yaml` files and the push-to-main triggers are untouched.
- Registry: `us-central1-docker.pkg.dev/ethans-services/containers/{name}`.
- Dashboard: runtime config keys win over build-time values **per key**; with no `window.__APP_CONFIG__` (local dev, staging/prod images, node-env tests) behavior is byte-identical to today.
- Dashboard: no import-time `window` access from `src/lib` modules — the vitest `lib` project runs in a plain node environment (see `vite.config.ts` `test.projects`).
- Dashboard CI gates: `npm run lint && npm run format:check && npm run test && npm run build` all green; run `npm run format` before committing.
- Identity preview builds read the shared `:buildcache` registry cache but never write it (`--cache-from` only) — branch layers must not pollute the cache mainline builds rely on.

---

### Task 1: Dashboard runtime-config module (`appConfig.ts`)

**Repo:** `~/Develop/footstrike/footstrike-dashboard` (branch `preview-build-pipeline`)

**Files:**
- Create: `src/lib/appConfig.ts`
- Test: `src/lib/__tests__/appConfig.test.ts` (node-env vitest project — no jsdom)
- Modify: `src/lib/oauth/config.ts` (whole file, shown below)
- Modify: `src/lib/api/fetch.ts` (line ~184, the only `import.meta.env` use)

**Interfaces:**
- Produces: `apiUrl(): string`, `identityUrl(): string`, `oauthClientId(): string` from `@/lib/appConfig`, and the global type `Window.__APP_CONFIG__?: { apiUrl?: string; identityUrl?: string; oauthClientId?: string }`. Task 2's entrypoint script writes exactly those three camelCase keys.

- [ ] **Step 1: Write the failing test**

Create `src/lib/__tests__/appConfig.test.ts`:

```ts
import { apiUrl, identityUrl, oauthClientId } from "@/lib/appConfig";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("appConfig", () => {
  it("falls back to build-time env when no window exists (node env)", () => {
    expect(apiUrl()).toBe(import.meta.env.VITE_API_URL);
    expect(identityUrl()).toBe(import.meta.env.VITE_IDENTITY_URL);
    expect(oauthClientId()).toBe(import.meta.env.VITE_OAUTH_CLIENT_ID);
  });

  it("prefers window.__APP_CONFIG__ values when present", () => {
    vi.stubGlobal("window", {
      __APP_CONFIG__: {
        apiUrl: "https://footstrike-api-x.preview.footstrike.run",
        identityUrl: "https://identity-x.preview.footstrike.run",
        oauthClientId: "preview-client-id",
      },
    });
    expect(apiUrl()).toBe("https://footstrike-api-x.preview.footstrike.run");
    expect(identityUrl()).toBe("https://identity-x.preview.footstrike.run");
    expect(oauthClientId()).toBe("preview-client-id");
  });

  it("falls back per key when runtime config is partial", () => {
    vi.stubGlobal("window", {
      __APP_CONFIG__: { apiUrl: "https://footstrike-api-x.preview.footstrike.run" },
    });
    expect(apiUrl()).toBe("https://footstrike-api-x.preview.footstrike.run");
    expect(identityUrl()).toBe(import.meta.env.VITE_IDENTITY_URL);
    expect(oauthClientId()).toBe(import.meta.env.VITE_OAUTH_CLIENT_ID);
  });

  it("treats an empty runtime config object as all-fallback", () => {
    vi.stubGlobal("window", { __APP_CONFIG__: {} });
    expect(apiUrl()).toBe(import.meta.env.VITE_API_URL);
  });
});
```

(`describe`/`it`/`expect`/`vi`/`afterEach` are ambient — vitest `globals: true`; don't import them.)

- [ ] **Step 2: Run it to verify it fails**

Run: `npm run test -- src/lib/__tests__/appConfig.test.ts`
Expected: FAIL — cannot resolve `@/lib/appConfig`.

- [ ] **Step 3: Implement `src/lib/appConfig.ts`**

```ts
type AppConfig = {
  apiUrl?: string;
  identityUrl?: string;
  oauthClientId?: string;
};

declare global {
  interface Window {
    __APP_CONFIG__?: AppConfig;
  }
}

// Runtime config (config.js, written by the container entrypoint from APP_*
// env vars) wins over build-time Vite env, per key. Window access is
// call-time and guarded so node-env lib tests can import this module.
function runtime(): AppConfig {
  return typeof window === "undefined" ? {} : (window.__APP_CONFIG__ ?? {});
}

export function apiUrl(): string {
  return runtime().apiUrl ?? import.meta.env.VITE_API_URL;
}

export function identityUrl(): string {
  return runtime().identityUrl ?? import.meta.env.VITE_IDENTITY_URL;
}

export function oauthClientId(): string {
  return runtime().oauthClientId ?? import.meta.env.VITE_OAUTH_CLIENT_ID;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npm run test -- src/lib/__tests__/appConfig.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Rewire `src/lib/oauth/config.ts`**

Replace the whole file with (the endpoints become lazy getters — `identityUrl()` may read `window`, and the lib/api barrel transitively imports this module, so import-time evaluation would break node-env lib tests; this extends the existing `redirectUri` lazy pattern to every field):

```ts
import { identityUrl, oauthClientId } from "@/lib/appConfig";

// All endpoint fields are lazy getters: identityUrl() may read runtime
// config from `window`, and the lib/api barrel transitively imports this
// module, so import-time evaluation would make every importer require a
// DOM (breaking node-env lib tests).
export const OAUTH_CONFIG = {
  get authorizationEndpoint() {
    return `${identityUrl()}/oauth/authorize`;
  },
  get tokenEndpoint() {
    return `${identityUrl()}/oauth/token`;
  },
  get refreshEndpoint() {
    return `${identityUrl()}/oauth/refresh`;
  },
  // Fallback identity source when a token response doesn't carry an id_token.
  get userinfoEndpoint() {
    return `${identityUrl()}/oauth/userinfo`;
  },
  // RP-Initiated Logout 1.0 end_session_endpoint (identity's /oauth/logout).
  get endSessionEndpoint() {
    return `${identityUrl()}/oauth/logout`;
  },
  get clientId() {
    return oauthClientId();
  },
  // Lazy: computed when a request is built, not at module load.
  get redirectUri() {
    return `${window.location.origin}/oauth/callback`;
  },
  scope: "openid profile email",
};
```

- [ ] **Step 6: Rewire `src/lib/api/fetch.ts`**

Add `import { apiUrl } from "@/lib/appConfig";` to the imports, and change the single env read (~line 184):

```ts
  const url = new URL(`${apiUrl()}${path}`);
```

(There must be zero remaining `import.meta.env` references outside `src/lib/appConfig.ts` — check with `grep -rn "import\.meta\.env" src/ | grep -v appConfig | grep -v __tests__`.)

- [ ] **Step 7: Run the full gates**

Run: `npm run format && npm run lint && npm run test && npm run build`
Expected: all green. The oauth suite (dom-lib project) exercises the getters; any failure there means a getter regressed the config shape.

- [ ] **Step 8: Commit**

```bash
git add src/lib/appConfig.ts src/lib/__tests__/appConfig.test.ts src/lib/oauth/config.ts src/lib/api/fetch.ts
git commit -m "Read app config from runtime window.__APP_CONFIG__ with build-time fallback"
```

---

### Task 2: Dashboard `config.js` delivery (entrypoint + index.html)

**Repo:** `~/Develop/footstrike/footstrike-dashboard` (same branch)

**Files:**
- Create: `public/config.js`
- Create: `docker-entrypoint.d/90-app-config.sh`
- Modify: `index.html` (one line)
- Modify: `Dockerfile` (two lines)

**Interfaces:**
- Consumes: the `window.__APP_CONFIG__` shape from Task 1.
- Produces: the container contract Task 7 documents and plans 3–4 rely on — env vars `APP_API_URL`, `APP_IDENTITY_URL`, `APP_OAUTH_CLIENT_ID` set on the dashboard container materialize as `/config.js`; unset vars produce absent keys (per-key fallback).

- [ ] **Step 1: Create `public/config.js`**

```js
// Placeholder overwritten at container start by docker-entrypoint.d/90-app-config.sh.
// In local dev there is no runtime config; the app falls back to import.meta.env.
window.__APP_CONFIG__ = {};
```

(Vite copies `public/` into `dist/`, so the built site always has a real `/config.js` — no 404 in dev or in images run without env vars.)

- [ ] **Step 2: Load it in `index.html`**

Add one line to `<head>`, directly before `</head>` (after the fonts `<link>`/`<title>`; it must load before the module bundle):

```html
    <script src="/config.js"></script>
```

- [ ] **Step 3: Create `docker-entrypoint.d/90-app-config.sh`**

```sh
#!/bin/sh
# nginx:alpine's stock entrypoint runs /docker-entrypoint.d/*.sh before nginx
# starts. Write the SPA's runtime config from APP_* env vars; unset/empty vars
# are omitted so the app falls back to its build-time values per key.
# Values must not contain double quotes (they are URLs and client IDs).
set -eu
CONFIG=/usr/share/nginx/html/config.js
{
  echo "window.__APP_CONFIG__ = {"
  if [ -n "${APP_API_URL:-}" ]; then
    echo "  apiUrl: \"${APP_API_URL}\","
  fi
  if [ -n "${APP_IDENTITY_URL:-}" ]; then
    echo "  identityUrl: \"${APP_IDENTITY_URL}\","
  fi
  if [ -n "${APP_OAUTH_CLIENT_ID:-}" ]; then
    echo "  oauthClientId: \"${APP_OAUTH_CLIENT_ID}\","
  fi
  echo "};"
} > "$CONFIG"
```

- [ ] **Step 4: Wire it into the `Dockerfile`**

In the nginx stage, after the `COPY --from=builder /app/dist /usr/share/nginx/html` line, add:

```dockerfile
# Runtime config hook: stock nginx entrypoint runs this before starting
COPY docker-entrypoint.d/90-app-config.sh /docker-entrypoint.d/90-app-config.sh
RUN chmod +x /docker-entrypoint.d/90-app-config.sh
```

No `ENTRYPOINT`/`CMD` changes — the official image's entrypoint already runs `/docker-entrypoint.d/*.sh`. The existing `USER nginx` runs the script as nginx, and `/usr/share/nginx/html` is already `chown`ed to nginx, so the write succeeds.

- [ ] **Step 5: Verify with a real container** (requires Docker)

```bash
docker build -t dash-config-test .
docker run --rm -d --name dash-cfg -p 8081:80 \
  -e APP_API_URL=https://footstrike-api-x.preview.footstrike.run dash-config-test
curl -s localhost:8081/config.js
docker rm -f dash-cfg
docker run --rm -d --name dash-nocfg -p 8082:80 dash-config-test
curl -s localhost:8082/config.js
docker rm -f dash-nocfg
```

Expected: first curl shows `apiUrl: "https://footstrike-api-x.preview.footstrike.run",` and no other keys; second shows an empty `window.__APP_CONFIG__ = { };`-style object (no keys). Both containers must be healthy (nginx started ⇒ the script exited 0).

- [ ] **Step 6: Run the CI gates and commit**

Run: `npm run format:check && npm run lint && npm run test && npm run build`

```bash
git add public/config.js docker-entrypoint.d/90-app-config.sh index.html Dockerfile
git commit -m "Write runtime config.js from APP_* env vars at container start"
```

---

### Task 3: Dashboard `cloudbuild-preview.yaml`

**Repo:** `~/Develop/footstrike/footstrike-dashboard` (same branch; after this task, open the PR for Tasks 1–3)

**Files:**
- Create: `cloudbuild-preview.yaml`

**Interfaces:**
- Consumes: the env-agnostic image from Tasks 1–2.
- Produces: image `us-central1-docker.pkg.dev/ethans-services/containers/footstrike-dashboard:preview-$SHORT_SHA`, which Task 6's trigger builds and plan 3's bifrost resolves.

- [ ] **Step 1: Create `cloudbuild-preview.yaml`**

```yaml
options:
  logging: CLOUD_LOGGING_ONLY

# Preview images are environment-agnostic: no VITE_* build args — URLs come
# from runtime config (config.js) written at container start from APP_* env
# vars. The preview-{sha} tag deliberately matches neither ImageUpdater
# allowTags pattern (bare sha, or {sha}-staging), so staging never deploys
# a preview build.
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'us-central1-docker.pkg.dev/ethans-services/containers/footstrike-dashboard:preview-$SHORT_SHA'
      - '.'
images:
  - 'us-central1-docker.pkg.dev/ethans-services/containers/footstrike-dashboard:preview-$SHORT_SHA'
```

- [ ] **Step 2: Sanity-check and commit**

`npm run format:check` must still pass (Prettier checks tracked YAML). Then:

```bash
git add cloudbuild-preview.yaml
git commit -m "Add substitution-free preview build config"
git push -u origin preview-build-pipeline
gh pr create --title "Preview build pipeline: runtime config + preview builds" \
  --body "Runtime window.__APP_CONFIG__ (APP_* env vars via nginx entrypoint.d) with per-key import.meta.env fallback; env-agnostic cloudbuild-preview.yaml tagging preview-{sha}. Part of the preview-environments effort (spec in bifrost repo)."
```

(Trigger-run verification happens in Task 6, after merge.)

---

### Task 4: footstrike-api `cloudbuild-preview.yaml`

**Repo:** `~/Develop/footstrike/footstrike-api` (branch `preview-build-pipeline`)

**Files:**
- Create: `cloudbuild-preview.yaml`

**Interfaces:**
- Produces: image `...containers/footstrike-api:preview-$SHORT_SHA`.

- [ ] **Step 1: Create `cloudbuild-preview.yaml`**

```yaml
options:
  logging: CLOUD_LOGGING_ONLY

# The preview-{sha} tag deliberately fails the staging ImageUpdater
# allowTags regexp (^[a-f0-9]{7,}$), so preview builds never auto-deploy.
# Unlike cloudbuild.yaml there is no bare-sha tag and no --all-tags push.
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - 'build'
      - '-t'
      - 'us-central1-docker.pkg.dev/ethans-services/containers/footstrike-api:preview-$SHORT_SHA'
      - '.'
images:
  - 'us-central1-docker.pkg.dev/ethans-services/containers/footstrike-api:preview-$SHORT_SHA'
```

- [ ] **Step 2: Commit and open the PR**

```bash
git add cloudbuild-preview.yaml
git commit -m "Add preview build config (preview-{sha} tags, never bare sha)"
git push -u origin preview-build-pipeline
gh pr create --title "Add cloudbuild-preview.yaml" \
  --body "Manual-trigger preview builds tagging preview-{sha} so staging image-updater never picks them up. Part of the preview-environments effort (spec in bifrost repo)."
```

---

### Task 5: identity `cloudbuild-preview.yaml`

**Repo:** `~/Develop/ibormeith/identity` (branch `preview-build-pipeline`)

**Files:**
- Create: `cloudbuild-preview.yaml`

**Interfaces:**
- Produces: image `...containers/identity:preview-$SHORT_SHA`.

- [ ] **Step 1: Create `cloudbuild-preview.yaml`**

```yaml
steps:
  # Same buildx pattern as cloudbuild.yaml, but read-only on the shared
  # registry cache: --cache-from without --cache-to, so preview branches get
  # warm layers without polluting the cache mainline builds rely on. The
  # preview-{sha} tag fails the ImageUpdater allowTags regexp
  # (^[a-f0-9]{7,}$), so preview builds never auto-deploy to staging.
  - name: gcr.io/cloud-builders/docker
    entrypoint: bash
    args:
      - -c
      - |
        docker buildx create --use --driver docker-container
        docker buildx build \
          --cache-from type=registry,ref=us-central1-docker.pkg.dev/ethans-services/containers/identity:buildcache \
          -t us-central1-docker.pkg.dev/ethans-services/containers/identity:preview-$SHORT_SHA \
          --push \
          .

options:
  logging: CLOUD_LOGGING_ONLY
```

- [ ] **Step 2: Commit and open the PR**

```bash
git add cloudbuild-preview.yaml
git commit -m "Add preview build config (cache-from only, preview-{sha} tags)"
git push -u origin preview-build-pipeline
gh pr create --title "Add cloudbuild-preview.yaml" \
  --body "Manual-trigger preview builds: buildx with read-only registry cache, preview-{sha} tags that image-updater ignores. Part of the preview-environments effort (spec in bifrost repo)."
```

---

### Task 6: Pulumi preview triggers (+ live verification)

**Repo:** `~/Develop/ibormeith/infra`
**Prerequisite:** PRs from Tasks 3, 4, 5 are merged (the triggers read `cloudbuild-preview.yaml` from each repo's `main`).

**Files:**
- Modify: `__main__.py` (after the existing trigger block that ends with `bifrost_build`, ~line 750)

**Interfaces:**
- Consumes: `cloudbuild-preview.yaml` on each repo's main.
- Produces: manual triggers named `{repo}-preview-build`, run as `gcloud builds triggers run {repo}-preview-build --branch=<branch>` — the invocation contract plan 3's bifrost uses via the API.

- [ ] **Step 1: Add the triggers**

Append after the existing Cloud Build trigger definitions:

```python
# Preview builds: manual-invocation triggers (no push event). Run with
#   gcloud builds triggers run {repo}-preview-build --branch=<branch>
# The build config is pinned to main's cloudbuild-preview.yaml; the build
# *source* is whatever branch the run names. Note RunBuildTrigger accepts
# no substitutions — preview builds are deliberately substitution-free.
for preview_repo in ["footstrike-api", "footstrike-dashboard", "identity"]:
    cloudbuild.Trigger(
        f"{preview_repo}-preview-build",
        name=f"{preview_repo}-preview-build",
        project=project,
        service_account=cloud_build_sa,
        source_to_build=cloudbuild.TriggerSourceToBuildArgs(
            uri=f"https://github.com/{github_owner}/{preview_repo}",
            ref="refs/heads/main",
            repo_type="GITHUB",
        ),
        git_file_source=cloudbuild.TriggerGitFileSourceArgs(
            path="cloudbuild-preview.yaml",
            uri=f"https://github.com/{github_owner}/{preview_repo}",
            revision="refs/heads/main",
            repo_type="GITHUB",
        ),
    )
```

(Pinning `git_file_source` to main is deliberate: a feature branch can change its Dockerfile freely — the build context is the branch — but the build *pipeline* definition stays main's. If the Pulumi provider rejects this arg shape for 1st-gen GitHub-connected repos, the fallback is `gcloud builds triggers create manual` with the same fields and a `pulumi import`; note it in the PR if taken.)

- [ ] **Step 2: Preview and apply**

Run from `infra/`: `uv run pulumi preview` — expect exactly 3 new resources, zero changes to existing ones. Then `uv run pulumi up --yes`.

- [ ] **Step 3: Live verification — build one preview image per repo**

```bash
for repo in footstrike-api footstrike-dashboard identity; do
  gcloud builds triggers run "${repo}-preview-build" --branch=main --project=ethans-services
done
# wait for the three builds, then:
for repo in footstrike-api footstrike-dashboard identity; do
  gcloud artifacts docker tags list \
    "us-central1-docker.pkg.dev/ethans-services/containers/${repo}" \
    --filter='tag~preview-' 2>/dev/null | head -3
done
```

Expected: each repo shows one `preview-<sha>` tag.

- [ ] **Step 4: Verify staging did NOT pick up the preview builds**

```bash
cd ~/Develop/ibormeith/infra && uv run python ib.py status footstrike-api
uv run python ib.py status footstrike-dashboard
uv run python ib.py status identity
```

Expected: staging tags are unchanged (bare sha / `{sha}-staging` — not `preview-*`). This is the load-bearing check for the whole plan: if any staging namespace now runs a `preview-*` image, the tag scheme failed and the preview images must be deleted from the registry while diagnosing.

- [ ] **Step 5: Commit and PR (or direct push if infra main is unprotected)**

```bash
git checkout -b preview-build-pipeline
git add __main__.py
git commit -m "Add manual preview-build triggers for previewable repos"
git push -u origin preview-build-pipeline
gh pr create --title "Add preview-build triggers" \
  --body "Manual Cloud Build triggers ({repo}-preview-build) running cloudbuild-preview.yaml against arbitrary branches. Verified: preview-{sha} tags land in Artifact Registry and staging image-updater ignores them."
```

---

### Task 7: Update the design spec

**Repo:** `~/Develop/ibormeith/bifrost` (commit to `main` — docs only, main is unprotected)

**Files:**
- Modify: `docs/superpowers/specs/2026-07-26-preview-environments-design.md`

- [ ] **Step 1: Amend the Builds section and out-of-scope list**

Three edits:
1. In the "Builds" section: replace the `preview-<tag>-<sha>` tag scheme with `preview-{SHORT_SHA}`, and replace the sentence about substitutions carrying preview URLs with: the dashboard preview image is env-agnostic; per-preview URLs are supplied at deploy time as `APP_API_URL` / `APP_IDENTITY_URL` / `APP_OAUTH_CLIENT_ID` env vars on the container, materialized as `/config.js` by the nginx entrypoint (runtime config with per-key fallback to build-time values).
2. In the control-plane "Creation flow": step 2 no longer mentions substitutions — bifrost runs the `{name}-preview-build` trigger against the branch (RunBuildTrigger API, no substitutions) and sets the `APP_*` env vars in the preview overlay instead.
3. In "Deliberately not doing": remove the "dashboard runtime config injection" bullet (it shipped in this plan) and add a line noting the `{sha}-{env}` dual staging/prod dashboard builds could later collapse onto runtime config — still deferred.

- [ ] **Step 2: Commit and push**

```bash
git add docs/superpowers/specs/2026-07-26-preview-environments-design.md
git commit -m "Spec: preview-{sha} tags and runtime dashboard config (shipped in build-pipeline plan)"
git push
```

---

## Self-review notes

- **Spec coverage:** implements the spec's "Builds" section fully; deviations (tag scheme, runtime config replacing substitutions) are deliberate, decided with the owner on 2026-07-26, and Task 7 folds them back into the spec.
- **Sequencing:** Tasks 1–3 → one dashboard PR; 4 and 5 independent single-file PRs; 6 requires 3–5 merged; 7 last.
- **Untouched on purpose:** existing `cloudbuild.yaml`s, push triggers, ImageUpdater CRs, k8s manifests (preview overlays are plan 3/4), staging/prod dashboard builds (still `{sha}-{env}` with baked env — the runtime-config fallback keeps them working unchanged).
- **Known risk, accepted:** the Pulumi arg shape for manual triggers on 1st-gen GitHub connections is the one thing not verifiable offline; Task 6 Step 1 carries the fallback path.
