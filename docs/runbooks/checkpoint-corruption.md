# Stale or corrupt scribe run or draft checkpoint

| Field | Value |
|---|---|
| Alert | Scribe run stuck in `running`; draft missing or malformed; schema/grounding failure; suspected wrong signature |
| Severity | S2 (S1 if a corrupt or stale draft was signed, or note integrity is in doubt) |
| Owner | E1 agent/product + clinical owner; E2 for API/database repair |
| Last reviewed | 2026-10-25 |

## Symptom

- The Scribe page shows a spinner for a run that has been `running` for more than a few minutes.
- `GET /api/v1/scribe/runs/{run_id}` returns `status: running`, `completed_at: null` and no draft.
- A run fails with `model_unavailable`, `transcript_too_long`, `draft_invalid_json`, `draft_schema_invalid`, `draft_citation_unknown`, `medicine_unsourced` or `medicine_ungrounded`.
- A `draft` run returns no draft, a malformed draft, citations to non-existent turns, or unsourced lines the doctor cannot resolve.
- A signed note's content or sources do not match the reviewed draft.

## Impact

There is **no LangGraph checkpoint store and no resume**. The graph compiles without a checkpointer; the durable state is the `scribe_runs`, `scribe_drafts` and `scribe_sources` rows. A `running` row left behind by an API crash cannot be resumed, cancelled, rejected or closed through the API.

A stale `running` run blocks a new run (`409 scribe_run_active`), a new transcript upload and encounter close. A failed run raises a doctor review task due in four hours. Signing is the highest-risk action: it creates a clinical note, version, hash and source snapshot, so a bad draft must never be signed to "unblock" the encounter.

## First five minutes

1. Confirm the API and its restart state, then read logs for the run window:
   ```bash
   ./scripts/status.sh
   ./scripts/logs.sh --service api --since 30m --no-follow
   ```
   A restart or request timeout around `started_at` is the usual cause of a stale `running` row.
2. In **Scribe**, open the encounter and record the run ID, revision, status, error code, model alias, prompt version and start/completion times. Tell the doctor not to sign.
3. Count runs and drafts by state without selecting draft content:
   ```bash
   docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT status, error_code, count(*)
     FROM scribe_runs GROUP BY 1, 2 ORDER BY 3 DESC;
   SELECT r.id, r.status, r.error_code, r.model_alias, r.revision,
          r.started_at, r.completed_at, count(d.id) AS drafts,
          max(d.revision) AS latest_draft_revision
     FROM scribe_runs r LEFT JOIN scribe_drafts d ON d.run_id = r.id
    GROUP BY r.id ORDER BY r.started_at DESC LIMIT 20;
   SQL
   ```
4. Check for API OOM/restart, a model timeout, or a transcript over the 6,000-character graph limit.
5. Freeze prompt/model/config changes and preserve the run, drafts and audit rows. Do not delete a bad draft to "retry".

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| `running` for >10 min, no draft, no `completed_at` | API process died or timed out mid-graph; no checkpoint/resume | keep the draft unsigned; escalate for a controlled repair; do not update `scribe_runs` by hand |
| `failed` with `model_unavailable` | local model/gateway unavailable | follow [model-outage.md](./model-outage.md); re-run after the gateway is healthy |
| `failed` with `transcript_too_long` | transcript exceeds the 6,000-character local-model window | upload a shorter/corrected manual transcript; start a new run |
| `failed` with `draft_invalid_json`/`draft_schema_invalid`/`draft_citation_unknown` | model output failed hard validation; nothing was persisted | re-run; repeated failures go to E1 with prompt/model/version details |
| `failed` with `medicine_unsourced`/`medicine_ungrounded` | a medicine or dose was not supported by the transcript | re-run; if it repeats, the doctor enters a grounded draft manually and rejects the run |
| `draft` missing while status is `draft` | database/application inconsistency | preserve rows, do not sign, escalate to E2/E1 |
| Draft shows `[doctor to specify]` or unsourced badges | expected grounding guard, not corruption | doctor edits and re-grounds, or rejects and re-runs; never sign unresolved unsourced content |
| `blocked` with `red_flag_ack_required` | emergency red flag detected before drafting | acknowledge the red flag in the UI; the graph re-runs with acknowledgement |
| Signed note content/source mismatch | wrong sign action or corrupt data | S1; preserve the signed version and escalate to the clinical/security owner |

## Mitigation

- **Stale `running` run:** there is no supported cancel/reset endpoint. Keep the encounter open, preserve evidence and escalate. If care cannot wait, the clinician documents under the clinic's approved downtime procedure; do not fabricate a draft or edit the database. Engineering must add a reviewed reconciler before this state can be repaired in-product.
- **Failed run:** correct the cause, then start a new run from a `ready` transcript. `start_run` allows a new run after `failed` and increments the revision; if the previous run was rejected, its reason is passed to the model as feedback.
- **Bad draft:** use **Reject** with a category and comment, or **Edit draft** and save. Editing re-grounds the content and creates a new draft revision; both actions are audited. Do not sign a draft with unresolved unsourced lines.
- **Oversized transcript:** manual transcripts accept at most 400 turns and 4,000 characters per turn, but the graph limits the joined transcript to 6,000 characters. Split the encounter or shorten the transcript, then re-run.
- **Badly signed note:** the author doctor uses `POST /api/v1/scribe/notes/{note_id}/corrections` to create a new version; the original version and hash remain. The clinical owner approves the correction. Never edit note versions in the database.

## Rollback

A prompt/model or API regression can be rolled back, but a rollback does **not** resume a stale run:

```bash
kubectl -n sahyog rollout undo deployment/api
kubectl -n sahyog rollout status deployment/api
```

For Compose, redeploy the last recorded API image; `restart.sh` keeps the old environment. Revert prompt/model config in git and restart the API only after preserving the failed run and trace IDs.

Never roll back by deleting runs/drafts or by restoring the database over a signed note. Use the correction workflow for a signed error.

## Evidence to capture

- Run ID, revision, status, error code, model alias, prompt version, start/completion times and trace ID.
- Draft revision count, source counts by status (including unsourced) and transcript turn/character counts. Do not copy transcript or draft text.
- Audit actions: `scribe.draft_created`, `scribe.run_failed`, `scribe.draft_edited`, `scribe.draft_rejected`, `scribe.red_flag_acknowledged`, `note.signed`.
- API restart/OOM evidence and the request window; command outputs with identifiers redacted.
- If a note was signed: note ID, version, content hash, correction version and clinical/security approval.
- Preserve the bad run and draft rows even after a new run is created.

## Escalation

E1 owns the graph, prompt and model behaviour; E2 owns API/database repair and must approve any reconciler; the clinical owner is notified immediately if care is blocked or a bad note was signed; security/compliance is notified if signature integrity or provenance is in doubt. Follow [incident-response.md](./incident-response.md) for severity, client notification and post-incident review.
