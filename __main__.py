"""Infrastructure for Ethan's Services in GCP"""

import pulumi
from pulumi import ResourceOptions
from pulumi_gcp import container, serviceaccount, projects, artifactregistry, secretmanager, cloudbuild

# Configuration
project = "ethans-services"
region = "us-central1"
zone = "us-central1-a"

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
main_cluster = container.Cluster("main-cluster",
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
    location="us-central1-a",
    logging_config={
        "enable_components": [
            "SYSTEM_COMPONENTS",
            "WORKLOADS",
        ],
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
        "enable_components": [
            "SYSTEM_COMPONENTS",
            "STORAGE",
            "HPA",
            "POD",
            "DAEMONSET",
            "DEPLOYMENT",
            "STATEFULSET",
            "JOBSET",
            "CADVISOR",
            "KUBELET",
            "DCGM",
        ],
        "managed_prometheus": {
            "enabled": True,
        },
    },
    name="main-cluster",
    network="projects/ethans-services/global/networks/default",
    network_policy={
        "enabled": False,
        "provider": "PROVIDER_UNSPECIFIED",
    },
    networking_mode="VPC_NATIVE",
    node_config={
        "boot_disk": {
            "disk_type": "pd-balanced",
            "size_gb": 20,
        },
        "disk_size_gb": 20,
        "disk_type": "pd-balanced",
        "image_type": "COS_CONTAINERD",
        "kubelet_config": {
            "insecure_kubelet_readonly_port_enabled": "FALSE",
            "max_parallel_image_pulls": 2,
        },
        "logging_variant": "DEFAULT",
        "machine_type": "e2-medium",
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
            "goog-gke-node-pool-provisioning-model": "spot",
        },
        "service_account": "default",
        "spot": True,
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
            "name": "spot-pool-medium",
            "network_config": {
                "pod_ipv4_cidr_block": "10.36.0.0/14",
                "pod_range": "gke-main-cluster-pods-3fd139f8",
            },
            "node_config": {
                "boot_disk": {
                    "disk_type": "pd-balanced",
                    "size_gb": 20,
                },
                "disk_size_gb": 20,
                "disk_type": "pd-balanced",
                "image_type": "COS_CONTAINERD",
                "kubelet_config": {
                    "insecure_kubelet_readonly_port_enabled": "FALSE",
                    "max_parallel_image_pulls": 2,
                },
                "logging_variant": "DEFAULT",
                "machine_type": "e2-medium",
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
                    "goog-gke-node-pool-provisioning-model": "spot",
                },
                "service_account": "default",
                "spot": True,
                "workload_metadata_config": {
                    "mode": "GKE_METADATA",
                },
            },
            "node_count": 1,
            "node_locations": ["us-central1-a"],
            "upgrade_settings": {
                "max_surge": 1,
            },
            "version": "1.33.5-gke.2118001",
        },
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
            "node_locations": ["us-central1-a"],
            "upgrade_settings": {
                "max_surge": 1,
            },
            "version": "1.33.5-gke.2118001",
        },
    ],
    node_version="1.33.5-gke.2118001",
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
    project="ethans-services",
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
    subnetwork="projects/ethans-services/regions/us-central1/subnetworks/default",
    workload_identity_config={
        "workload_pool": "ethans-services.svc.id.goog",
    },
    opts = pulumi.ResourceOptions(protect=True),
)

# Service Accounts
identity_staging_sa = serviceaccount.Account("identity-staging-sa",
    account_id="identity-staging-sa",
    display_name="Identity Staging Service Account",
    project="ethans-services",
)
identity_prod_sa = serviceaccount.Account("identity-prod-sa",
    account_id="identity-prod-sa",
    display_name="Identity Prod Service Account",
    project="ethans-services",
)
fitness_api_staging_sa = serviceaccount.Account("fitness-api-staging-sa",
    account_id="fitness-api-staging-sa",
    display_name="Fitness API Staging",
    project="ethans-services",
)
fitness_api_prod_sa = serviceaccount.Account("fitness-api-prod-sa",
    account_id="fitness-api-prod-sa",
    display_name="Fitness API Prod",
    project="ethans-services",
)
argocd_image_updater_sa = serviceaccount.Account("argocd-image-updater-sa",
    account_id="argocd-image-updater-sa",
    display_name="ArgoCD Image Updater",
    project="ethans-services",
)

# Workload Identity bindings
fitness_api_prod_wi = serviceaccount.IAMMember("fitness-api-prod-workload-identity",
    service_account_id=fitness_api_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[fitness-api-prod/fitness-api-prod-ksa]",
)
fitness_api_staging_wi = serviceaccount.IAMMember("fitness-api-staging-workload-identity",
    service_account_id=fitness_api_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[fitness-api-staging/fitness-api-staging-ksa]",
)
identity_prod_wi = serviceaccount.IAMMember("identity-prod-workload-identity",
    service_account_id=identity_prod_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[identity-prod/identity-prod-ksa]",
)
identity_staging_wi = serviceaccount.IAMMember("identity-staging-workload-identity",
    service_account_id=identity_staging_sa.name,
    role="roles/iam.workloadIdentityUser",
    member=f"serviceAccount:{project}.svc.id.goog[identity-staging/identity-staging-ksa]",
)

# Secret Manager access
fitness_api_prod_secrets = projects.IAMMember("fitness-api-prod-secret-access",
    project=project,
    role="roles/secretmanager.secretAccessor",
    member=fitness_api_prod_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)
fitness_api_staging_secrets = projects.IAMMember("fitness-api-staging-secret-access",
    project=project,
    role="roles/secretmanager.secretAccessor",
    member=fitness_api_staging_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Artifact Registry access for ArgoCD Image Updater
argocd_image_updater_ar = projects.IAMMember("argocd-image-updater-ar-access",
    project=project,
    role="roles/artifactregistry.reader",
    member=argocd_image_updater_sa.email.apply(lambda email: f"serviceAccount:{email}"),
)

# Secret Manager secrets (structure only - values managed outside Pulumi)
secret_names = [
    # fitness-api prod
    "fitness_api_prod_database_url",
    "fitness_api_prod_google_client_id",
    "fitness_api_prod_google_client_secret",
    "fitness_api_prod_hevy_api_key",
    "fitness_api_prod_strava_client_id",
    "fitness_api_prod_strava_client_secret",
    "fitness_api_prod_trmnl_api_key",
    # fitness-api staging
    "fitness_api_staging_database_url",
    "fitness_api_staging_google_client_id",
    "fitness_api_staging_google_client_secret",
    "fitness_api_staging_hevy_api_key",
    "fitness_api_staging_strava_client_id",
    "fitness_api_staging_strava_client_secret",
    "fitness_api_staging_trmnl_api_key",
    # identity prod
    "identity_prod_database_url",
    "identity_prod_jwt_private_key",
    "identity_prod_resend_api_key",
    "identity_prod_storage_access_key",
    "identity_prod_storage_secret_key",
    "identity_prod_storage_token",
    # identity staging
    "identity_staging_admin_database_url",
    "identity_staging_database_url",
    "identity_staging_jwt_private_key",
    "identity_staging_resend_api_key",
    "identity_staging_storage_access_key",
    "identity_staging_storage_secret_key",
    "identity_staging_storage_token",
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

# Cloud Build triggers
fitness_api_build = cloudbuild.Trigger("fitness-api-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="fitness-api",
        owner="eswan18",
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="fitness-api-build",
    project=project,
    service_account=f"projects/{project}/serviceAccounts/754418346661-compute@developer.gserviceaccount.com",
)
fitness_dashboard_build = cloudbuild.Trigger("fitness-dashboard-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="fitness-dashboard",
        owner="eswan18",
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="fitness-dashboard-build",
    project=project,
    service_account=f"projects/{project}/serviceAccounts/754418346661-compute@developer.gserviceaccount.com",
)
identity_build = cloudbuild.Trigger("identity-build",
    filename="cloudbuild.yaml",
    github=cloudbuild.TriggerGithubArgs(
        name="identity",
        owner="eswan18",
        push=cloudbuild.TriggerGithubPushArgs(
            branch="^main$",
        ),
    ),
    name="identity-build",
    project=project,
    service_account=f"projects/{project}/serviceAccounts/754418346661-compute@developer.gserviceaccount.com",
)

# Export cluster info
pulumi.export("cluster_name", main_cluster.name)
pulumi.export("cluster_endpoint", main_cluster.endpoint)
pulumi.export("registry_url", container_registry.id.apply(
    lambda id: f"{region}-docker.pkg.dev/{project}/containers"
))
