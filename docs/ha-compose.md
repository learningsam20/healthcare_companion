# Local app-tier HA (Compose)

Data plane remains **single** Postgres / Redis / MinIO. This overlay only proves
API multi-replica + shared Postgres checkpointer behind nginx.

```bash
export COMPOSE_FILE=docker-compose.yml:docker-compose.ha.yml
docker compose --profile minimal up -d --scale api=2
./scripts/compose-ha-smoke.sh
```

Requirements:

- `HA_MODE=true` and `CHECKPOINTER_REQUIRED=true` (set by the overlay)
- `/readyz` fails if the checkpointer is missing
- Host API port is served by `api-lb` (nginx), not a single `api` container

K8s architecture artefact: `deploy/k8s/overlays/ha/`.
