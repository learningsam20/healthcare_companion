# Clinical i18n report (G-01 / G-02)

- Generated: `2026-10-31T14:48:21Z`
- Review status: **unreviewed**
- Gaps: G-01 (translation coverage), G-02 (clinical language validation)

## Clinical reviewer sign-off

No approved clinical sign-off is on file.

- Detail: Sign-off file present but incomplete (need review_status=approved, approver.name, signed_at).
- To record approval: copy `docs/evidence/i18n-clinical-signoff.example.json` → `docs/evidence/i18n-clinical-signoff.json`, fill approver/signed_at, set `review_status` to `approved`, then re-run `scripts/i18n_safety_key_audit.py`.

Until then, hi/mr safety copy must **not** be claimed as clinically validated.

## Safety key inventory

- Locales scanned: en, hi, mr
- Safety keys found: **3**
- Red-flag rule IDs in config: **9**

| Key |
|---|
| `chat.redFlagBody` |
| `chat.redFlagTitle` |
| `scribe.redFlags` |

## Honesty

- This report surfaces sign-off status; it does not create approval.
- Key inventory is not linguistic QA.
- G-12 (medical-device validation) remains separate from G-01/G-02 copy review.
