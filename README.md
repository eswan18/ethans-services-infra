# ethans-services-infra

Infrastructure as code for Ethan's services, using Pulumi with Python on GCP.

## What's Managed

- **GKE Cluster** (`main-cluster` in `us-central1-a`)
  - Spot pool (`e2-medium`) for cost-efficient workloads
  - On-demand pool (`e2-standard-2`) for reliable workloads
  - Workload Identity enabled

- **Artifact Registry** for container images

- **Service Accounts** with Workload Identity bindings
  - `fitness-api-staging-sa` / `fitness-api-prod-sa`
  - `identity-staging-sa` / `identity-prod-sa`
  - `argocd-image-updater-sa`

- **Secret Manager** secrets for each service/environment

- **Cloud Build Triggers** for CI/CD: one `{service}-build` per service pushing to
  `main` (asset-manager, bifrost, comms, footstrike-api, footstrike-dashboard,
  forecasting, identity), plus a manual `{service}-preview-build` for each service
  onboarded to preview environments, which bifrost invokes to build a branch.
  Preview triggers are named after the **bifrost registry key**, not the repo —
  the two differ for asset-manager (`asset_manager`), and a trigger named after
  the repo is one bifrost would never find.

- **Secret Manager CSI stack** — how pods get their secrets
  - `secrets-store-csi-driver` (upstream Helm chart)
  - `secrets-store-csi-driver-provider-gcp` (vendored manifest, see below)

  Every service's `SecretProviderClass` goes through both. If the provider is
  down, pods that are already running keep their mounted secrets, but any pod
  that *starts* will fail to mount until it is back.


- **cloudflared** — the Cloudflare Tunnel connector (Deployment + namespace +
  token secret) that carries every prod public hostname. The tunnel itself and
  its hostname routing stay in the Cloudflare Zero Trust dashboard; only the
  in-cluster connector is managed here.


- **Monitoring** — uptime checks against each prod health endpoint, the email
  notification channel, and both alert policies (`Pod Crash Loop`,
  `Prod Uptime Check Failure`).


## Prerequisites

- `gcloud` authenticated with access to the `ethans-services` project
- `pulumi` CLI logged in
- `uv` for Python dependency management

## Usage

```bash
# Preview changes
pulumi preview

# Deploy changes
pulumi up
```

## Bumping the Secret Manager CSI provider

Google publishes no Helm chart for the GCP provider plugin, so
`k8s/secrets-store-csi-driver-provider-gcp.yaml` is upstream's
`deploy/provider-gcp-plugin.yaml` vendored **verbatim** — no local edits, which
is what keeps a bump to a one-line diff:

```bash
TAG=v1.18.0   # whatever is newest
curl -sSf -o k8s/secrets-store-csi-driver-provider-gcp.yaml \
  "https://raw.githubusercontent.com/GoogleCloudPlatform/secrets-store-csi-driver-provider-gcp/$TAG/deploy/provider-gcp-plugin.yaml"
git diff      # expect the image digest to change, and nothing else
pulumi up
```

Upstream pins the image by digest, so that digest line *is* the version. Check
the [changelog][csi-changelog] first; everything through v1.17.0 has been Go and
dependency bumps with no breaking changes.

**Don't let this drift.** Google deprecates old plugin images in Artifact
Registry by retagging them `deprecated-public-image-*`, and eventually removes
them. Because the DaemonSet uses `imagePullPolicy: IfNotPresent`, a pulled image
keeps working on a node that already cached it and fails only when a *new* node
tries to pull it — so the failure surfaces at node replacement, taking down
secret mounting for every service at the least convenient moment. GCP emails an
advisory when a version goes deprecated.

[csi-changelog]: https://github.com/GoogleCloudPlatform/secrets-store-csi-driver-provider-gcp/blob/main/CHANGELOG.md


## Deployment Helper

**The deploy CLI has moved to the bifrost repo.** `ib.py` (and its companion
check script `verify_preview_progress.py`) used to live here; they were ported
to Go as `cmd/bif` in bifrost and deleted from this repo. Install it from a
bifrost checkout:

```bash
cd ../bifrost && make install   # go install ./cmd/bif
```

Then `bif status`, `bif promote` and `bif preview` do what `ib status`,
`ib promote` and `ib preview` did. See bifrost's `README.md` for the full
command list, the exit-code contract, and the two places `bif` deliberately
behaves differently from the Python it replaced.

`bif status` and `bif promote` still work when bifrost itself is down — they
talk to the cluster directly through client-go, never to bifrost's API, which
is what makes `bif promote bifrost` the recovery path for bifrost. (`bif
preview` is an HTTP client of bifrost's API, as `ib preview` was.)

### The `SERVICES` list is no longer maintained here

`ib.py` carried a hardcoded `SERVICES` list that duplicated bifrost's service
registry on purpose: the CLI had to keep working with bifrost down, so it could
not fetch the list over the network. `bif` reads bifrost's
`internal/registry/registry.yaml`, which is `//go:embed`ed into the binary —
compiled in, not fetched — so the offline property survives without the
duplicate. **Adding a service to the fleet no longer requires an edit in this
repo.** Add the registry entry in bifrost; see its
`docs/adding-a-service.md`.
