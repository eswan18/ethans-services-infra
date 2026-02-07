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

- **Cloud Build Triggers** for CI/CD (fitness-api, fitness-dashboard, identity)

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

The `deploy.py` script helps manage staging-to-prod promotions via ArgoCD.

```bash
# Check deployment status for an app
uv run deploy status fitness-api

# Promote staging to prod
uv run deploy promote fitness-api
```

The `status` command shows current image tags for both environments and whether they're in sync. If out of sync, it tells you the command to promote.
