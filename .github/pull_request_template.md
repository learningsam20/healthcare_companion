<!--
Keep this template short. A PR that cannot answer a box either fixes it or records the
remaining gap in docs/gaps.md before review.
-->

## Summary

<!-- What changes, for whom, and why. Link the requirement or acceptance ID. -->

## Requirement and acceptance

- Requirement / acceptance ID:
- Routes or screens affected:
- Feature flag(s) added or changed (owner, environments, expiry):

## Safety checks

- [ ] No patient-identifying data added to logs, traces, analytics, exports or audit metadata.
- [ ] No new external egress; if egress is touched, the composite PII gate still fails closed.
- [ ] No direct model or tool provider call: LLM traffic goes through LiteLLM, tools through MCP.
- [ ] Consent/scope predicates unchanged, or the change includes a cross-patient test.
- [ ] No auth bypass, no test-only credential, no runtime mock of a real integration.
- [ ] New or changed flag registered; locked safety flags still locked.

## Verification

Paste the commands and result lines you actually ran.

```
./scripts/test.sh
./scripts/test.sh --postgres
./scripts/test.sh --contracts --i18n
./scripts/test.sh --e2e          # when a UI flow changed
uv run ruff check . && uv run ruff format --check . && uv run mypy ...
npm --prefix apps/web run typecheck && npm --prefix apps/web run build
```

- [ ] Happy path exercised.
- [ ] Authorization failure exercised.
- [ ] Validation failure exercised.
- [ ] Degradation exercised (provider/database/storage unavailable).

## Migration and rollback

- Migration revision:
- Forward-only and re-runnable on an empty and an existing database:
- Rollback / disable path:

## Documentation

- [ ] `docs/gaps.md` updated (new gap, closure evidence, or status change).
- [ ] `AI-COLLABORATION.md` has an entry for this change.
- [ ] Setup, architecture, design or plan updated where behaviour changed.
- [ ] `.env.example` updated for any new setting.
