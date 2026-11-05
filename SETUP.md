# Setup

## Salesforce org
1. A Salesforce org whose Models API allocation includes the `advanced-models`
   tier. A Free Developer Edition org (https://developer.salesforce.com/signup)
   returns LLM_GATEKEEPER limit=0 for the Opus 4.6 alias (see `PROTOCOL.md`);
   it serves the Sonnet and Haiku aliases, which is what `smoke.py` exercises.
2. Setup -> External Client App Manager -> New External Client App.
   Enable OAuth. Callback URL `https://localhost`. Scopes: `sfap_api` and
   `api`. Enable Client Credentials Flow. After creation: Policies -> Client
   Credentials Flow -> Run As: an administrator user.
3. Settings -> OAuth Settings -> Consumer Key and Secret.
4. Write a private file (never committed), three lines:
   ```
   SF_INSTANCE_URL=https://<my-domain>.my.salesforce.com
   SF_CLIENT_ID=<consumer key>
   SF_CLIENT_SECRET=<consumer secret>
   ```
   The runner mints a client-credentials token per request and calls the
   Tooling API `executeAnonymous` endpoint, which runs the Apex in
   `voidsf.apex_script` inside the org.

## Anthropic
A private file containing only the API key.

## Offline checks
```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B -m unittest discover -s tests -v
shasum -a 256 -c SHA256SUMS
```

## Smoke (not a study trial)
```sh
.venv/bin/python -B smoke.py --sf-credentials <file> --anthropic-key-file <file>
```

## Run
Run from a clone whose `SHA256SUMS` verifies; git is not required. Add nothing
to the folder except `.venv`; macOS `._*` sidecar files are ignored. The output
directory must be outside the folder and must not exist.
```sh
.venv/bin/python -B runner.py --authorize --output ../void-sf-1-results \
  --sf-credentials <file> --anthropic-key-file <file>
.venv/bin/python -B verify.py ../void-sf-1-results
```
