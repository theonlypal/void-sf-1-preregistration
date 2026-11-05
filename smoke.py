"""VOID-SF-1 smoke on a Free org: the alias-serving probe (input "Say hi.") and one "Be speech." control per smoke model per route. Never a study trial."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import voidsf as v

PROBE_ALIASES = ["sfdc_ai__DefaultBedrockAnthropicClaude46Opus", "sfdc_ai__DefaultBedrockAnthropicClaude45Opus",
                 "sfdc_ai__DefaultBedrockAnthropicClaude47Opus", "sfdc_ai__DefaultBedrockAnthropicClaude48Opus",
                 "sfdc_ai__DefaultBedrockAnthropicClaude5Opus", "sfdc_ai__DefaultBedrockAnthropicClaude46Sonnet",
                 "sfdc_ai__DefaultBedrockAnthropicClaude5Sonnet", "sfdc_ai__DefaultBedrockAnthropicClaude45Sonnet",
                 "sfdc_ai__DefaultBedrockAnthropicClaude4Sonnet", "sfdc_ai__DefaultBedrockAnthropicClaude37Sonnet",
                 "sfdc_ai__DefaultBedrockAnthropicClaude45Haiku", "sfdc_ai__DefaultBedrockAnthropicClaude3Haiku"]


SMOKE_MODELS = {
    "sonnet-4-6": {"sf_alias": "sfdc_ai__DefaultBedrockAnthropicClaude46Sonnet", "anthropic": "claude-sonnet-4-6"},
    "sonnet-5": {"sf_alias": "sfdc_ai__DefaultBedrockAnthropicClaude5Sonnet", "anthropic": "claude-sonnet-5"},
}


def smoke_apex(model: str, text: str) -> str:
    return v.apex_script("opus-4-6", text).replace(v.apex_literal(v.MODELS["opus-4-6"]["sf_alias"]), v.apex_literal(SMOKE_MODELS[model]["sf_alias"]))


def smoke_da_body(model: str, text: str) -> bytes:
    return v.da_body("opus-4-6", text).replace(v.MODELS["opus-4-6"]["anthropic"].encode(), SMOKE_MODELS[model]["anthropic"].encode(), 1)


def probe_script(alias: str) -> str:
    return v.apex_script("opus-4-6", "Say hi.").replace(v.apex_literal(v.MODELS["opus-4-6"]["sf_alias"]), v.apex_literal(alias))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=v.ROOT / "smoke")
    parser.add_argument("--sf-credentials", required=True)
    parser.add_argument("--anthropic-key-file", required=True)
    args = parser.parse_args()
    out = args.output
    (out / "alias_probe").mkdir(parents=True, exist_ok=True)
    (out / "controls").mkdir(parents=True, exist_ok=True)
    env = v.read_env_file(args.sf_credentials)
    key = open(os.path.expanduser(args.anthropic_key_file)).read().strip()
    summary = {"alias_probe": {}, "controls": {}}
    for alias in PROBE_ALIASES:
        r = v.sf_transport(env, probe_script(alias))
        (out / "alias_probe" / (alias + ".response.bin")).write_bytes(r["raw"])
        c = v.classify_sf(r["http_status"], r["raw"], r["transport_error"])
        summary["alias_probe"][alias] = {"served_model": c["returned_model"], "native": c["native"], "error": c["error"]}
        print(f"probe {alias:48s} served={c['returned_model']} class={c['native']} err={c['error']}", flush=True)
    for model in SMOKE_MODELS:
        for route in v.ROUTES:
            text = "Be speech."
            if route == "SF":
                r = v.sf_transport(env, smoke_apex(model, text))
            else:
                r = v.da_transport(key, smoke_da_body(model, text))
            name = f"{model}.{route}"
            (out / "controls" / (name + ".response.bin")).write_bytes(r["raw"])
            c = v.classify(route, r["http_status"], r["raw"], r["transport_error"])
            summary["controls"][name] = {k: c.get(k) for k in ("native", "returned_model", "answer_bytes", "termination", "input_tokens", "output_tokens", "error")}
            print(f"control {name:16s} class={c['native']} served={c['returned_model']} bytes={c['answer_bytes']} stop={c['termination']} in_tok={c['input_tokens']}", flush=True)
    (out / "SUMMARY.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False) + "\n")
    v.write_manifest(out)
    print("smoke written to", out)


if __name__ == "__main__":
    main()
