# Chat interrupt HA soak evidence

Run against two API replicas that share Postgres (checkpointer required):

```bash
export API_A=http://localhost:5706
export API_B=http://localhost:5708   # second replica
export TOKEN=...                     # patient bearer
export SOAK_WRITE_EVIDENCE=1
./scripts/chat-interrupt-ha-soak.sh
```

Successful runs write `docs/evidence/chat-interrupt-ha-soak-<UTC>.json` with `status=passed`.
Until that file exists from a dual-replica environment, G-46 remains **Mitigated** (harness present, soak not attached).
