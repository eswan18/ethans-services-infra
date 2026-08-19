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
