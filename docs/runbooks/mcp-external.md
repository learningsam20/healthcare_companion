# External MCP listener (G-14)

**Status:** read-only demo listener. No named partner, no per-consumer credential issuance and no certification. Default **off**.

## Where it runs

| Target | Present? | Notes |
|---|---|---|
| Docker Compose | Yes — service `mcp-external`, profile `core`, host port `${MCP_EXTERNAL_PORT:-5734}` (loopback only) | Reads `EXTERNAL_MCP_ENABLED` (default `false`). |
| Kubernetes pilot/production overlays | **No** | `deploy/k8s` has no `mcp-external` Deployment/Service/NetworkPolicy. Exposing it on a cluster is a separate, unreviewed change; do not claim K8s support. |

## Kill switch (two settings — keep them aligned)

1. **Enforcement:** `EXTERNAL_MCP_ENABLED` on the `mcp-external` container. `false` → empty `/tools` catalogue, `404 tool_not_found` on invoke.
2. **Platform visibility:** startup feature flag `external_mcp` (`FEATURE_EXTERNAL_MCP`). Shown in the admin flags list and reported by `GET /api/v1/meta` as `adapters.external_mcp` (`enabled|disabled`, `mode: read_only`, `certified: false`) and in Settings → Integrations.

The flag is a *startup* class flag; changing either value needs a container restart. `/meta` does not probe the container, so a mismatch is possible — verify with `curl http://127.0.0.1:5734/tools` (`kill_switch.enabled`).

To stop external access immediately: set `EXTERNAL_MCP_ENABLED=false`, recreate `mcp-external`, confirm `/tools` returns `"tools": []`, then set `FEATURE_EXTERNAL_MCP=false` and restart the API.

## Versioning and quotas

Configured in [`config/external_mcp.yaml`](../../config/external_mcp.yaml) (override with `EXTERNAL_MCP_CONFIG`).

- `GET /tools` reports `api_version`, `supported_versions`, per-tool versions, `kill_switch`, `quota`, `read_only: true`, `certified: false`.
- Callers may send `X-Sahyog-Api-Version`; an unsupported value returns `400 unsupported_api_version`. Responses carry `X-Sahyog-Api-Version`.
- Quota: sliding window requests/minute per signed `actor_subject`; exceed → `429 rate_limited` with `Retry-After`. **In-process, per replica** — N replicas allow N× the rate. There is no shared (Redis) limiter yet.

## Conformance

`uv run pytest services/mcp-external -q` (also a named CI step). It covers kill switch, missing/forged signed context, valid context, quota window, 429/`Retry-After`, version headers. It is an interim control and not partner certification.

## Still open (X-03)

Named consumer, per-consumer credentials, shared quota store, support/SLA model, developer contract, security review, Kubernetes manifests.
