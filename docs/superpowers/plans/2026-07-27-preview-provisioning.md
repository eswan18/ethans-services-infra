# Preview Provisioning (Plan 4a) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up everything the preview control plane needs outside bifrost's own code: the shared `previews` namespace with the wildcard TLS certificate, Secret Manager containers + IAM for bifrost's three preview tokens, redirect-URI breadth validation in identity-cli, and the wildcard redirect registration on the staging dashboard client. Runs in parallel with the bifrost 3b/3c track — zero file overlap with it.

**Architecture:** Pulumi already manages cluster-shared k8s resources (ingress-nginx Helm release, `letsencrypt-dns01` ClusterIssuer as a `k8s.apiextensions.CustomResource`) — the `previews` Namespace and the wildcard `Certificate` follow that exact precedent. One shared wildcard cert (not per-preview Certificates: Let's Encrypt's duplicate-certificate limit is 5/week for an identical dnsNames set; 3c's orchestrator copies the secret into each preview namespace, same as it copies app secrets). Secrets follow the `{name}_{env}_{secret}` convention with `bifrost_prod_*` names. identity-cli gains structural validation for wildcard redirect entries only (non-wildcard URIs stay unvalidated — existing clients have localhost/http dev entries that must not break).

**Tech Stack:** Pulumi (Python, infra repo), gcloud CLI, cert-manager/Cloudflare DNS-01, Go (identity repo, cobra CLI), identity-cli against the staging Neon DB.

**Repos/branches:** infra → branch `preview-provisioning` (this plan doc + Task 1; one PR). identity → branch `wildcard-redirect-validation` (Task 3; one PR). Tasks 2 and 4 are imperative (no commits beyond what 1 and 3 created).

**User-action checkpoints (cannot be done by agents):**
- Cloudflare dashboard: wildcard CNAME (Task 2, step 3 — exact record given there).
- Provide the fine-grained GitHub PAT and Neon API key values (Task 2, step 4).

## Global Constraints

- Secret names exactly: `bifrost_prod_github_token`, `bifrost_prod_neon_api_key`, `bifrost_prod_preview_api_token`. Prod-bifrost only — staging bifrost never orchestrates previews.
- Shared namespace name exactly `previews`; certificate + secret name exactly `preview-footstrike-run-tls`; dnsNames exactly `["*.preview.footstrike.run"]`; issuer `letsencrypt-dns01` (ClusterIssuer — already exists, do not create another).
- `pulumi preview` before `pulumi up`, and the preview must show ONLY creations (no changes/deletes to existing resources).
- identity-cli validation applies ONLY to entries containing `*`: must parse as a URL, scheme `https`, host exactly `*.` + a suffix containing ≥ 2 dots, exactly one `*` total, non-empty path, no query/fragment. Non-wildcard entries pass through untouched.
- identity repo gates: `make test && make lint` (golangci-lint runs in identity CI? identity CI = GitHub Actions lint/test — run `make lint` plus `go vet ./...`; if the repo has golangci config in CI, match it).
- Never print secret values in reports or command output (gcloud reads from stdin/files).

---

### Task 1: Pulumi — previews namespace, wildcard Certificate, bifrost preview secrets + IAM

**Repo:** `~/Develop/ibormeith/infra` (worktree branch `preview-provisioning` — the plan doc is already its first commit)

**Files:**
- Modify: `__main__.py`

**Interfaces:**
- Produces: k8s Namespace `previews`; Certificate/Secret `preview-footstrike-run-tls` in `previews` (3c copies this secret into each preview namespace); the three `bifrost_prod_*` Secret Manager containers with accessor IAM for the existing bifrost-prod SA (3b's deployment wiring consumes them).

- [ ] **Step 1: Add the k8s resources**

Next to the existing cert-manager/ingress-nginx block (after `letsencrypt_dns01_issuer`), following the SAME `opts` pattern (provider/depends_on) used by `letsencrypt_dns01_issuer` and `cloudflare_dns_token_secret` in this file — mirror it exactly, including `depends_on` on the cert-manager release for the Certificate:

```python
# Preview environments: shared namespace holding the wildcard certificate.
# One cert (not per-preview) — Let's Encrypt's duplicate-certificate limit
# (5/week per identical name set) would throttle preview creation otherwise.
# Bifrost copies the secret into each preview namespace at creation time.
previews_namespace = k8s.core.v1.Namespace(
    "previews",
    metadata={"name": "previews"},
)

preview_wildcard_cert = k8s.apiextensions.CustomResource(
    "preview-wildcard-cert",
    api_version="cert-manager.io/v1",
    kind="Certificate",
    metadata={"name": "preview-footstrike-run-tls", "namespace": "previews"},
    spec={
        "secretName": "preview-footstrike-run-tls",
        "issuerRef": {"name": "letsencrypt-dns01", "kind": "ClusterIssuer"},
        "dnsNames": ["*.preview.footstrike.run"],
    },
)
```

(If the neighboring k8s resources pass an explicit `opts=pulumi.ResourceOptions(...)`, replicate it on both resources and add `depends_on=[previews_namespace]` to the Certificate; DNS-01 issuance needs no DNS CNAME to exist — the ACME solver writes its own TXT records via the Cloudflare token.)

- [ ] **Step 2: Add the secrets + IAM**

Append to the `secret_names` list (in the bifrost section):

```python
    "bifrost_prod_github_token",
    "bifrost_prod_neon_api_key",
    "bifrost_prod_preview_api_token",
```

Extend the existing `"bifrost-prod"` entry's secret list in `secret_access` with the same three names.

- [ ] **Step 3: Verify the plan**

Run from the worktree: `uv run pulumi preview --stack prod 2>&1 | tail -15`
Expected: exactly 2 k8s resources + 3 secrets + 3 IAM members to create (8 creates), everything else unchanged. If ANY existing resource shows a change/delete: STOP and report BLOCKED with the preview output.

- [ ] **Step 4: Commit, push, PR**

```bash
git add __main__.py
git commit -m "Add preview provisioning: previews namespace, wildcard cert, bifrost preview secrets"
git push -u origin preview-provisioning
gh pr create --repo eswan18/ethans-services-infra --title "Preview provisioning: namespace, wildcard cert, bifrost secrets" \
  --body "Shared previews namespace + *.preview.footstrike.run wildcard Certificate (letsencrypt-dns01), plus Secret Manager containers and IAM for bifrost's three preview tokens. Track B of the preview-environments effort.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

(Do NOT run `pulumi up` — that's Task 2, after the PR merges.)

---

### Task 2: Apply, set values, DNS, verify cert (imperative; requires Task 1's PR merged)

**Prereqs gathered from the user first:** the GitHub PAT (fine-grained, Contents read-only on footstrike-api/footstrike-dashboard/identity) and the Neon API key. Do not start until both exist.

- [ ] **Step 1: Apply**

From an infra checkout at merged main: `uv run pulumi preview --stack prod` (re-confirm 8 creates, nothing else) then `uv run pulumi up --stack prod --yes`.

- [ ] **Step 2: Set the secret values**

The PAT and Neon key come from the user; the bearer token is generated. The user should run these themselves (values never enter the transcript):

```bash
# user pastes PAT / Neon key when prompted by read:
read -s PAT && echo -n "$PAT" | gcloud secrets versions add bifrost_prod_github_token --data-file=- && unset PAT
read -s NK && echo -n "$NK" | gcloud secrets versions add bifrost_prod_neon_api_key --data-file=- && unset NK
python3 -c "import secrets; print(secrets.token_urlsafe(32), end='')" | gcloud secrets versions add bifrost_prod_preview_api_token --data-file=-
```

Verify each has a version: `for s in bifrost_prod_github_token bifrost_prod_neon_api_key bifrost_prod_preview_api_token; do gcloud secrets versions list $s --limit=1 --format='value(name)'; done`

- [ ] **Step 3: USER — Cloudflare DNS record**

In the Cloudflare dashboard, zone `footstrike.run`, add: **CNAME, name `*.preview`, target `staging-ingress.tailc06f30.ts.net`, DNS-only (grey cloud)** — same shape as the existing `staging` / `api.staging` records.

- [ ] **Step 4: Verify the certificate issued**

```bash
kubectl get certificate -n previews preview-footstrike-run-tls
kubectl get secret -n previews preview-footstrike-run-tls -o jsonpath='{.type}'
```

Expected: `READY True` (DNS-01 takes a minute or two) and `kubernetes.io/tls`. If stuck in pending: `kubectl describe certificaterequest -n previews` and report the challenge status — do not delete/retry blindly.

- [ ] **Step 5: Verify DNS (after the user confirms Step 3)**

`dig +short x.preview.footstrike.run` — expected: CNAME chain to `staging-ingress.tailc06f30.ts.net` (routable only from the tailnet; resolution alone proves the record).

---

### Task 3: identity-cli wildcard redirect breadth validation

**Repo:** `~/Develop/ibormeith/identity` (branch `wildcard-redirect-validation` from up-to-date main; PR at the end — identity main is push-protected)

**Files:**
- Create: `cmd/identity-cli/internal/validate.go`
- Test: `cmd/identity-cli/internal/validate_test.go`
- Modify: `cmd/identity-cli/cmd/client_update.go` (before the `UpdateOAuthClient` call, ~line 124)
- Modify: `cmd/identity-cli/cmd/client_create.go` (before `CreateOAuthClientParams` assembly, ~line 82)

**Interfaces:**
- Produces: `func ValidateRedirectURIs(uris []string) error` in `cmd/identity-cli/internal` — called with the FULL final list in both create and update paths (append path included: validate `params.RedirectUris` after assembly).

- [ ] **Step 1: Failing tests** (`cmd/identity-cli/internal/validate_test.go`):

```go
package internal

import "testing"

func TestValidateRedirectURIs(t *testing.T) {
	cases := []struct {
		name    string
		uris    []string
		wantErr bool
	}{
		{"non-wildcard URIs pass untouched", []string{"http://localhost:5173/oauth/callback", "https://footstrike.run/oauth/callback", "not-even-a-url"}, false},
		{"valid preview wildcard", []string{"https://*.preview.footstrike.run/oauth/callback"}, true == false},
		{"wildcard suffix too broad (one dot)", []string{"https://*.run/oauth/callback"}, true},
		{"wildcard must be whole leftmost label", []string{"https://api-*.preview.footstrike.run/oauth/callback"}, true},
		{"two wildcards rejected", []string{"https://*.*.footstrike.run/oauth/callback"}, true},
		{"http wildcard rejected", []string{"http://*.preview.footstrike.run/oauth/callback"}, true},
		{"wildcard without path rejected", []string{"https://*.preview.footstrike.run"}, true},
		{"wildcard with query rejected", []string{"https://*.preview.footstrike.run/cb?x=1"}, true},
		{"wildcard with fragment rejected", []string{"https://*.preview.footstrike.run/cb#f"}, true},
		{"mixed list validates only wildcards", []string{"https://staging.footstrike.run/oauth/callback", "https://*.preview.footstrike.run/oauth/callback"}, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			err := ValidateRedirectURIs(tc.uris)
			if (err != nil) != tc.wantErr {
				t.Errorf("ValidateRedirectURIs(%v) error = %v, wantErr %v", tc.uris, err, tc.wantErr)
			}
		})
	}
}
```

(Note the `"valid preview wildcard"` case uses `true == false` deliberately spelled out to make the expectation unmissable in review: it must NOT error. Write it as `false` in the final code — this is the plan being explicit, not code to copy blindly.)

- [ ] **Step 2: Verify failure** — `go test ./cmd/identity-cli/internal/ -run TestValidateRedirectURIs -v` → compile error.

- [ ] **Step 3: Implement** (`cmd/identity-cli/internal/validate.go`):

```go
package internal

import (
	"fmt"
	"net/url"
	"strings"
)

// ValidateRedirectURIs rejects malformed wildcard redirect entries before
// they reach the database. Only entries containing "*" are validated —
// non-wildcard URIs (including localhost/http dev entries) pass through
// untouched, matching the server's runtime behavior where exact-match
// entries are compared byte-for-byte. The rules mirror
// pkg/httpserver/redirect_match.go: https only, "*." as the entire leftmost
// label, a real path, no query/fragment — plus a breadth guard: the suffix
// after "*." must contain at least two dots (e.g. preview.footstrike.run),
// so an operator can't accidentally register https://*.run/....
func ValidateRedirectURIs(uris []string) error {
	for _, raw := range uris {
		if !strings.Contains(raw, "*") {
			continue
		}
		if strings.Count(raw, "*") != 1 {
			return fmt.Errorf("redirect URI %q: multiple wildcards", raw)
		}
		u, err := url.Parse(raw)
		if err != nil {
			return fmt.Errorf("redirect URI %q: %w", raw, err)
		}
		if u.Scheme != "https" {
			return fmt.Errorf("redirect URI %q: wildcard entries must be https", raw)
		}
		suffix, ok := strings.CutPrefix(u.Host, "*.")
		if !ok || strings.Contains(suffix, "*") {
			return fmt.Errorf("redirect URI %q: wildcard must be the entire leftmost host label (\"*.suffix\")", raw)
		}
		if strings.Count(suffix, ".") < 2 {
			return fmt.Errorf("redirect URI %q: wildcard suffix %q too broad — needs at least two dots", raw, suffix)
		}
		if u.Path == "" || u.Path == "/" {
			return fmt.Errorf("redirect URI %q: wildcard entries must include the full callback path", raw)
		}
		if u.RawQuery != "" || u.Fragment != "" {
			return fmt.Errorf("redirect URI %q: wildcard entries must not carry a query or fragment", raw)
		}
	}
	return nil
}
```

- [ ] **Step 4: Verify pass**, then wire the two call sites:

In `client_update.go`, immediately before the `datastore.Q.UpdateOAuthClient(ctx, params)` call, guarded on the redirect-URI flags having been used (i.e. `params.RedirectUris != nil`):

```go
	if params.RedirectUris != nil {
		if err := internal.ValidateRedirectURIs(params.RedirectUris); err != nil {
			return err
		}
	}
```

In `client_create.go`, after the redirect-URI list is parsed and before the create params are used:

```go
	if err := internal.ValidateRedirectURIs(redirectURIs); err != nil {
		return err
	}
```

(Adapt variable names to what the file actually uses; check the existing import path for the `internal` package alias.)

- [ ] **Step 5: Full gates + commit + PR**

`make test && make lint && go vet ./...` — all green.

```bash
git add cmd/identity-cli/internal/validate.go cmd/identity-cli/internal/validate_test.go cmd/identity-cli/cmd/client_update.go cmd/identity-cli/cmd/client_create.go
git commit -m "Validate wildcard redirect URIs in identity-cli"
git push -u origin wildcard-redirect-validation
gh pr create --title "Validate wildcard redirect URIs in identity-cli" \
  --body "Structural guard for wildcard redirect entries (https, whole-label *, ≥2-dot suffix, full path, no query/fragment) before they reach the DB. Non-wildcard URIs untouched. Deferred item from the preview-environments plan 1 review.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

---

### Task 4: Register the wildcard redirect on the staging dashboard client (imperative; after Task 3's PR merges)

The staging dashboard OAuth client is `oUYmMxjJaeyvnx_gVBddWYAkC88nhy6xxminHqTxRDc=` (public identifier, from footstrike-dashboard's cloudbuild substitutions); its callback path is `/oauth/callback`.

- [ ] **Step 1: Snapshot current state**

```bash
cd ~/Develop/ibormeith/identity && git pull
export DATABASE_URL=$(gcloud secrets versions access latest --secret=identity_staging_database_url)
go run ./cmd/identity-cli client get 'oUYmMxjJaeyvnx_gVBddWYAkC88nhy6xxminHqTxRDc='
```

Record the existing redirect-URI list in the report (it's non-secret config).

- [ ] **Step 2: Append the wildcard entry**

```bash
go run ./cmd/identity-cli client update 'oUYmMxjJaeyvnx_gVBddWYAkC88nhy6xxminHqTxRDc=' \
  --add-redirect-uris 'https://*.preview.footstrike.run/oauth/callback'
```

(`--add-redirect-uris` appends de-duped — it must NOT touch existing entries; the just-merged validation should accept this exact entry, which is itself an end-to-end test of Task 3.)

- [ ] **Step 3: Verify and clean up**

`client get` again — expected: previous list + the one new wildcard entry. Then `unset DATABASE_URL`.

---

## Self-review notes

- **Spec coverage:** provisions every "One-time provisioning" item from the design spec except DNS (user-only, Task 2 step 3) and the bifrost k8s manifest changes (deliberately Track A: SecretProviderClass/env wiring belongs to 3b, RBAC to 3c — they version with the code that consumes them).
- **Cert strategy** deliberately diverges from "per-namespace Certificates": LE duplicate-cert rate limits + 3c's existing secret-copy step make the shared cert strictly better. The spec already says bifrost copies the cert secret.
- **Validation scope** deliberately narrow (wildcard entries only) so existing http/localhost dev registrations keep working.
- **Order:** 1 → 2 requires PR merge + user values; 3 → 4 requires PR merge. Tasks 1 and 3 are independent of each other (different repos) but run sequentially within this track's SDD loop.
