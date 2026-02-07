"""
Deployment status and promotion helper for GKE services.

Usage:
    uv run deploy.py status <app>     # Show current images for staging and prod
    uv run deploy.py promote <app>    # Compare staging vs prod, offer to promote

Examples:
    uv run deploy.py status fitness-api
    uv run deploy.py promote fitness-dashboard
"""

import subprocess
import sys
import re

REGISTRY = "us-central1-docker.pkg.dev/ethans-services/containers"


def run(cmd: list[str]) -> str:
    """Run a command and return stdout."""
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_deployed_images(namespace: str) -> set[str]:
    """Get all unique images currently deployed in a namespace."""
    try:
        # Get images from all pods, space-separated
        output = run([
            "kubectl", "get", "pods", "-n", namespace,
            "-o", "jsonpath={.items[*].spec.containers[*].image}"
        ])
        if not output:
            return set()
        # Split on whitespace and return unique images
        return set(output.split())
    except SystemExit:
        return set()


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


def status(app: str) -> None:
    """Show current deployment status for an app."""
    staging_images = get_deployed_images(f"{app}-staging")
    prod_images = get_deployed_images(f"{app}-prod")

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
        print(f"\n⚠ Staging has an image mismatch (deployment in progress?)")
    elif len(prod_images) > 1:
        print(f"\n⚠ Prod has an image mismatch (deployment in progress?)")
    elif staging_tag and prod_tag:
        staging_sha = extract_sha(staging_tag)
        prod_sha = extract_sha(prod_tag)
        if staging_sha and prod_sha:
            if staging_sha == prod_sha:
                print(f"\n✓ In sync")
            else:
                # Determine what the new prod tag would be
                uses_suffix = "-staging" in staging_tag or "-prod" in prod_tag
                new_prod_tag = f"{staging_sha}-prod" if uses_suffix else staging_sha
                print(f"\n✗ Out of sync")
                print(f"  To promote: uv run deploy.py promote {app}")
                print(f"  This will deploy {new_prod_tag} to prod")
    print()


def promote(app: str) -> None:
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
        print(f"Error: Staging has an image mismatch (deployment in progress?)")
        print("  Images found:")
        for img in sorted(staging_images):
            print(f"    - {extract_tag(img)}")
        print("\nWait for the deployment to complete before promoting.")
        sys.exit(1)

    if len(prod_images) > 1:
        print(f"Warning: Prod has an image mismatch (deployment in progress?)")
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
    
    # Determine if this app uses suffixed tags
    uses_suffix = "-staging" in staging_tag or "-prod" in prod_tag
    
    if uses_suffix:
        new_prod_tag = f"{staging_sha}-prod"
    else:
        new_prod_tag = staging_sha
    
    image_base = f"{REGISTRY}/{app}"
    new_prod_image = f"{image_base}:{new_prod_tag}"
    
    print(f"\n→ Promote prod to: {new_prod_tag}")
    response = input("\nProceed? [y/N] ").strip().lower()
    
    if response != "y":
        print("Aborted.")
        return
    
    # Run argocd app set
    argocd_app = f"{app}-prod"
    cmd = [
        "argocd", "app", "set", argocd_app,
        "--kustomize-image", f"{image_base}={new_prod_image}",
    ]
    
    print(f"\nRunning: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    
    if result.returncode != 0:
        print(f"\n✗ Promotion failed (exit code {result.returncode})")
        sys.exit(1)
    
    print(f"\n✓ Promoted {app} prod to {new_prod_tag}")
    print("  (ArgoCD will sync automatically)")


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]
    app = sys.argv[2]

    if command == "status":
        status(app)
    elif command == "promote":
        promote(app)
    else:
        print(f"Unknown command: {command}")
        print("Available commands: status, promote")
        sys.exit(1)


if __name__ == "__main__":
    main()
