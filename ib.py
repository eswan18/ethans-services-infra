"""
Deployment status and promotion helper for GKE services.

Usage:
    ib status               # Show status for all services
    ib status <app>         # Show current images for staging and prod
    ib status -q            # List out-of-sync services (* = mid-deploy)
    ib status <app> -q      # Exit 0 if in sync, 1 if not (minimal output)
    ib promote <app>        # Compare staging vs prod, offer to promote
    ib promote <app> -y     # Promote without confirmation

Examples:
    ib status
    ib status fitness-api
    ib status -q
    ib promote fitness-dashboard
"""

import json
import subprocess
import sys
import re

REGISTRY = "us-central1-docker.pkg.dev/ethans-services/containers"

SERVICES = [
    "asset-manager",
    "bifrost",
    "comms",
    "fitness-api",
    "fitness-dashboard",
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
    else:
        print(f"Unknown command: {command}")
        print("Available commands: status, promote")
        sys.exit(1)


if __name__ == "__main__":
    main()
