# Supply-chain CI status (G-27 / G-37)

Recorded: `2026-10-31T12:46:46Z` (local operator pass).

## Digest capture

- Ran `scripts/pin-image-digests.sh` against the local Docker daemon.
- Evidence: [image-digests-20261031T124646Z.txt](./image-digests-20261031T124646Z.txt)
- Overlay notes: `docker-compose.digests.example.yml` (gitignored real overlay:
  `docker-compose.digests.yml`).
- Digests resolved for most Compose images already present locally.
- Still unavailable until pull/build: `ghcr.io/ggerganov/llama.cpp:server`,
  `neo4j:5.26.4`, `prom/alertmanager:v0.28.1`, `sahyog-mem0:local`.

## CI `supply-chain` job — `continue-on-error`

Source: `.github/workflows/ci.yml` job `supply-chain`
(`Semgrep, Trivy FS, SBOM (G-27/G-37)`).

| Step | `continue-on-error` | Notes |
|---|---|---|
| Semgrep (error severity) | **true** (advisory) | Not flipped to blocking this pass |
| Trivy filesystem scan | **true** (advisory) | Also sets `exit-code: "0"` |
| CycloneDX SBOM (Python) | **true** (advisory) | Writes under `docs/evidence/` when possible |
| Red-team corpus offline | false | Shape check; not Semgrep/Trivy |
| Nursing X-01 case count | false | Asserts 20 cases |

**Decision this pass:** leave Semgrep / Trivy / SBOM as advisory
(`continue-on-error: true`). This workspace has no GitHub remote/`gh` CI history to
prove those three steps are already green on `main`, so flipping them to blocking
would be unsafe guesswork. Flip only after a green advisory run is recorded.

## Not claimed

- Digest-pinned Compose is not the default runtime (example overlay only).
- No SBOM/signature/Trivy blocking gate.
- No pod-security exception register for third-party images.
