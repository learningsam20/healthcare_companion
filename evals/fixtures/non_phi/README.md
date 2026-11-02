# Non-PHI audio fixtures (G-05 foundations)

Everything here is synthetic and contains only public phrases. See
`manifest.json` for provenance (`synthetic_tts`) and checksums.

| Audio | Reference | Notes |
|---|---|---|
| `pangram_en_tts.wav` | `pangram_en_tts.reference.txt` | macOS `say` TTS of a public-domain pangram, 16 kHz mono |

## Use

```bash
# mcp-stt must be up (core profile) and able to fetch the audio over http(s).
python3 -m http.server 8099 --directory evals/fixtures/non_phi &
scripts/stt_wer_live.sh \
  --audio http://host.docker.internal:8099/pangram_en_tts.wav \
  --reference "$(cat evals/fixtures/non_phi/pangram_en_tts.reference.txt)" \
  --language en-US --id pangram-en-tts
```

## Honest limits

- This is a **contract/smoke fixture**, not a WER benchmark. TTS audio is far
  cleaner than clinic speech and is English only.
- Do not commit a score from this file as G-05 closure. Closure needs
  human-recorded (or public-corpus) multilingual audio with human reference text.
- Never add real consultations or any PHI here; PHI audio belongs in the
  restricted store, not in git.
