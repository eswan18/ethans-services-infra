"""Infrastructure for Ethan's Services in GCP"""

import base64
import json

import pulumi
from pulumi_gcp import (
    container,
    serviceaccount,
    projects,
    artifactregistry,
    secretmanager,
    cloudbuild,
    pubsub,
    monitoring,
)
import pulumi_kubernetes as k8s

# Configuration
config = pulumi.Config()
project = "ethans-services"
region = "us-central1"
zone = "us-central1-a"
github_owner = "eswan18"
cloud_build_sa = f"projects/{project}/serviceAccounts/754418346661-compute@developer.gserviceaccount.com"

# Artifact Registry repository
container_registry = artifactregistry.Repository(
    "containers",
    description="Container images",
    format="DOCKER",
    location=region,
    project=project,
    repository_id="containers",
    opts=pulumi.ResourceOptions(protect=True),
)

# GKE Cluster
main_cluster = container.Cluster(
    "main-cluster",
    addons_config={
        "gce_persistent_disk_csi_driver_config": {
            "enabled": True,
        },
        "network_policy_config": {
            "disabled": True,
        },
    },
    anonymous_authentication_config={
        "mode": "ENABLED",
    },
    cluster_ipv4_cidr="10.36.0.0/14",
    cluster_telemetry={
        "type": "ENABLED",
    },
    control_plane_endpoints_config={
        "dns_endpoint_config": {
            "endpoint": "gke-3fd139f806604cd19549a21e2dd49874e01e-754418346661.us-central1-a.gke.goog",
        },
        "ip_endpoints_config": {
            "enabled": True,
        },
    },
    database_encryption={
        "state": "DECRYPTED",
    },
    default_max_pods_per_node=110,
    location=zone,
    logging_config={
        "enable_components": [
            "SYSTEM_COMPONENTS",
            "WORKLOADS",
        ],
    },
    # Confine GKE auto-upgrades (node + control plane) to 08:00-12:00 UTC,
    # i.e. 3-7am Chicago: single-node cluster, so upgrades mean brief downtime.
    maintenance_policy={
        "daily_maintenance_window": {
            "start_time": "08:00",
        },
    },
    master_auth={
        "client_certificate_config": {
            "issue_client_certificate": False,
        },
    },
    monitoring_config={
        "advanced_datapath_observability_config": {
            "enable_metrics": False,
            "enable_relay": False,
        },
        # CADVISOR/KUBELET + managed Prometheus were GKE creation defaults:
        # ~$22/mo of samples with no dashboards or alerts reading them. Free
        # SYSTEM_COMPONENTS metrics (kubernetes.io/*) cover the crash-loop alert.
        "enable_components": [
            "SYSTEM_COMPONENTS",
        ],
        "managed_prometheus": {
            "enabled": False,
        },
    },
    name="main-cluster",
    network=f"projects/{project}/global/networks/default",
    network_policy={
        "enabled": False,
        "provider": "PROVIDER_UNSPECIFIED",
    },
    networking_mode="VPC_NATIVE",
    node_config={
        "boot_disk": {
            "disk_type": "pd-balanced",
            "size_gb": 100,
        },
        "disk_size_gb": 100,
        "disk_type": "pd-balanced",
        "image_type": "COS_CONTAINERD",
        "kubelet_config": {
            "insecure_kubelet_readonly_port_enabled": "FALSE",
            "max_parallel_image_pulls": 2,
        },
        "logging_variant": "DEFAULT",
        "machine_type": "e2-standard-2",
        "metadata": {
            "disable-legacy-endpoints": "true",
        },
        "oauth_scopes": [
            "https://www.googleapis.com/auth/devstorage.read_only",
            "https://www.googleapis.com/auth/logging.write",
            "https://www.googleapis.com/auth/monitoring",
            "https://www.googleapis.com/auth/service.management.readonly",
            "https://www.googleapis.com/auth/servicecontrol",
            "https://www.googleapis.com/auth/trace.append",
        ],
        "resource_labels": {
            "goog-gke-node-pool-provisioning-model": "on-demand",
        },
        "service_account": "default",
        "workload_metadata_config": {
            "mode": "GKE_METADATA",
        },
    },
    node_pool_auto_config={
        "node_kubelet_config": {
            "insecure_kubelet_readonly_port_enabled": "FALSE",
        },
    },
    node_pool_defaults={
        "node_config_defaults": {
            "insecure_kubelet_readonly_port_enabled": "FALSE",
            "logging_variant": "DEFAULT",
        },
    },
    node_pools=[
        {
            "initial_node_count": 1,
            "max_pods_per_node": 110,
            "name": "default-pool-std2",
            "network_config": {
                "pod_ipv4_cidr_block": "10.36.0.0/14",
                "pod_range": "gke-main-cluster-pods-3fd139f8",
            },
            "node_config": {
                "boot_disk": {
                    "disk_type": "pd-balanced",
                    "size_gb": 100,
                },
                "disk_size_gb": 100,
                "disk_type": "pd-balanced",
                "image_type": "COS_CONTAINERD",
                "kubelet_config": {
                    "insecure_kubelet_readonly_port_enabled": "FALSE",
                    "max_parallel_image_pulls": 2,
                },
                "logging_variant": "DEFAULT",
                "machine_type": "e2-standard-2",
                "metadata": {
                    "disable-legacy-endpoints": "true",
                },
                "oauth_scopes": [
                    "https://www.googleapis.com/auth/devstorage.read_only",
                    "https://www.googleapis.com/auth/logging.write",
                    "https://www.googleapis.com/auth/monitoring",
                    "https://www.googleapis.com/auth/service.management.readonly",
                    "https://www.googleapis.com/auth/servicecontrol",
                    "https://www.googleapis.com/auth/trace.append",
                ],
                "resource_labels": {
                    "goog-gke-node-pool-provisioning-model": "on-demand",
                },
                "service_account": "default",
                "workload_metadata_config": {
                    "mode": "GKE_METADATA",
                },
            },
            "node_count": 1,
            "node_locations": [zone],
            "upgrade_settings": {
                "max_surge": 1,
            },
        },
    ],
    notification_config={
        "pubsub": {
            "enabled": False,
        },
    },
    pod_autoscaling={
        "hpa_profile": "PERFORMANCE",
    },
    pod_security_policy_config={
        "enabled": False,
    },
    private_cluster_config={
        "master_global_access_config": {
            "enabled": False,
        },
    },
    project=project,
    protect_config={
        "workload_config": {
            "audit_mode": "BASIC",
        },
        "workload_vulnerability_mode": "WORKLOAD_VULNERABILITY_MODE_UNSPECIFIED",
    },
    rbac_binding_config={
        "enable_insecure_binding_system_authenticated": True,
        "enable_insecure_binding_system_unauthenticated": True,
    },
    release_channel={
        "channel": "REGULAR",
    },
    secret_manager_config={
        "enabled": False,
    },
    secret_sync_config={
        "enabled": False,
    },
    security_posture_config={
        "mode": "BASIC",
        "vulnerability_mode": "VULNERABILITY_MODE_UNSPECIFIED",
    },
    service_external_ips_config={
        "enabled": False,
    },
    subnetwork=f"projects/{project}/regions/{region}/subnetworks/default",
    workload_identity_config={
        "workload_pool": f"{project}.svc.id.goog",
    },
    opts=pulumi.ResourceOptions(protect=True),
)


# K8s Provider (uses existing kubeconfig context)
k8s_provider = k8s.Provider(
    "gke-k8s",
    context="gke_ethans-services_us-central1-a_main-cluster",
)

# Service Accounts
identity_staging_sa = serviceaccount.Account(
    "identity-staging-sa",
    account_id="identity-staging-sa",
    display_name="Identity Staging Service Account",
    project=project,
)
identity_prod_sa = serviceaccount.Account(
    "identity-prod-sa",
    account_id="identity-prod-sa",
    display_name="Identity Prod Service Account",
    project=project,
)
fitness_api_staging_sa = serviceaccount.Account(
    "fitness-api-staging-sa",
    account_id="fitness-api-staging-sa",
    display_name="Fitness API Staging",
    project=project,
)
fitness_api_prod_sa = serviceaccount.Account(
    "fitness-api-prod-sa",
    account_id="fitness-api-prod-sa",
    display_name="Fitness API Prod",
    project=project,
)
asset_manager_staging_sa = serviceaccount.Account(
    "asset-manager-staging-sa",
    account_id="asset-manager-staging-sa",
    display_name="Asset Manager Staging Service Account",
    project=project,
)
asset_manager_prod_sa = serviceaccount.Account(
    "asset-manager-prod-sa",
    account_id="asset-manager-prod-sa",
    display_name="Asset Manager Prod Service Account",
    project=project,
)
# This service is named haruspex everywhere now. It was `forecasting` until
# Sept 2026; the rename could not happen in place because service accounts,
# secrets and namespaces have no rename operation, so the haruspex identity was
# built alongside the old one, traffic was cut over, and the forecasting-*
# resources were then deleted. Only forecasting_sentry_auth_token survives, and
# only because Cloud Build reads it by name.
haruspex_staging_sa = serviceaccount.Account(
    "haruspex-staging-sa",
    account_id="haruspex-staging-sa",
    display_name="Haruspex Staging Service Account",
    project=project,
)
haruspex_prod_sa = serviceaccount.Account(
    "haruspex-prod-sa",
    account_id="haruspex-prod-sa",
    display_name="Haruspex Prod Service Account",
    project=project,
)
comms_staging_sa = serviceaccount.Account(
    "comms-staging-sa",
    account_id="comms-staging-sa",
    display_name="Comms Staging Service Account",
    project=project,
)
comms_prod_sa = serviceaccount.Account(
    "comms-prod-sa",
    account_id="comms-prod-sa",
    display_name="Comms Prod Service Account",
    project=project,
)
bifrost_staging_sa = serviceaccount.Account(
    "bifrost-staging-sa",
    account_id="bifrost-staging-sa",
    display_name="Bifrost Staging Service Account",
    project=project,
)
bifrost_prod_sa = serviceaccount.Account(
    "bifrost-prod-sa",
    account_id="bifrost-prod-sa",
    display_name="Bifrost Prod Service Account",
    project=project,
)
argocd_image_updater_sa = serviceaccount.Account(
    "argocd-image-updater-sa",
    account_id="argocd-image-updater-sa",
    display_name="ArgoCD Image Updater",
    project=project,
)

# Workload Identity bindings
# (The GCP SAs keep their fitness-api-* names from before the Footstrike
# rename; only the namespace/KSA side was renamed.)
footstrike_api_prod_wi = serviceaccount.IAMMember(
    "footstrike-api-prod-workload-identity",
    service_account_id=fitness_api_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[footstrike-api-prod/footstrike-api-prod-ksa]",
)
footstrike_api_staging_wi = serviceaccount.IAMMember(
    "footstrike-api-staging-workload-identity",
    service_account_id=fitness_api_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[footstrike-api-staging/footstrike-api-staging-ksa]",
)
identity_prod_wi = serviceaccount.IAMMember(
    "identity-prod-workload-identity",
    service_account_id=identity_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[identity-prod/identity-prod-ksa]",
)
identity_staging_wi = serviceaccount.IAMMember(
    "identity-staging-workload-identity",
    service_account_id=identity_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[identity-staging/identity-staging-ksa]",
)
asset_manager_prod_wi = serviceaccount.IAMMember(
    "asset-manager-prod-workload-identity",
    service_account_id=asset_manager_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[asset-manager-prod/asset-manager-prod-ksa]",
)
asset_manager_staging_wi = serviceaccount.IAMMember(
    "asset-manager-staging-workload-identity",
    service_account_id=asset_manager_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[asset-manager-staging/asset-manager-staging-ksa]",
)
haruspex_prod_wi = serviceaccount.IAMMember(
    "haruspex-prod-workload-identity",
    service_account_id=haruspex_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[haruspex-prod/haruspex-prod-ksa]",
)
haruspex_staging_wi = serviceaccount.IAMMember(
    "haruspex-staging-workload-identity",
    service_account_id=haruspex_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[haruspex-staging/haruspex-staging-ksa]",
)
comms_prod_wi = serviceaccount.IAMMember(
    "comms-prod-workload-identity",
    service_account_id=comms_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[comms-prod/comms-prod-ksa]",
)
comms_staging_wi = serviceaccount.IAMMember(
    "comms-staging-workload-identity",
    service_account_id=comms_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[comms-staging/comms-staging-ksa]",
)
bifrost_prod_wi = serviceaccount.IAMMember(
    "bifrost-prod-workload-identity",
    service_account_id=bifrost_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[bifrost-prod/bifrost-prod-ksa]",
)
bifrost_staging_wi = serviceaccount.IAMMember(
    "bifrost-staging-workload-identity",
    service_account_id=bifrost_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[bifrost-staging/bifrost-staging-ksa]",
)

# Secret Manager access (per-secret IAM bindings)
# Maps each service account to the secrets it needs access to.
#
# Both the dict keys here and the strings in secret_names below are Pulumi
# RESOURCE-NAME ANCHORS, not labels — renaming one is a destroy-and-recreate,
# not an edit:
#
#   - A key here feeds `f"{env_key}-access-{secret_name}"`, so renaming it
#     replaces that service account's IAM bindings. Recoverable, but it briefly
#     revokes the running app's access to its own secrets.
#   - A string in secret_names is passed as both the Pulumi resource name and
#     the secret_id, so renaming it DESTROYS the secret and every version in
#     it. Secret Manager has no undelete.
#
# The Aug 2026 fitness_api_* -> footstrike_api_* rename is the worked example:
# it could not be done by editing these strings. It took five phases — create
# the new secrets alongside the old, copy each value with a digest check,
# repoint the SecretProviderClasses, soak, and only then delete the originals.
# The keys below still read `fitness-api-*` because the service accounts really
# are named `fitness-api-{env}-sa`; that one is a deliberate keep, not a
# leftover.
secret_access = {
    "fitness-api-prod": (
        fitness_api_prod_sa,
        [
            "footstrike_api_prod_database_url",
            "footstrike_api_prod_google_client_id",
            "footstrike_api_prod_google_client_secret",
            "footstrike_api_prod_oauth_state_secret",
            "footstrike_api_prod_r2_access_key_id",
            "footstrike_api_prod_r2_secret_access_key",
            "footstrike_api_prod_credential_encryption_key",
        ],
    ),
    "fitness-api-staging": (
        fitness_api_staging_sa,
        [
            "footstrike_api_staging_database_url",
            "footstrike_api_staging_google_client_id",
            "footstrike_api_staging_google_client_secret",
            "footstrike_api_staging_oauth_state_secret",
            "footstrike_api_staging_r2_access_key_id",
            "footstrike_api_staging_r2_secret_access_key",
            "footstrike_api_staging_credential_encryption_key",
        ],
    ),
    "identity-prod": (
        identity_prod_sa,
        [
            "identity_prod_database_url",
            "identity_prod_jwt_private_key",
            "identity_prod_resend_api_key",
            "identity_prod_storage_access_key",
            "identity_prod_storage_secret_key",
            "identity_prod_storage_token",
        ],
    ),
    "identity-staging": (
        identity_staging_sa,
        [
            "identity_staging_database_url",
            "identity_staging_jwt_private_key",
            "identity_staging_resend_api_key",
            "identity_staging_storage_access_key",
            "identity_staging_storage_secret_key",
            "identity_staging_storage_token",
        ],
    ),
    "asset-manager-prod": (
        asset_manager_prod_sa,
        [
            "asset_manager_prod_database_url",
            "asset_manager_prod_client_id",
            "asset_manager_prod_client_secret",
            "asset_manager_prod_secret_key",
        ],
    ),
    "asset-manager-staging": (
        asset_manager_staging_sa,
        [
            "asset_manager_staging_database_url",
            "asset_manager_staging_client_id",
            "asset_manager_staging_client_secret",
            "asset_manager_staging_secret_key",
        ],
    ),
    "haruspex-prod": (
        haruspex_prod_sa,
        [
            "haruspex_prod_database_url",
            "haruspex_prod_jwt_secret",
            "haruspex_prod_argon2_salt",
            "haruspex_prod_idp_client_id",
            "haruspex_prod_idp_client_secret",
        ],
    ),
    "haruspex-staging": (
        haruspex_staging_sa,
        [
            "haruspex_staging_database_url",
            "haruspex_staging_jwt_secret",
            "haruspex_staging_argon2_salt",
            "haruspex_staging_idp_client_id",
            "haruspex_staging_idp_client_secret",
        ],
    ),
    "comms-prod": (
        comms_prod_sa,
        [
            "comms_prod_resend_api_key",
        ],
    ),
    "comms-staging": (
        comms_staging_sa,
        [
            "comms_staging_resend_api_key",
        ],
    ),
    "bifrost-prod": (
        bifrost_prod_sa,
        [
            "bifrost_prod_oidc_client_id",
            "bifrost_prod_oidc_client_secret",
            "bifrost_prod_session_secret",
            "bifrost_prod_github_token",
            "bifrost_prod_neon_api_key",
            "bifrost_prod_preview_api_token",
        ],
    ),
    "bifrost-staging": (
        bifrost_staging_sa,
        [
            "bifrost_staging_oidc_client_id",
            "bifrost_staging_oidc_client_secret",
            "bifrost_staging_session_secret",
        ],
    ),
}
# Artifact Registry access for ArgoCD Image Updater
argocd_image_updater_ar = projects.IAMMember(
    "argocd-image-updater-ar-access",
    project=project,
    role="roles/artifactregistry.reader",
    member=argocd_image_updater_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Cloud Build read access for bifrost (shows build status in its UI)
bifrost_staging_builds_viewer = projects.IAMMember(
    "bifrost-staging-builds-viewer",
    project=project,
    role="roles/cloudbuild.builds.viewer",
    member=bifrost_staging_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)
bifrost_prod_builds_viewer = projects.IAMMember(
    "bifrost-prod-builds-viewer",
    project=project,
    role="roles/cloudbuild.builds.viewer",
    member=bifrost_prod_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Preview orchestration (prod bifrost only): running a {registry key}-preview-build
# trigger needs cloudbuild.builds.create, which the viewer role above lacks —
# builds.editor is the narrowest predefined role that grants it. The triggers
# also pin service_account=cloud_build_sa, so the caller must additionally be
# allowed to actAs that SA; without the serviceAccountUser binding below, the
# run fails with a second, less obvious 403.
bifrost_prod_builds_editor = projects.IAMMember(
    "bifrost-prod-builds-editor",
    project=project,
    role="roles/cloudbuild.builds.editor",
    member=bifrost_prod_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)
bifrost_prod_act_as_cloud_build_sa = serviceaccount.IAMMember(
    "bifrost-prod-act-as-cloud-build-sa",
    service_account_id=f"projects/{project}/serviceAccounts/754418346661-compute@developer.gserviceaccount.com",
    role="roles/iam.serviceAccountUser",
    member=bifrost_prod_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Secret Manager secrets (structure only - values managed outside Pulumi)
secret_names = [
    # footstrike-api prod
    "footstrike_api_prod_database_url",
    "footstrike_api_prod_google_client_id",
    "footstrike_api_prod_google_client_secret",
    "footstrike_api_prod_oauth_state_secret",
    "footstrike_api_prod_r2_access_key_id",
    "footstrike_api_prod_r2_secret_access_key",
    "footstrike_api_prod_credential_encryption_key",
    # footstrike-api staging
    "footstrike_api_staging_database_url",
    "footstrike_api_staging_google_client_id",
    "footstrike_api_staging_google_client_secret",
    "footstrike_api_staging_oauth_state_secret",
    "footstrike_api_staging_r2_access_key_id",
    "footstrike_api_staging_r2_secret_access_key",
    "footstrike_api_staging_credential_encryption_key",
    # identity prod
    "identity_prod_database_url",
    "identity_prod_jwt_private_key",
    "identity_prod_resend_api_key",
    "identity_prod_storage_access_key",
    "identity_prod_storage_secret_key",
    "identity_prod_storage_token",
    # identity staging
    "identity_staging_database_url",
    "identity_staging_jwt_private_key",
    "identity_staging_resend_api_key",
    "identity_staging_storage_access_key",
    "identity_staging_storage_secret_key",
    "identity_staging_storage_token",
    # asset-manager prod
    "asset_manager_prod_database_url",
    "asset_manager_prod_client_id",
    "asset_manager_prod_client_secret",
    "asset_manager_prod_secret_key",
    # asset-manager staging
    "asset_manager_staging_database_url",
    "asset_manager_staging_client_id",
    "asset_manager_staging_client_secret",
    "asset_manager_staging_secret_key",
    # haruspex prod (rename phase 1; values copied from forecasting_prod_*)
    "haruspex_prod_database_url",
    "haruspex_prod_jwt_secret",
    "haruspex_prod_argon2_salt",
    "haruspex_prod_idp_client_id",
    "haruspex_prod_idp_client_secret",
    # haruspex staging (rename phase 1; values copied from forecasting_staging_*)
    "haruspex_staging_database_url",
    "haruspex_staging_jwt_secret",
    "haruspex_staging_argon2_salt",
    "haruspex_staging_idp_client_id",
    "haruspex_staging_idp_client_secret",
    # haruspex build (used by Cloud Build, not the app). Keeps its old name:
    # cloudbuild.yaml names it literally, so it moves with the build-side rename.
    "forecasting_sentry_auth_token",
    # comms prod
    "comms_prod_resend_api_key",
    # comms staging
    "comms_staging_resend_api_key",
    # bifrost prod
    "bifrost_prod_oidc_client_id",
    "bifrost_prod_oidc_client_secret",
    "bifrost_prod_session_secret",
    "bifrost_prod_github_token",
    "bifrost_prod_neon_api_key",
    "bifrost_prod_preview_api_token",
    # bifrost staging
    "bifrost_staging_oidc_client_id",
    "bifrost_staging_oidc_client_secret",
    "bifrost_staging_session_secret",
]
secrets = {}
for name in secret_names:
    secrets[name] = secretmanager.Secret(
        name,
        secret_id=name,
        project=project,
        replication=secretmanager.SecretReplicationArgs(
            auto=secretmanager.SecretReplicationAutoArgs(),
        ),
        opts=pulumi.ResourceOptions(protect=True),
    )

# Per-secret IAM bindings (grant each SA access only to its own secrets)
secret_iam_bindings = {}
for env_key, (sa, secret_list) in secret_access.items():
    for secret_name in secret_list:
        resource_name = f"{env_key}-access-{secret_name}"
        secret_iam_bindings[resource_name] = secretmanager.SecretIamMember(
            resource_name,
            project=project,
            secret_id=secrets[secret_name].secret_id,
            role="roles/secretmanager.secretAccessor",
            member=sa.email.apply(lambda email: f"serviceAccount:{email}"),
        )

# Cloud Build SA access to build-time secrets
cloud_build_sa_email = "754418346661-compute@developer.gserviceaccount.com"
cloud_build_sentry_access = secretmanager.SecretIamMember(
    "cloud-build-access-forecasting_sentry_auth_token",
    project=project,
    secret_id=secrets["forecasting_sentry_auth_token"].secret_id,
    role="roles/secretmanager.secretAccessor",
    member=f"serviceAccount:{cloud_build_sa_email}",
)

# Cloud Build triggers
footstrike_api_build = cloudbuild.Trigger(
    "footstrike-api-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="footstrike-api",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="footstrike-api-build",
    project=project,
    service_account=cloud_build_sa,
)
footstrike_dashboard_build = cloudbuild.Trigger(
    "footstrike-dashboard-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="footstrike-dashboard",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="footstrike-dashboard-build",
    project=project,
    service_account=cloud_build_sa,
)
identity_build = cloudbuild.Trigger(
    "identity-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="identity",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="identity-build",
    project=project,
    service_account=cloud_build_sa,
)
asset_manager_build = cloudbuild.Trigger(
    "asset-manager-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="asset_manager",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="asset-manager-build",
    project=project,
    service_account=cloud_build_sa,
)
# Trigger name stays "forecasting" because bifrost's registry key does -- it is
# what Orchestrator.TriggerIDs looks up. The namespaces and ArgoCD apps that
# also used to justify this are haruspex now, so bifrost is the only reason
# left, and renaming these triggers is part of that same change. The GitHub
# repo the trigger watches was renamed to haruspex separately; Cloud Build
# matches push events by repo name, so that pair has to disagree or the trigger
# never fires.
forecasting_build = cloudbuild.Trigger(
    "forecasting-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="haruspex",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="forecasting-build",
    project=project,
    service_account=cloud_build_sa,
)
comms_build = cloudbuild.Trigger(
    "comms-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="comms",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="comms-build",
    project=project,
    service_account=cloud_build_sa,
)
bifrost_build = cloudbuild.Trigger(
    "bifrost-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="bifrost",
        owner=github_owner,
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="bifrost-build",
    project=project,
    service_account=cloud_build_sa,
)

# Preview builds: manual-invocation triggers (no push event). Run with
#   gcloud builds triggers run {registry key}-preview-build --branch=<branch>
# The build config is pinned to main's cloudbuild-preview.yaml; the build
# *source* is whatever branch the run names. Note RunBuildTrigger accepts
# no substitutions — preview builds are deliberately substitution-free.
#
# The trigger *name* must match bifrost's internal/registry/registry.yaml key
# for the service (what Orchestrator.TriggerIDs looks up), while the GitHub
# *repo* the trigger builds from is that service's own repo — the two aren't
# always equal (asset-manager's repo is asset_manager), so each is sourced
# from its own element of the pair rather than one variable serving both.
for preview_key, preview_repo in [
    ("footstrike-api", "footstrike-api"),
    ("footstrike-dashboard", "footstrike-dashboard"),
    ("identity", "identity"),
    ("forecasting", "haruspex"),
]:
    cloudbuild.Trigger(
        f"{preview_key}-preview-build",
        name=f"{preview_key}-preview-build",
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

# Pub/Sub topics and subscriptions for event-driven notifications
# One topic per source service per environment; comms subscribes to all of them.
pubsub_config = {
    "staging": {
        "topics": {
            "footstrike-events-staging": fitness_api_staging_sa,
            "identity-events-staging": identity_staging_sa,
            "asset-events-staging": asset_manager_staging_sa,
            "haruspex-events-staging": haruspex_staging_sa,
        },
        "subscriber_sa": comms_staging_sa,
        "subscriptions": {
            "comms-staging-footstrike-sub": "footstrike-events-staging",
            "comms-staging-identity-sub": "identity-events-staging",
            "comms-staging-asset-sub": "asset-events-staging",
            "comms-staging-haruspex-sub": "haruspex-events-staging",
        },
    },
    "prod": {
        "topics": {
            "footstrike-events-prod": fitness_api_prod_sa,
            "identity-events-prod": identity_prod_sa,
            "asset-events-prod": asset_manager_prod_sa,
            "haruspex-events-prod": haruspex_prod_sa,
        },
        "subscriber_sa": comms_prod_sa,
        "subscriptions": {
            "comms-prod-footstrike-sub": "footstrike-events-prod",
            "comms-prod-identity-sub": "identity-events-prod",
            "comms-prod-asset-sub": "asset-events-prod",
            "comms-prod-haruspex-sub": "haruspex-events-prod",
        },
    },
}

pubsub_topics = {}
for env, env_config in pubsub_config.items():
    for topic_name, publisher_sa in env_config["topics"].items():
        topic = pubsub.Topic(
            topic_name,
            name=topic_name,
            project=project,
        )
        pubsub_topics[topic_name] = topic

        # Grant the source service permission to publish
        pubsub.TopicIAMMember(
            f"{topic_name}-publisher",
            project=project,
            topic=topic.name,
            role="roles/pubsub.publisher",
            member=publisher_sa.email.apply(lambda email: f"serviceAccount:{email}"),
        )

    subscriber_sa = env_config["subscriber_sa"]
    for sub_name, topic_name in env_config["subscriptions"].items():
        subscription = pubsub.Subscription(
            sub_name,
            name=sub_name,
            topic=pubsub_topics[topic_name].name,
            project=project,
            ack_deadline_seconds=60,
        )

        # Grant comms permission to consume
        pubsub.SubscriptionIAMMember(
            f"{sub_name}-subscriber",
            project=project,
            subscription=subscription.name,
            role="roles/pubsub.subscriber",
            member=subscriber_sa.email.apply(lambda email: f"serviceAccount:{email}"),
        )

# These duplicate the publisher grants the pubsub_config loop above now builds:
# both resources assert (haruspex-*-sa, roles/pubsub.publisher) on the same
# topic. They are kept deliberately, and removing them is not a tidy-up.
#
# GCP holds ONE binding per (member, role). Two Pulumi resources asserting it
# means deleting either issues a real removeIamMember and the binding goes,
# whatever the surviving resource's state says it owns -- and Pulumi will not
# re-assert on the next up, because its state already records the member as
# present. During the teardown this mattered: the loop-built grants were being
# replaced (forecasting-sa -> haruspex-sa) in the same apply that would have
# deleted these, with no ordering guarantee between the two, so prod could have
# been left unable to publish.
#
# To remove them later, delete them and then run `pulumi up --refresh` in the
# same sitting: the refresh notices the loop-built grant's binding is missing
# and re-creates it. Verify with
#   gcloud pubsub topics get-iam-policy haruspex-events-prod
# before considering it done.
for _env_suffix, _sa in (("staging", haruspex_staging_sa), ("prod", haruspex_prod_sa)):
    pubsub.TopicIAMMember(
        f"haruspex-events-{_env_suffix}-publisher-haruspex-sa",
        project=project,
        topic=pubsub_topics[f"haruspex-events-{_env_suffix}"].name,
        role="roles/pubsub.publisher",
        member=_sa.email.apply(lambda email: f"serviceAccount:{email}"),
    )

# Namespaces for the Helm releases that do not create their own. cert-manager
# and ingress-nginx pass create_namespace=True; argocd, argocd-image-updater
# and tailscale-operator do not -- and Helm will not install into a namespace
# that does not exist. Without these two resources a from-scratch `pulumi up`
# fails outright, which made "step 2 creates the Tailscale operator release" in
# the bootstrap runbook untrue: someone had to hand-create both namespaces
# first, and nothing said so.
#
# Adopted by import rather than recreated: deleting either would take ArgoCD or
# the entire tailnet ingress with it.
argocd_namespace = k8s.core.v1.Namespace(
    "argocd",
    metadata={"name": "argocd"},
    opts=pulumi.ResourceOptions(provider=k8s_provider, import_="argocd"),
)

tailscale_namespace = k8s.core.v1.Namespace(
    "tailscale",
    # The `name` label is already on the live namespace; declaring it keeps the
    # import clean. (`kubernetes.io/metadata.name` is server-added, so Pulumi
    # tolerates it undeclared.)
    metadata={"name": "tailscale", "labels": {"name": "tailscale"}},
    opts=pulumi.ResourceOptions(provider=k8s_provider, import_="tailscale"),
)

# ArgoCD (Helm)
argocd_release = k8s.helm.v3.Release(
    "argocd",
    chart="argo-cd",
    version="9.4.10",
    namespace="argocd",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://argoproj.github.io/argo-helm",
    ),
    values={
        "server": {
            "resources": {
                "requests": {"cpu": "5m", "memory": "64Mi"},
            },
        },
        "controller": {
            "resources": {
                "requests": {"cpu": "5m", "memory": "64Mi"},
            },
        },
        "repoServer": {
            "resources": {
                "requests": {"cpu": "250m", "memory": "256Mi"},
                "limits": {"cpu": "1", "memory": "1Gi"},
            },
            "livenessProbe": {
                "timeoutSeconds": 10,
                "failureThreshold": 5,
            },
            "readinessProbe": {
                "timeoutSeconds": 5,
                "failureThreshold": 5,
            },
        },
        "redis": {
            "resources": {
                "requests": {"cpu": "5m", "memory": "32Mi"},
            },
        },
        "dex": {"enabled": False},
        "notifications": {"enabled": False},
        "applicationSet": {"enabled": False},
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[argocd_namespace],
    ),
)

argocd_image_updater_release = k8s.helm.v3.Release(
    "argocd-image-updater",
    chart="argocd-image-updater",
    version="1.1.3",
    namespace="argocd",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://argoproj.github.io/argo-helm",
    ),
    values={
        "resources": {
            "requests": {"cpu": "5m", "memory": "32Mi"},
        },
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[argocd_namespace],
    ),
)


# Registry credentials for argocd-image-updater. Pulumi mints the service
# account key itself rather than adopting the hand-made one, which is what
# makes this the one bootstrap secret with no human step at all: a rebuild goes
# SA -> key -> secret with nothing to hand-carry. The Feb 2026 USER_MANAGED key
# on this SA should be deleted once this is live.
argocd_image_updater_key = serviceaccount.Key(
    "argocd-image-updater-key",
    service_account_id=argocd_image_updater_sa.name,
)


def _gar_docker_config(b64_private_key: str) -> str:
    """Render a dockerconfigjson for Artifact Registry from a SA key.

    `serviceaccount.Key.private_key` is the base64-encoded key *file*; Artifact
    Registry wants the decoded JSON as the password, under the literal username
    `_json_key`. The `auth` field is the same pair base64'd, which is what
    clients that ignore username/password read instead.
    """
    key_json = base64.b64decode(b64_private_key).decode()
    pair = base64.b64encode(f"_json_key:{key_json}".encode()).decode()
    return json.dumps(
        {
            "auths": {
                f"{region}-docker.pkg.dev": {
                    "username": "_json_key",
                    "password": key_json,
                    "auth": pair,
                }
            }
        }
    )


gar_pull_secret = k8s.core.v1.Secret(
    "gar-pull-secret",
    metadata={"name": "gar-pull-secret", "namespace": "argocd"},
    type="kubernetes.io/dockerconfigjson",
    string_data={
        ".dockerconfigjson": argocd_image_updater_key.private_key.apply(
            _gar_docker_config
        )
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[argocd_image_updater_release],
    ),
)

# ArgoCD's credential template for the private eswan18 repos (footstrike-api
# and footstrike-dashboard went private in July 2026). Without it every
# affected Application reports a ComparisonError -- "failed to list refs:
# authentication required: Repository not found" -- and syncs stop silently
# while `bif promote` appears to do nothing: it still writes the image
# override, ArgoCD just cannot render manifests to apply it.
#
# The PAT expires and Pulumi does not fix that. It only makes renewal
# `pulumi config set --secret github-repocreds-pat` + `pulumi up` rather than a
# hand-rolled `kubectl create secret`.
github_repocreds_secret = k8s.core.v1.Secret(
    "github-eswan18-repocreds",
    metadata={
        "name": "github-eswan18-repocreds",
        "namespace": "argocd",
        # This label is what makes ArgoCD treat the secret as a credential
        # template rather than an inert Opaque secret.
        "labels": {"argocd.argoproj.io/secret-type": "repo-creds"},
    },
    string_data={
        "url": f"https://github.com/{github_owner}",
        "username": github_owner,
        "password": config.require_secret("github-repocreds-pat"),
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[argocd_release],
    ),
)

# Secrets Store CSI Driver (Helm)
csi_secrets_store_release = k8s.helm.v3.Release(
    "csi-secrets-store",
    chart="secrets-store-csi-driver",
    version="1.5.5",
    namespace="kube-system",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts",
    ),
    values={
        "syncSecret": {"enabled": True},
        # Re-fetch mounted secrets and patch synced K8s Secrets every poll
        # interval (default 2m). Without this, SecretProviderClass changes
        # never reach an already-created synced Secret.
        "enableSecretRotation": True,
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

# Secret Manager CSI provider plugin (GCP). Vendored verbatim from upstream's
# deploy/provider-gcp-plugin.yaml at v1.17.0: Google publishes no Helm chart
# for it, so the raw manifest is the supported install path. To bump, re-fetch
# the file at the new tag and `pulumi up` (see README).
#
# depends_on is load-bearing on a fresh cluster: the plugin registers its
# socket in the directory the driver watches, so the driver must exist first.
csi_provider_gcp = k8s.yaml.v2.ConfigFile(
    "csi-secrets-store-provider-gcp",
    file="k8s/secrets-store-csi-driver-provider-gcp.yaml",
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[csi_secrets_store_release],
    ),
)

# Tailscale Operator (Helm)
tailscale_operator_release = k8s.helm.v3.Release(
    "tailscale-operator",
    chart="tailscale-operator",
    version="1.94.1",
    namespace="tailscale",
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://pkgs.tailscale.com/helmcharts",
    ),
    values={
        "oauth": {
            "clientId": config.require_secret("tailscale-oauth-client-id"),
            "clientSecret": config.require_secret("tailscale-oauth-client-secret"),
        },
        "operatorConfig": {
            "defaultTags": ["tag:k8s-operator", "tag:k8s"],
        },
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[tailscale_namespace],
    ),
)

# cert-manager (Helm): browser-valid TLS for custom-domain staging hosts
# (*.staging.footstrike.run, staging.haruspex.fyi) that stay tailnet-only.
# Issuance uses Let's Encrypt DNS-01 through the Cloudflare API, so it never
# needs public reachability.
#
# One API token per zone, each a Pulumi config secret, each scoped to just its
# own zone: a leaked token can then only touch the zone it belongs to, and
# footstrike.run carries prod plus every preview environment.
#
#   cloudflare-dns-api-token           -> footstrike.run
#   cloudflare-dns-api-token-haruspex  -> haruspex.fyi
#
# Both need Zone:DNS:Edit *and* Zone:Zone:Read — cert-manager resolves a zone
# ID from the DNS name before it can write the _acme-challenge TXT record, and
# Cloudflare's "Edit zone DNS" token template does not include the read.
# Without it the challenge hangs rather than failing with a clear error.
cert_manager_release = k8s.helm.v3.Release(
    "cert-manager",
    chart="cert-manager",
    version="v1.21.0",
    namespace="cert-manager",
    create_namespace=True,
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://charts.jetstack.io",
    ),
    values={
        "crds": {"enabled": True},
        "resources": {"requests": {"cpu": "5m", "memory": "64Mi"}},
        "cainjector": {"resources": {"requests": {"cpu": "5m", "memory": "64Mi"}}},
        "webhook": {"resources": {"requests": {"cpu": "5m", "memory": "32Mi"}}},
    },
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

cloudflare_dns_token_secret = k8s.core.v1.Secret(
    "cloudflare-dns-token",
    metadata={
        "name": "cloudflare-dns-token",
        "namespace": "cert-manager",
    },
    string_data={"api-token": config.require_secret("cloudflare-dns-api-token")},
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[cert_manager_release],
    ),
)

cloudflare_dns_token_haruspex_secret = k8s.core.v1.Secret(
    "cloudflare-dns-token-haruspex",
    metadata={
        "name": "cloudflare-dns-token-haruspex",
        "namespace": "cert-manager",
    },
    string_data={
        "api-token": config.require_secret("cloudflare-dns-api-token-haruspex")
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[cert_manager_release],
    ),
)

letsencrypt_dns01_issuer = k8s.apiextensions.CustomResource(
    "letsencrypt-dns01",
    api_version="cert-manager.io/v1",
    kind="ClusterIssuer",
    metadata={"name": "letsencrypt-dns01"},
    spec={
        "acme": {
            "email": "ethanpswan@gmail.com",
            "server": "https://acme-v02.api.letsencrypt.org/directory",
            "privateKeySecretRef": {"name": "letsencrypt-dns01-account-key"},
            # One solver per zone, each with an explicit dnsZones selector so
            # routing never rests on cert-manager's specificity rules: a
            # selectorless solver matches everything, and pairing one with a
            # selectored sibling makes which token gets used a question of
            # precedence rather than of what is written here. A dnsZones entry
            # covers the zone and all of its subdomains, so footstrike.run
            # still carries *.preview.footstrike.run and the staging hosts.
            "solvers": [
                {
                    "selector": {"dnsZones": ["footstrike.run"]},
                    "dns01": {
                        "cloudflare": {
                            "apiTokenSecretRef": {
                                "name": "cloudflare-dns-token",
                                "key": "api-token",
                            }
                        }
                    },
                },
                {
                    "selector": {"dnsZones": ["haruspex.fyi"]},
                    "dns01": {
                        "cloudflare": {
                            "apiTokenSecretRef": {
                                "name": "cloudflare-dns-token-haruspex",
                                "key": "api-token",
                            }
                        }
                    },
                },
            ],
        }
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[
            cert_manager_release,
            cloudflare_dns_token_secret,
            cloudflare_dns_token_haruspex_secret,
        ],
    ),
)

# Preview environments: shared namespace holding the wildcard certificate.
# One cert (not per-preview) — Let's Encrypt's duplicate-certificate limit
# (5/week per identical name set) would throttle preview creation otherwise.
# Bifrost copies the secret into each preview namespace at creation time.
previews_namespace = k8s.core.v1.Namespace(
    "previews",
    metadata={"name": "previews"},
    opts=pulumi.ResourceOptions(provider=k8s_provider),
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
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[cert_manager_release, previews_namespace],
    ),
)

# ingress-nginx (Helm): routes the custom-domain staging hosts. Its Service is
# a Tailscale LoadBalancer, so the controller gets a stable tailnet device
# (staging-ingress.<tailnet>.ts.net); public grey-cloud CNAMEs for
# staging.footstrike.run / api.staging.footstrike.run resolve to it, and only
# tailnet members can route to the address. Service repos add Ingress
# resources with ingressClassName: nginx + a cert-manager annotation.
ingress_nginx_release = k8s.helm.v3.Release(
    "ingress-nginx",
    chart="ingress-nginx",
    version="4.15.1",
    namespace="ingress-nginx",
    create_namespace=True,
    repository_opts=k8s.helm.v3.RepositoryOptsArgs(
        repo="https://kubernetes.github.io/ingress-nginx",
    ),
    values={
        "controller": {
            "service": {
                "loadBalancerClass": "tailscale",
                "annotations": {"tailscale.com/hostname": "staging-ingress"},
            },
            "resources": {"requests": {"cpu": "10m", "memory": "128Mi"}},
        },
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[tailscale_operator_release],
    ),
)

# cloudflared: the Cloudflare Tunnel connector carrying every prod public
# hostname (*.ethanswan.com, footstrike.run, api.footstrike.run). It dials out
# to Cloudflare's edge, so there is no inbound LoadBalancer here to secure.
#
# Hand-applied and tracked nowhere until Aug 2026, which made it the quietest
# hole in a rebuild: every service would come up healthy and simply be
# unreachable from the internet, with nothing failing to point at the cause.
#
# Only the in-cluster connector is IaC. The tunnel itself, its public-hostname
# routing, and the DNS records live in the Cloudflare Zero Trust dashboard as
# remotely-managed config, and a rebuild still needs those recreated by hand.
cloudflared_namespace = k8s.core.v1.Namespace(
    "cloudflared",
    metadata={"name": "cloudflared"},
    # Adopted from the hand-applied original rather than recreated (Aug 2026):
    # deleting this namespace would have taken every prod hostname with it. The
    # import_ option that did the adopting has served its purpose and is gone.
    opts=pulumi.ResourceOptions(provider=k8s_provider),
)

cloudflared_token_secret = k8s.core.v1.Secret(
    "cloudflared-token",
    metadata={"name": "cloudflared-token", "namespace": "cloudflared"},
    string_data={"token": config.require_secret("cloudflared-tunnel-token")},
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[cloudflared_namespace],
    ),
)

cloudflared_deployment = k8s.apps.v1.Deployment(
    "cloudflared",
    metadata={"name": "cloudflared", "namespace": "cloudflared"},
    spec={
        "replicas": 2,
        "selector": {"match_labels": {"app": "cloudflared"}},
        "template": {
            "metadata": {"labels": {"app": "cloudflared"}},
            "spec": {
                "containers": [
                    {
                        "name": "cloudflared",
                        "image": "cloudflare/cloudflared:latest",
                        "args": [
                            "tunnel",
                            "--no-autoupdate",
                            "run",
                            "--token",
                            "$(TUNNEL_TOKEN)",
                        ],
                        "env": [
                            {
                                "name": "TUNNEL_TOKEN",
                                "value_from": {
                                    "secret_key_ref": {
                                        "name": "cloudflared-token",
                                        "key": "token",
                                    },
                                },
                            },
                        ],
                        # Steady state measures 6m CPU / 24Mi. These requests
                        # exist mainly to get off BestEffort QoS: without them
                        # the connector for all prod ingress is the first pod
                        # evicted under node memory pressure.
                        "resources": {
                            "requests": {"cpu": "10m", "memory": "64Mi"},
                        },
                    },
                ],
            },
        },
    },
    opts=pulumi.ResourceOptions(
        provider=k8s_provider,
        depends_on=[cloudflared_token_secret],
    ),
)

# Uptime checks: probe each prod app's health endpoint through the full public
# path (Cloudflare edge -> tunnel -> cloudflared -> service -> pod), catching
# outages the in-cluster restart alert can't see. US-only; the API requires a
# minimum of 3 probe locations, so this is the smallest allowed footprint.
prod_health_checks = {
    "footstrike-dashboard": ("footstrike.run", "/health"),
    "footstrike-api": ("api.footstrike.run", "/health"),
    "identity": ("identity.ethanswan.com", "/health"),
    "forecasting": ("haruspex.fyi", "/api/health"),
    "asset-manager": ("assets.ethanswan.com", "/health"),
    "bifrost": ("bifrost.ethanswan.com", "/health"),
}

for app, (host, path) in prod_health_checks.items():
    monitoring.UptimeCheckConfig(
        f"{app}-prod-uptime",
        display_name=f"{app} prod health",
        project=project,
        period="60s",
        timeout="10s",
        selected_regions=["USA_OREGON", "USA_IOWA", "USA_VIRGINIA"],
        http_check={
            "path": path,
            "port": 443,
            "use_ssl": True,
            "validate_ssl": True,
            "request_method": "GET",
        },
        monitored_resource={
            "type": "uptime_url",
            "labels": {"project_id": project, "host": host},
        },
    )

# The email channel every alert routes to. The console-made original was
# adopted by import in Aug 2026 rather than replaced, because a NEW email
# channel starts unverified, and an unverified channel accepts alerts and
# silently delivers nothing until someone clicks a link in a confirmation mail.
# That still applies to a from-scratch rebuild, where this resource does get
# created: verify it by mail or the cluster is unmonitored while looking fine.
#
# This replaces a hardcoded channel ID, which was a bootstrap landmine: on a
# fresh project that ID resolves to nothing, so `pulumi up` failed outright
# until someone hand-edited this file.
alert_email_channel = monitoring.NotificationChannel(
    "alert-email",
    display_name="ethanpswan@gmail.com",
    type="email",
    project=project,
    labels={"email_address": "ethanpswan@gmail.com"},
    enabled=True,
)

# One policy covers all uptime checks (grouped by host, so each app alerts
# independently and future checks are included automatically).

monitoring.AlertPolicy(
    "prod-uptime-alert",
    display_name="Prod Uptime Check Failure",
    project=project,
    combiner="OR",
    conditions=[
        {
            "display_name": "Health endpoint failing from multiple locations",
            "condition_threshold": {
                "filter": (
                    'metric.type="monitoring.googleapis.com/uptime_check/check_passed"'
                    ' AND resource.type="uptime_url"'
                ),
                "aggregations": [
                    {
                        "alignment_period": "120s",
                        "per_series_aligner": "ALIGN_NEXT_OLDER",
                        "cross_series_reducer": "REDUCE_COUNT_FALSE",
                        "group_by_fields": ["resource.label.host"],
                    }
                ],
                "comparison": "COMPARISON_GT",
                "threshold_value": 1,
                "duration": "180s",
                "trigger": {"count": 1},
            },
        }
    ],
    notification_channels=[alert_email_channel.name],
    documentation={
        "content": (
            "A prod health endpoint has been failing its uptime check from"
            " multiple US locations for 3+ minutes. The full public path is"
            " affected (Cloudflare tunnel -> cloudflared -> service -> pod).\n\n"
            "Expected during the GKE maintenance window (08:00-12:00 UTC)"
            " while the single node upgrades.\n\n"
            "Triage: `kubectl get pods -A | grep -v Running`, then"
            " `kubectl get pods -n cloudflared` and `bif status <app>`."
        ),
        "mime_type": "text/markdown",
    },
)

# Transcribed verbatim from the console-created policy, which was then adopted
# by import rather than rebuilt: this alert has been live since Feb 2026 and
# replacing it would have meant a window with no crash-loop alerting. The odd
# filter spacing, the 0s duration and the 3-day autoClose are the console's
# own, kept byte-for-byte so that import landed as an import, not an update.
# Leave them alone unless you mean to change the alert.
monitoring.AlertPolicy(
    "pod-crash-loop-alert",
    display_name="Pod Crash Loop",
    project=project,
    combiner="OR",
    enabled=True,
    conditions=[
        {
            "display_name": "Kubernetes Container - Restart count",
            "condition_threshold": {
                "filter": (
                    'resource.type = "k8s_container" AND metric.type ='
                    ' "kubernetes.io/container/restart_count"'
                ),
                "aggregations": [
                    {
                        "alignment_period": "300s",
                        "per_series_aligner": "ALIGN_DELTA",
                    }
                ],
                "comparison": "COMPARISON_GT",
                "threshold_value": 1,
                "duration": "0s",
                "trigger": {"count": 1},
            },
        }
    ],
    notification_channels=[alert_email_channel.name],
    alert_strategy={
        "auto_close": "259200s",
        "notification_prompts": ["OPENED"],
    },
    documentation={
        "content": (
            "A pod in the cluster has restarted multiple times, indicating a"
            " possible crash loop.\n\nTo find the problem pod:\nkubectl get"
            " pods -A | grep -v Running\n\nTo see recent events:\nkubectl get"
            " events -A --sort-by='.lastTimestamp' | tail -20\n\nTo get logs"
            " from the crashing container:\nkubectl logs -n <namespace>"
            " <pod-name> --previous"
        ),
        "mime_type": "text/markdown",
        "subject": "GCP Pod Crash Loop",
    },
)

# Export cluster info
pulumi.export("cluster_name", main_cluster.name)
pulumi.export("cluster_endpoint", main_cluster.endpoint)
pulumi.export(
    "registry_url",
    container_registry.id.apply(
        lambda id: f"{region}-docker.pkg.dev/{project}/containers"
    ),
)
