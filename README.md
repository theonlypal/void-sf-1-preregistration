# VOID-SF-1

Rayan Pal

Preregistration, frozen runner and offline verifier for a 360-request test of
whether the Salesforce Models API route (Einstein Trust Layer, Bedrock-hosted,
inside the Salesforce Trust Boundary) preserves the zero-byte normal-stop
completion that Claude Opus 4.6 returns on null-concept inputs, compared with
the same model served directly by Anthropic under byte-identical messages.

- Model: Claude Opus 4.6 (`sfdc_ai__DefaultBedrockAnthropicClaude46Opus` / `claude-opus-4-6`).
- Routes: Salesforce Models API (Apex, through the Tooling API) and direct Anthropic.
- Inputs: three null concepts and three matched controls under the primary
  embodiment system prompt of the Cross-Vendor Semantic Void Matrix.
- Predictions are in `PREREG.md`, committed before any VOID-SF-1 inference.
- Sealed at tag v1.0.0, commit 3e4fae10980f56e7de1c7c4f3af7951d0d6939f8. DOI: https://doi.org/10.5281/zenodo.23988726

| File | Content |
|---|---|
| `PROTOCOL.md` | Models, routes, prompts, classification, measurements, controls |
| `PREDICTION_QUESTIONS.md` | The ten prediction questions |
| `PREREG.md` | Preregistered answers |
| `prompts.json` | Exact system prompt and inputs with lengths and SHA-256 |
| `SCHEDULE.json`, `SCHEDULE.sha256` | Ordered 360-slot schedule and hash |
| `voidsf.py` | Prompts, schedule, request builders, transports, classification, ledger, analysis |
| `runner.py` | Two-lane execution with raw receipts and a hash-chained event log; binds the run to this folder's SHA256SUMS (and commit when present) |
| `smoke.py` | Alias-serving probe and one `Be speech.` control per Sonnet smoke model per route on a Free org; never a study input |
| `verify.py` | Offline reconstruction of every class, count and ledger entry |
| `vendor/` | Byte-identical frozen Opus classifier; provenance in `NOTICE.md` |
| `smoke/` | Alias-serving probe and control receipts produced by the frozen `smoke.py` on a Free org, including the LLM_GATEKEEPER body for the Opus 4.6 alias |
| `tests/` | Offline checks |
| `SETUP.md` | Org tier requirement, app and credential setup; run commands |

License: Creative Commons Attribution 4.0 International, except the vendored
MIT-licensed classifier noted in `NOTICE.md`.
