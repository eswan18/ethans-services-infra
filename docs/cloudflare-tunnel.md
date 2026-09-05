# Cloudflare Tunnel routing

Pulumi manages the **cloudflared connector** running in the cluster (see
`__main__.py`), but the tunnel itself, its hostname routing, and the DNS
records are remotely-managed config living in the Cloudflare Zero Trust
dashboard. Nothing in this repo recreates them.

This file is the recovery input: after a cluster rebuild every service comes up
healthy and is **unreachable from the internet** until these hostnames exist
again. It is also the reference for "what is actually exposed publicly."

## This file is regenerated from the cluster, not from the dashboard

cloudflared receives its configuration from Cloudflare and logs it verbatim on
startup, so the live routing is recoverable without dashboard access, an API
token, or even a Cloudflare login:

```bash
kubectl logs -n cloudflared deploy/cloudflared | grep "Updated to new configuration"
kubectl logs -n cloudflared deploy/cloudflared | grep "Starting tunnel"   # tunnel ID
```

Re-run those and update this file whenever hostnames change. The `version=N`
in that log line increments on every dashboard edit, which is the cheapest
staleness check: if the live version is higher than the one recorded below,
this file is out of date.

**Caveat:** this reflects what the *running connector* was told. A hostname
configured in the dashboard but never pushed, or one with no DNS record, would
not appear — though neither would be reachable anyway, so neither matters for
recovery.

## Tunnel

| | |
|---|---|
| Tunnel ID | `444d86d4-1884-414d-a6bb-74c79e3fb2c8` |
| Config version | 24 (as of 2026-09-02) |
| WARP routing | disabled |
| Credential | token in the `cloudflared-token` secret, sourced from the dashboard and stored as the Pulumi stack secret `cloudflared-tunnel-token` |

## Public hostnames

Seven, all proxied through Cloudflare to in-cluster Services over the tunnel.
Recreate under **Networks → Tunnels → your tunnel → Public Hostname**.

| Public hostname | Service URL |
|---|---|
| `footstrike.run` | `http://footstrike-dashboard.footstrike-dashboard-prod.svc.cluster.local:80` |
| `api.footstrike.run` | `http://footstrike-api.footstrike-api-prod.svc.cluster.local:80` |
| `identity.ethanswan.com` | `http://identity.identity-prod.svc.cluster.local` |
| `assets.ethanswan.com` | `http://asset-manager.asset-manager-prod.svc.cluster.local` |
| `haruspex.fyi` | `http://haruspex.haruspex-prod.svc.cluster.local` |
| `bifrost.ethanswan.com` | `http://bifrost.bifrost-prod.svc.cluster.local` |

Plus a catch-all rule returning `http_status:404` for anything unmatched.

**`forecasting.ethanswan.com` is no longer in this table, and that is correct.**
The service moved to the `haruspex.fyi` apex in Sept 2026 and the old hostname
kept a duplicate tunnel route for a while, on the theory that removing it would
take the DNS record with it. The route was removed during the Sept 2026 rename
and the redirect kept working: a Redirect Rule in the `ethanswan.com` zone 301s
the old host (path-preserving) to the new domain, and Redirect Rules run at the
edge *before* origin selection, so the request never reaches the tunnel at all.

What the old hostname does still need is its **DNS record** — a name that does
not resolve cannot be redirected. That record has no tunnel route behind it and
should not get one; do not "fix" its absence from this table by recreating it.

Two cosmetic notes: the `ethanswan.com` and `haruspex.fyi` entries omit the
explicit `:80` that the `footstrike.run` entries carry — functionally identical,
since the Services listen on 80 and `http://` defaults there. And no entry sets
`originRequest` overrides, so all seven use Cloudflare's defaults.

## DNS

Each hostname is a **proxied** record pointing at
`444d86d4-1884-414d-a6bb-74c79e3fb2c8.cfargotunnel.com`. Because they are
proxied, `dig` returns Cloudflare edge addresses (`104.21.x` / `172.67.x`)
rather than the CNAME target — that is expected and not a misconfiguration.

Zones: `footstrike.run`, `ethanswan.com` and `haruspex.fyi`.

`haruspex.fyi` also carries a **grey-cloud (DNS-only)** `staging` CNAME to
`staging-ingress.tailc06f30.ts.net`, which has nothing to do with this tunnel —
it is the shared Tailscale ingress path described under "Deliberately not
exposed" below. Do not orange-cloud it: Cloudflare's edge cannot route to a
tailnet address.

## Deliberately not exposed

- **comms** has a ClusterIP Service but no public hostname. It is a background
  worker that only pulls from Pub/Sub and sends mail; it has no ingress by
  design. Do not add a hostname for it.
- **Staging** does not use this tunnel at all. Staging hosts are tailnet-only,
  reached through the Tailscale operator — `*.tailc06f30.ts.net`, plus the
  custom-domain staging hosts served by the shared `staging-ingress` Tailscale
  LoadBalancer. Different path entirely; nothing here applies to them.

## Retired

`fitness.ethanswan.com` and `fitness-api.ethanswan.com` were the pre-rename
hostnames. Both now have **no DNS records** and no tunnel entry — fully
retired, not merely unused. Do not recreate them.

## If you ever want this in IaC

It is feasible with the Cloudflare Pulumi provider
(`cloudflare.ZeroTrustTunnelCloudflaredConfig` for the ingress rules, plus DNS
records). It was deliberately not done: it costs a new provider dependency and
a long-lived Cloudflare API token to store and rotate, with prod ingress as the
blast radius, in exchange for avoiding a rebuild step that takes about twenty
minutes from the table above. Revisit if hostnames start changing often enough
that this file drifts.
