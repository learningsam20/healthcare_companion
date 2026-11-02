# Ingestion or OCR/STT failure

| Field | Value |
|---|---|
| Alert | Document `failed` with an extraction error; transcript `failed` with `stt_unavailable`/`stt_empty`; image or scanned PDF cannot be indexed |
| Severity | S2 (S1 if the document or audio is needed for immediate care and no manual alternative exists) |
| Owner | E1 agent/product + E4 integrations; E2 for worker/storage; clinical owner for care impact |
| Last reviewed | 2026-10-25 |

## Symptom

- An uploaded image or scanned PDF becomes `failed` with `ocr_not_configured` or `no_extractable_text`.
- A PDF becomes `failed` with `pdf_unreadable`, `unsupported_content_type`, `document_too_large` or `ingestion_failed`.
- A document stays `queued`/`processing`; see [queue-backlog.md](./queue-backlog.md).
- Audio upload completes with a transcript `failed` and `stt_unavailable`, `stt_empty` or `audio_unreadable`.
- The record cannot be found by search or RAG because no chunks were indexed.

## Impact

OCR is **not implemented** in this build. Image uploads pass MIME/size validation but extraction raises `ocr_not_configured`; a scanned PDF with no text layer raises `no_extractable_text`. Retrying either error cannot succeed.

`mcp-stt` registers **no transcription tool** because faster-whisper weights are not bundled; the service returns an empty catalogue rather than a fabricated transcript. Audio completion therefore fails `stt_unavailable` (or `stt_empty` for silence). The supported fallback is a manual transcript or a text-based PDF, clearly marked as the source.

A failed ingestion must stay visibly failed. Never create chunks, blank text, placeholder answers or a guessed transcript to make the record look available.

## First five minutes

1. Confirm the API/worker and dependency state:
   ```bash
   ./scripts/status.sh
   ./scripts/logs.sh --service worker --since 30m --no-follow
   ./scripts/logs.sh --service api --since 30m --no-follow
   ```
2. Record the resource ID, status, error code, content type and size from **Records → Documents** or **Scribe → Transcript**. Do not copy extracted text or audio content.
3. Count failures by code and type without selecting content:
   ```bash
   docker compose exec -T postgres sh -lc 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
   SELECT status, error_code, content_type, count(*)
     FROM documents GROUP BY 1, 2, 3 ORDER BY 4 DESC;
   SELECT status, error_code, source, count(*)
     FROM transcripts GROUP BY 1, 2, 3 ORDER BY 4 DESC;
   SQL
   ```
4. Check whether the STT service is running and what it advertises:
   ```bash
   curl -fsS http://localhost:5716/healthz
   curl -fsS http://localhost:5716/tools | python3 -m json.tool
   ```
   An empty `tools` list is the expected state in this build, not a transient outage. A connection failure means `mcp-stt` is down in the `core`/`full` profile.
5. Confirm the upload is within policy: PDF/PNG/JPEG only, 25 MB document limit, audio up to 200 MB. An image being accepted does not mean OCR exists.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| Image document `ocr_not_configured` | OCR is absent by design | do not retry; request a text PDF or use the manual workflow |
| PDF `no_extractable_text` | scanned/image-only, blank or textless PDF | request a text-layer PDF; retry only after a corrected file |
| PDF `pdf_unreadable` | corrupt, encrypted or unsupported PDF | ask for a re-export; upload as a new document |
| `unsupported_content_type` | MIME does not match PDF/PNG/JPEG | convert the file; do not rename an unsupported file |
| `document_too_large` | exceeds 25 MB upload or 4,000 chunk cap | split the document; do not raise limits under pressure |
| `storage_unavailable`/`ingestion_failed` | transient MinIO/worker/model failure | retry the ingest endpoint after the dependency is healthy |
| Transcript `stt_unavailable` | `mcp-stt` unreachable, empty tool catalogue, or MCP error | use a manual transcript; restart `mcp-stt` only if it is down |
| Transcript `stt_empty` | silence, no speech or unusable audio | re-record or enter a verified manual transcript |
| Transcript `audio_unreadable` | corrupt/unsupported audio or failed upload | re-record; do not guess content |
| `malware_detected`/`quarantined` | scanner verdict | stop and escalate to security; this is not an OCR issue |

## Mitigation

- **Manual transcript (supported):** open the encounter in **Scribe → Add transcript**, choose the language, add speaker turns and submit. The encounter must be active, have no signed note and no `running`/`draft`/`blocked` run. A failed or rejected run does not block it. Manual transcripts allow 1–400 turns and 4,000 characters per turn; the graph still caps the joined transcript at 6,000 characters.
- **Manual/document fallback:** re-upload a text-layer PDF. Do not photograph pages, paste unverified OCR output from another tool, or attach a transcript as a "document" unless the clinic's policy allows it.
- **Transient retry:** use **Retry ingest** in Records or:
  ```bash
  curl -fsS -X POST http://localhost:5706/api/v1/records/documents/<document-id>/ingest \
    -H "Authorization: Bearer <operator-token>"
  ```
  This is rejected for `processing` and quarantined documents. If enqueue fails, the API runs ingestion in-process; do not restart the API until it settles.
- **STT service:** if `mcp-stt` is down, restart it with `./scripts/restart.sh --service mcp-stt`. Confirm Whisper weights are present and `/healthz` is healthy; if the adapter is unavailable, audio completion fails with `stt_unavailable` and W3 still accepts a manual transcript (G-05/G-29).
- **Fail visible:** keep the `failed` status and error code. Do not SQL-update `documents.status`, insert chunks, or write a transcript the clinician did not provide.

## Rollback

There is no rollback for a deterministic extraction failure; upload a corrected file as a new document and leave the failed row as evidence. Do not delete failed or quarantined documents.

For a code/model regression in extraction or embeddings, roll back the API/worker image and re-drive only transient failures:

```bash
kubectl -n sahyog rollout undo deployment/api deployment/worker
kubectl -n sahyog rollout status deployment/api deployment/worker
```

A rollback does not make scanned images processable; OCR is still absent. Never restore the database over a document or transcript that is part of an open clinical encounter.

## Evidence to capture

- Document/transcript ID, MIME type, size, status/error code, page/chunk counts and retry timestamps.
- The `/tools` response showing an empty or populated catalogue; no audio or extracted text.
- Worker job ID, trace ID and log event names (`records.document.failed`, `transcript.stt_failed`); no content.
- Audit actions `records.document_failed`, `records.document_reingest_requested`, `records.document_indexed`, `transcript.uploaded`.
- The manual-transcript fallback used, who entered it and when; no fabricated source claim.
- If care was delayed, the clinical hand-off and downtime procedure used.

## Escalation

E1 owns OCR/STT capability and the manual fallback contract; E4 owns MCP/STT integration and storage; E2 owns worker/queue and database state; the clinical owner decides the care fallback. Security/compliance is notified for malware/quarantine or any proposal to send a document to an external OCR service. Record the missing OCR/STT capability as a product gap rather than improvising around it.
