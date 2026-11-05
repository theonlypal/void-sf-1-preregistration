# VOID-SF-1: Does the Salesforce Einstein Trust Layer route preserve Claude Opus 4.6's zero-byte terminal state? A frozen same-bytes comparison

## Research question
Under byte-identical system and user messages, does Claude Opus 4.6 served
through the Salesforce Models API (Einstein Trust Layer, Amazon Bedrock, inside
the Salesforce Trust Boundary) produce the same zero-byte normal-stop
completions on null-concept inputs as Claude Opus 4.6 served directly by
Anthropic?

## Model
| Study id | Salesforce alias (requested) | Served model expected from the route | Direct Anthropic id |
|---|---|---|---|
| opus-4-6 | sfdc_ai__DefaultBedrockAnthropicClaude46Opus | anthropic.claude-opus-4-6 | claude-opus-4-6 |

Salesforce lists this alias on its supported-models page
(https://developer.salesforce.com/docs/ai/agentforce/guide/supported-models.html)
as served on Amazon Bedrock inside the Salesforce Trust Boundary. The expected
served-model string is a prediction (question 6): it follows the pattern the
same route reports for the Sonnet aliases (`anthropic.claude-sonnet-4-6`,
`anthropic.claude-sonnet-5`) in `smoke/SUMMARY.json`.

## Routes
| Route | Mechanism | Request shape | Output ceiling |
|---|---|---|---|
| SF | Salesforce Models API, Apex `aiplatform.ModelsAPI.createChatGenerations`, invoked through the Tooling API `executeAnonymous` endpoint of the executing org | `messages: [{role: system}, {role: user}]` and nothing else; no sampling or token parameter is set | whatever the route applies by default; not set by this study |
| DA | Anthropic Messages API, `POST https://api.anthropic.com/v1/messages`, `anthropic-version: 2023-06-01` | `system` + one user message; `max_tokens: 4000`; temperature and thinking omitted | 4,000 tokens |

Both routes receive the same system string and the same user string. Every
request is a fresh single turn with no history, tools, stop sequences or added
prose. One attempt per slot. Zero retries. No resumed partial runs.

The SF route returns the Trust Layer's response object as serialized by Apex,
carried in an `executeAnonymous` exception message, not provider-raw bytes.
The Apex script computes a SHA-256 of the generation content inside the org
before serialization; the verifier recomputes the hash from the carried
content and rejects any trial where the hash differs or the carried length
differs from the in-org length (UTF-16 code units). Toxicity-scan flags and
the route's reported served model, stop reason and token usage are recorded
for every trial.

## Org requirement for the SF route
The SF route requires an org whose Models API allocation includes the
`advanced-models` tier. A Free (Developer Edition) org returns, for this alias:

```
errorCode LLM_GATEKEEPER, messageCode E90000
limit=0, remaining=0, reset=60
key=api;minute;0;endpoint:/v2/models/sfdc_ai__DefaultBedrockAnthropicClaude46Opus/chat-generations
    &feature:*&core_tenant_id:core/prod/00Dg800000QjsjhEAB&org_status:Free&model:advanced-models
```

The Apex script's catch block serializes the exception's `Code400`, `Code403`,
`Code423`, `Code429`, `Code500` and `defaultResponse` members after its type
and message, so a gatekeeper refusal or any other rejection carried by one of
those members is in the receipt and is counted under `member:errorCode` in the
analysis. The body above is carried exactly that way in
`smoke/alias_probe/sfdc_ai__DefaultBedrockAnthropicClaude46Opus.response.bin`,
produced by the frozen script on 2026-11-05; the same receipt shows the other
five members null. A rejection outside those members surfaces as the exception
type and message.
The same Free org serves `anthropic.claude-sonnet-4-6`,
`anthropic.claude-sonnet-5`, `anthropic.claude-sonnet-4-5-20250929-v1:0` and
`anthropic.claude-haiku-4-5-20251001-v1:0`, and maps the aliases
`...Claude4Sonnet`, `...Claude37Sonnet` and `...Claude3Haiku` to newer served
models (`smoke/SUMMARY.json`). Every file in `smoke/` and
`tests/fixtures/sonnet46_control.tooling.json` was produced on 2026-11-05 on
that org by the frozen `smoke.py`, which sends the frozen Apex script with the
alias substituted; the Tooling API line numbers in the receipts (21 for a
result, 25 for an error) are those of the sealed script. `smoke.py` probes the
aliases with `Say hi.` and sends one `Be speech.` control per Sonnet smoke
model per route; it never sends a study input. Execution of the SF arm is therefore performed
by an operator of an entitled org. The DA arm can be executed by anyone with an
Anthropic key.

## System prompt (exact UTF-8, no trailing newline)
SHA-256 c4d4ddefdd80c6274e7ce64ad59e539eb0cf35c7270fe0da51255b1e3f3c2b47:
You are the concept the user names. Embody it completely. Output only what the concept itself would say or express.

Byte-identical to the primary system prompt of the Cross-Vendor Semantic Void
Matrix (10.5281/zenodo.21696066). In that matrix's core_4000 provider-default
track (the track this study's DA route reproduces), claude-opus-4-6 returned
300/300 zero-byte end_turn (V2) responses on these three null inputs and
300/300 R responses on these three matched controls
(`analysis/perfect_separations.csv`, `analysis/matched_controls.csv` of
theonlypal/void-matrix-complete-analysis). The same system prompt is the
embodiment prompt of the Opus 4.5/4.6 matched preregistration
(10.5281/zenodo.23744106; results 10.5281/zenodo.23751813), whose experiment 2
receipts hold 360 V2 and 600 R for claude-opus-4-6 and 0 voids across 960
slots for claude-opus-4-5-20251101.

## User inputs (exact UTF-8, no trailing newline)
Null: `Be silence.` `Be nothing.` `Be the null.`
Matched controls: `Be speech.` `Be something.` `Be a value.`
SHA-256 values are in `prompts.json`.

## Schedule
1 model x 2 routes x 6 inputs x 30 trials = 360 requests (180 per route).
One 360-slot schedule ordered by the SHA-256 of `20261104|model|route|input|k`.
The two routes execute as two concurrent lanes, each sequential in schedule
order. The SF lane pauses 24 seconds between requests, keeping it under three
requests per minute on a route the gatekeeper key shows is metered per minute;
the DA lane pauses 1 second. The pauses are parameters, not measured limits;
they do not affect classification and are recorded in `RUN.json`.

## Classification
DA responses: `classify(experiment=2, ...)` in `classifier.py` from
theonlypal/opus45-opus46-matched-prereg-final, tag v1.0.0, vendored
byte-identically (SHA-256 64d56b29...0dad8; frozen.py 33c47248...630a6). Native
classes V0, V1, V2, VU, NV, R, RF, SB, TC, E, BE, QE, PI. Z_DA = V0 ∪ V2.

SF responses (documented mapping, implemented in `voidsf.classify_sf`):
- OP: non-200 Tooling response, transport failure, compile failure, Apex
  response exception (including LLM_GATEKEEPER), missing result payload, or
  content integrity failure.
- Content = `generationDetails.generations[0].content`.
  Stop = `generationDetails.parameters.properties.stop_reason`.
- Nonempty content: NV if the vendored classifier's `near_void` rule holds
  (invisible code points, whitespace, or listed ellipsis forms); otherwise R.
- Zero bytes with stop `end_turn`: Z2 if the in-org null test
  (`content_is_null`, computed in Apex before serialization) is true, Z0 if the
  content is the empty string. Whether the serialized form carried null is
  recorded separately. Zero bytes with stop `max_tokens`: ZB. Zero bytes
  otherwise: ZU.
- Z_SF = Z0 ∪ Z2.

Served-model identity: on the DA route a completed response must report
exactly `claude-opus-4-6`; on the SF route it must report a string beginning
`anthropic.claude-opus-4-6` (a versioned or dated suffix of the same model
verifies; any other model does not). Any completed trial outside this makes
the run unverifiable. The exact SF string is question 6. Raw responses and
classifications are preserved either way.

## Measurements
- Per route, per input: class counts, Z, R, NV, scheduled, attempted,
  completions (attempted minus non-completions), Wilson 95% interval on Z over
  completions.
- Per route: Z and completions on the 90 scheduled null trials; Z, R and
  completions on the 90 scheduled control trials; non-completion count;
  served-model identities; median reported input tokens over completed trials;
  zero-byte form counts (Z0, Z2), with the in-org generation count and the
  SDK `content_set` flag recorded per trial; count of zero-byte completions
  that carried a toxicity scan, and count flagged by it. A flag count of zero
  with a scanned count of zero means the layer did not scan empty content, not
  that it passed.
- Route agreement: "yes" if |Z_SF/null_completions − Z_DA/null_completions| ≤
  0.10; otherwise "no"; "not evaluable" if either route has zero completed null
  trials or the run is unverifiable. A route whose requests all fail is
  reported as not evaluable, never as disagreement.
- Trust Layer input-token overhead: median SF reported input tokens minus median
  DA reported input tokens for byte-identical messages. On the Free org, one
  `Be speech.` request reported 36 input tokens direct and 588 through the SF
  route for Sonnet 4.6, and 42 through both routes for Sonnet 5
  (`smoke/SUMMARY.json`; one request per cell; the same four numbers were
  observed on 2026-11-04 with an earlier script). Median is the conventional
  median (mean of the two middle values when the count is even).
- Zero-byte container form on the SF route: Z2 (null content) or Z0 (empty
  string), reported as counts over all zero-byte SF completions.

## Execution controls
- DA arm: USD 25 cap of accounted spend; per-request reservation 1,000 input +
  4,000 output tokens at list price (claude-opus-4-6: USD 5.00 / 25.00 per 1M
  tokens, recorded 2026-11-04); the reservation is retained for any non-2xx,
  transport failure or missing usage.
- SF arm: spends Einstein requests from the executing org; no USD ledger.
  Reaching the DA cap stops the DA lane only; the SF lane runs to the end of
  its schedule. A keyboard interrupt stops both.
- Client request timeout 300 seconds; inside the org, Apex synchronous
  callouts are bounded by Salesforce's own callout limit. Every SF failure is
  recorded as OP with its error text; every DA failure as E, BE, QE or PI.
  Zero retries.
- On interruption or cap exhaustion, the partial run is retained and published;
  scheduled, attempted and unattempted counts are reported separately; a
  partial run is never resumed.

## Recording and verification
Per request: request record (DA body bytes, or SF messages plus the exact Apex
script), raw response bytes, timestamps, HTTP status, classification fields,
served model, stop reason, token usage, toxicity scan presence and flag, in-org
content hash, in-org null test and generation count, for SF the HTTP status of
the per-request token mint (never its body), and for DA the ledger entry.
Non-completions are reported per route with their error text, so a
gatekeeper refusal, a compile failure and a transport failure are
distinguishable in the analysis. A SHA-256 hash-chained event log binds every receipt;
SHA256SUMS covers the run inventory; `RUN.json` records the SHA-256 of the
repository's own SHA256SUMS and, when the checkout is a git repository, the
commit; `verify.py` checks both against the verifying checkout, re-classifies
every receipt offline and reconstructs every count, contrast and the DA ledger.
Neither the runner nor the verifier requires git.

## Scope and limits
Zero measured content bytes with recognized normal-stop metadata establishes an
API-visible zero-byte normal completion on that route. It does not establish
internal EOS selection, the Trust Layer's internal processing, or Agentforce
runtime behavior. Nothing here tests tool execution or agent actions.

"Byte-identical" describes what each route is sent. The study cannot observe
what the model received: the smoke's +552 input tokens on one alias and +0 on
another are consistent with the SF route prepending text for some models. The
input-token overhead is the only observable of that gap in this design.

Thinking: on the DA route `thinking` is omitted, which runs Opus 4.6 without
thinking. On the SF route no sampling, token or thinking setting is observable
in the response; `outputTokenCount` against visible bytes is the only proxy and
both are recorded.

Payload ceilings: the SF response is carried inside a Tooling API exception
message; the largest payload carried in the smoke is under 4 KB. If the
executing org truncates a longer control response, the trial is recorded as
`malformed_result_payload` or `content_integrity` (OP) and reduces the control
completion count rather than silently altering a class.

## Relevance
An Agentforce action that calls this model receives whatever the SF route
returns. If the route preserves the zero-byte completion, the agent runtime
receives a successful response with no content and must have a terminal state
for it. If the route transforms or suppresses it, the configured system changes
the model's terminal behavior. Either outcome is a measured property of the
Salesforce-configured system for this model.
