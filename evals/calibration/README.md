# Judge calibration

`./scripts/calibrate-judge.sh` defaults to a fixture-consistency smoke. It copies
`reviewer_template.json`, fills labels from the authored fixture, and writes
`reviewer_provisional.json` with:

- `attested_human_review=false`
- `review_mode=fixture_consistency_smoke`
- `calibrated_by=provisional_fixture`

That provisional smoke checks plumbing only. It is **not human calibration**,
does not close G-16, and the harness calibration artifact remains `pending`.

For G-16 closure, have a named human reviewer independently label every item
against the rubric, attest the completed file with
`attested_human_review=true`, and run:

```bash
REVIEWER_FILE=/absolute/path/to/reviewer.json ./scripts/calibrate-judge.sh
```

The harness validates the attestation, reviewer identity, label values, and
coverage. A reviewed artifact still does not claim clinical validation; judge
agreement requires a separate complete judge-label file.
