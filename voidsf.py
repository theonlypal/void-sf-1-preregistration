"""VOID-SF-1 definitions: prompts, schedule, request builders, transports, classification, ledger, chain, analysis."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import statistics
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / "vendor" / "opus45-opus46-matched-prereg-final"
VENDOR_SHA256 = {
    "vendor/opus45-opus46-matched-prereg-final/classifier.py": "64d56b291bcdcd8ec4376d91933b1dd25299c62f335a406d9a989b687510dad8",
    "vendor/opus45-opus46-matched-prereg-final/frozen.py": "33c47248e123a2b2bf59f96bb858dc0874d65d2aba1f75aaa836a41e097630a6",
}

SYSTEM = "You are the concept the user names. Embody it completely. Output only what the concept itself would say or express."
SYSTEM_SHA256 = "c4d4ddefdd80c6274e7ce64ad59e539eb0cf35c7270fe0da51255b1e3f3c2b47"
NULLS = ("Be silence.", "Be nothing.", "Be the null.")
CONTROLS = ("Be speech.", "Be something.", "Be a value.")
INPUTS = NULLS + CONTROLS
INPUT_SHA256 = {
    "Be silence.": "cdc0262242c79b0fef9aca41862e543632586e0221fc368bf46a72965282dc57",
    "Be nothing.": "58daa738843bc8f34ed6b1d1eef6647a09a54006d73fbd1d786d8b8a663e4485",
    "Be the null.": "f31e587e56ee77a23171e438da1faed0e0f122133558bf11fc654f18366d2bdb",
    "Be speech.": "42444be4c85b8b88bc70b3318f5514294613661674eddb76a7de34fe86a2956a",
    "Be something.": "9f867ebe544cbb3ba7514c9558136823188e1d3af7b3aedd1c312dd3584268fc",
    "Be a value.": "a0070648c905b7636ef2cb90f0cd7545fd9d1e062bfebc4af183c9be2b76ecda",
}
MODELS = {
    "opus-4-6": {"sf_alias": "sfdc_ai__DefaultBedrockAnthropicClaude46Opus", "sf_served": "anthropic.claude-opus-4-6",
                 "anthropic": "claude-opus-4-6"},
}
ROUTES = ("SF", "DA")
TRIALS = 30
SEED = 20261104
DA_MAX_TOKENS = 4000
ANTHROPIC_VERSION = "2023-06-01"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
TOOLING_PATH = "/services/data/v62.0/tooling/executeAnonymous/"
TIMEOUT_SECONDS = 300
SF_PAUSE_SECONDS = 24.0
DA_PAUSE_SECONDS = 1.0
PRICE_PER_MILLION = {"opus-4-6": (Decimal("5.00"), Decimal("25.00"))}
RESERVE_INPUT_TOKENS = 1000
RESERVE_OUTPUT_TOKENS = 4000
DA_SPEND_CAP = Decimal("25")

Z_DA = frozenset({"V0", "V2"})
Z_SF = frozenset({"Z0", "Z2"})
EMITTED = frozenset({"NV", "R"})
NON_COMPLETION_DA = frozenset({"E", "BE", "QE", "PI"})
NON_COMPLETION_SF = frozenset({"OP"})


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def schedule():
    keyed = []
    for model in MODELS:
        for route in ROUTES:
            for text in INPUTS:
                for k in range(1, TRIALS + 1):
                    keyed.append((sha256(f"{SEED}|{model}|{route}|{text}|{k}".encode()), model, route, text, k))
    keyed.sort()
    return [{"slot": f"{i:04d}", "model": m, "route": r, "input": t, "k": k}
            for i, (_, m, r, t, k) in enumerate(keyed, 1)]


def schedule_bytes() -> bytes:
    return (json.dumps(schedule(), ensure_ascii=False, indent=1) + "\n").encode("utf-8")


def check_frozen_sources(root: Path = ROOT):
    if sha256(SYSTEM.encode()) != SYSTEM_SHA256:
        raise ValueError("System prompt differs")
    for text, digest in INPUT_SHA256.items():
        if sha256(text.encode()) != digest:
            raise ValueError("User input differs: " + text)
    for rel, digest in VENDOR_SHA256.items():
        if sha256((root / rel).read_bytes()) != digest:
            raise ValueError("Vendored classifier differs: " + rel)
    data = schedule_bytes()
    if (root / "SCHEDULE.json").read_bytes() != data:
        raise ValueError("SCHEDULE.json differs from the seeded schedule")
    if (root / "SCHEDULE.sha256").read_text() != f"{sha256(data)}  SCHEDULE.json\n":
        raise ValueError("SCHEDULE.sha256 differs")


# ---------------------------------------------------------------- requests

def da_body(model: str, text: str) -> bytes:
    body = {"model": MODELS[model]["anthropic"], "max_tokens": DA_MAX_TOKENS, "system": SYSTEM,
            "messages": [{"role": "user", "content": text}]}
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def apex_literal(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def sf_messages(text: str):
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]


def apex_script(model: str, text: str) -> str:
    alias = MODELS[model]["sf_alias"]
    return (
        "aiplatform.ModelsAPI.createChatGenerations_Request req = new aiplatform.ModelsAPI.createChatGenerations_Request();\n"
        f"req.modelName = {apex_literal(alias)};\n"
        "aiplatform.ModelsAPI_ChatGenerationsRequest body = new aiplatform.ModelsAPI_ChatGenerationsRequest();\n"
        "List<aiplatform.ModelsAPI_ChatMessageRequest> msgs = new List<aiplatform.ModelsAPI_ChatMessageRequest>();\n"
        "aiplatform.ModelsAPI_ChatMessageRequest s = new aiplatform.ModelsAPI_ChatMessageRequest();\n"
        f"s.role = 'system'; s.content = {apex_literal(SYSTEM)}; msgs.add(s);\n"
        "aiplatform.ModelsAPI_ChatMessageRequest u = new aiplatform.ModelsAPI_ChatMessageRequest();\n"
        f"u.role = 'user'; u.content = {apex_literal(text)}; msgs.add(u);\n"
        "body.messages = msgs; req.body = body;\n"
        "try {\n"
        "  aiplatform.ModelsAPI.createChatGenerations_Response resp = new aiplatform.ModelsAPI().createChatGenerations(req);\n"
        "  String c = null;\n"
        "  if (resp.Code200 != null && resp.Code200.generationDetails != null && resp.Code200.generationDetails.generations != null\n"
        "      && !resp.Code200.generationDetails.generations.isEmpty()) { c = resp.Code200.generationDetails.generations[0].content; }\n"
        "  Map<String,Object> o = new Map<String,Object>();\n"
        "  o.put('content_is_null', c == null);\n"
        "  o.put('generations_count', (resp.Code200 != null && resp.Code200.generationDetails != null && resp.Code200.generationDetails.generations != null) ? resp.Code200.generationDetails.generations.size() : null);\n"
        "  o.put('content_len_chars', c == null ? null : c.length());\n"
        "  o.put('content_sha256', EncodingUtil.convertToHex(Crypto.generateDigest('SHA-256', Blob.valueOf(c == null ? '' : c))));\n"
        "  o.put('full', resp.Code200);\n"
        "  throw new StringException('RESULT:' + JSON.serialize(o));\n"
        "} catch (aiplatform.ModelsAPI.createChatGenerations_ResponseException e) {\n"
        "  Map<String,Object> err = new Map<String,Object>();\n"
        "  err.put('Code400', e.Code400); err.put('Code403', e.Code403); err.put('Code423', e.Code423); err.put('Code429', e.Code429); err.put('Code500', e.Code500); err.put('defaultResponse', e.defaultResponse);\n"
        "  throw new StringException('ERROR:' + e.getTypeName() + '|' + e.getMessage() + '|' + JSON.serialize(err));\n"
        "}\n"
    )


def sf_request_record(model: str, text: str) -> bytes:
    return json.dumps({"route": "SF", "mechanism": "tooling_execute_anonymous", "alias": MODELS[model]["sf_alias"],
                       "messages": sf_messages(text), "apex": apex_script(model, text)},
                      ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ---------------------------------------------------------------- transports

def read_env_file(path: str) -> dict:
    env = {}
    for line in open(os.path.expanduser(path)):
        if "=" in line:
            key, value = line.strip().split("=", 1)
            env[key] = value.strip().strip('"')
    return env


def _http(method, url, headers, body, timeout):
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    dispatch = utc()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"http_status": response.status, "raw": response.read(), "transport_error": None,
                    "dispatch_utc": dispatch, "receipt_utc": utc()}
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        except Exception as inner:
            return {"http_status": error.code, "raw": b"", "transport_error": type(inner).__name__,
                    "dispatch_utc": dispatch, "receipt_utc": utc()}
        return {"http_status": error.code, "raw": raw, "transport_error": None, "dispatch_utc": dispatch, "receipt_utc": utc()}
    except Exception as error:
        return {"http_status": None, "raw": b"", "transport_error": type(error).__name__, "dispatch_utc": dispatch, "receipt_utc": utc()}


def sf_token(env: dict, timeout=TIMEOUT_SECONDS):
    data = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": env["SF_CLIENT_ID"],
                                   "client_secret": env["SF_CLIENT_SECRET"]}).encode()
    r = _http("POST", env["SF_INSTANCE_URL"].rstrip("/") + "/services/oauth2/token",
              {"Content-Type": "application/x-www-form-urlencoded"}, data, timeout)
    status = r["transport_error"] or r["http_status"]
    if r["http_status"] != 200:
        return None, status
    try:
        return json.loads(r["raw"]).get("access_token"), status
    except Exception:
        return None, status


def sf_transport(env: dict, apex: str, timeout=TIMEOUT_SECONDS) -> dict:
    token, token_status = sf_token(env, timeout)
    if not token:
        return {"http_status": None, "raw": b"", "transport_error": "TokenError", "dispatch_utc": utc(), "receipt_utc": utc(),
                "token_status": token_status}
    url = env["SF_INSTANCE_URL"].rstrip("/") + TOOLING_PATH + "?anonymousBody=" + urllib.parse.quote(apex)
    return {**_http("GET", url, {"Authorization": "Bearer " + token}, None, timeout), "token_status": token_status}


def da_transport(key: str, body: bytes, timeout=TIMEOUT_SECONDS) -> dict:
    return _http("POST", ANTHROPIC_URL, {"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION,
                                         "content-type": "application/json"}, body, timeout)


# ---------------------------------------------------------------- classification

_vendor = {}


def vendored():
    if "cls" not in _vendor:
        path = str(VENDOR)
        if path not in sys.path:
            sys.path.insert(0, path)
        spec = importlib.util.spec_from_file_location("void_sf_vendor_opus_classifier", VENDOR / "classifier.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _vendor["cls"] = module
    return _vendor["cls"]


def classify_da(http_status, raw: bytes, transport_error) -> dict:
    r = vendored().classify(2, http_status if transport_error is None else None, raw)
    return {"native": r["class"], "returned_model": r["returned_model"], "answer_bytes": r["visible_bytes"],
            "termination": r["stop_reason"], "response_id": r["response_id"], "usage": r["usage"],
            "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]}


def classify_sf(http_status, raw: bytes, transport_error) -> dict:
    out = {"native": "OP", "returned_model": None, "answer_bytes": None, "termination": None, "response_id": None,
           "usage": None, "input_tokens": None, "output_tokens": None, "content_is_null": None, "apex_sha256": None,
           "recomputed_sha256": None, "hash_match": None, "truncated": None, "toxicity_detected": None,
           "compiled": None, "success": None, "error": None, "serialized_content_null": None,
           "generations_count": None, "content_set": None, "toxicity_scan_present": None, "sf_error_code": None}
    if transport_error is not None or http_status != 200:
        out["error"] = transport_error or f"http_{http_status}"
        return out
    try:
        j = json.loads(raw)
    except Exception:
        out["error"] = "malformed_tooling_body"
        return out
    out["compiled"], out["success"] = j.get("compiled"), j.get("success")
    message = j.get("exceptionMessage") or ""
    if not j.get("compiled"):
        out["error"] = "compile:" + str(j.get("compileProblem"))[:200]
        return out
    if "RESULT:" not in message:
        out["error"] = ("apex:" + message[:300]) if message else "no_result"
        body = message[message.index("ERROR:") + 6:].split("|", 2) if "ERROR:" in message else []
        if len(body) == 3:
            try:
                err = json.loads(body[2])
                codes = [(k, x) for k, x in sorted(err.items()) if isinstance(x, dict)] if isinstance(err, dict) else []
                out["sf_error_code"] = (codes[0][0] + ":" + str(codes[0][1].get("errorCode"))) if codes else None
            except Exception:
                out["sf_error_code"] = None
        return out
    try:
        payload = json.loads(message[message.index("RESULT:") + 7:])
    except Exception:
        out["error"] = "malformed_result_payload"
        return out
    full = payload.get("full") or {}
    details = full.get("generationDetails") or {}
    gens = details.get("generations") or []
    props = ((details.get("parameters") or {}).get("properties")) or {}
    content = gens[0].get("content") if gens and isinstance(gens[0], dict) else None
    out["content_is_null"] = payload.get("content_is_null")
    out["serialized_content_null"] = content is None
    out["apex_sha256"] = payload.get("content_sha256")
    out["generations_count"] = payload.get("generations_count")
    out["content_set"] = gens[0].get("content_set") if gens and isinstance(gens[0], dict) else None
    text = content if isinstance(content, str) else ""
    try:
        encoded = text.encode("utf-8")
    except UnicodeError:
        out["error"] = "unencodable_content"
        return out
    out["recomputed_sha256"] = sha256(encoded)
    out["hash_match"] = out["recomputed_sha256"] == out["apex_sha256"]
    expected_len = payload.get("content_len_chars")
    utf16_units = len(text.encode("utf-16-le")) // 2  # Apex String.length() counts UTF-16 code units
    out["truncated"] = (expected_len is not None and expected_len != utf16_units)
    out["answer_bytes"] = len(encoded)
    out["returned_model"] = props.get("model")
    out["termination"] = props.get("stop_reason")
    out["response_id"] = full.get("id")
    usage = props.get("usage") or {}
    out["usage"] = usage
    out["input_tokens"] = usage.get("inputTokenCount")
    out["output_tokens"] = usage.get("outputTokenCount")
    quality = (gens[0].get("contentQuality") or {}) if gens else {}
    scan = quality.get("scanToxicity")
    out["toxicity_scan_present"] = isinstance(scan, dict) and "isDetected" in scan
    out["toxicity_detected"] = scan.get("isDetected") if isinstance(scan, dict) else None
    cls = vendored()
    stop = out["termination"]
    if out["truncated"] or not out["hash_match"]:
        out["native"] = "OP"
        out["error"] = "content_integrity"
    elif encoded:
        out["native"] = "NV" if cls.near_void(text) else "R"
    elif stop in cls.BUDGET_STOPS:
        out["native"] = "ZB"
    elif stop in cls.NORMAL_STOPS:
        out["native"] = "Z2" if out["content_is_null"] is True else "Z0"
    else:
        out["native"] = "ZU"
    return out


def classify(route: str, http_status, raw: bytes, transport_error) -> dict:
    return classify_sf(http_status, raw, transport_error) if route == "SF" else classify_da(http_status, raw, transport_error)


def model_mismatch(route: str, model: str, result: dict) -> bool:
    if result["native"] in (NON_COMPLETION_SF | NON_COMPLETION_DA):
        return False
    returned = result["returned_model"]
    if route == "SF":
        return not (isinstance(returned, str) and returned.startswith(MODELS[model]["sf_served"]))
    return returned != MODELS[model]["anthropic"]


# ---------------------------------------------------------------- ledger (DA only)

def reservation(model: str) -> Decimal:
    inp, out = PRICE_PER_MILLION[model]
    return (RESERVE_INPUT_TOKENS * inp + RESERVE_OUTPUT_TOKENS * out) / Decimal(1_000_000)


def da_charge(model: str, http_status, usage, transport_error):
    if transport_error is None and isinstance(http_status, int) and 200 <= http_status < 300 and isinstance(usage, dict):
        a, b = usage.get("input_tokens"), usage.get("output_tokens")
        c = usage.get("cache_creation_input_tokens") or 0
        d = usage.get("cache_read_input_tokens") or 0
        if all(type(x) is int and x >= 0 for x in (a, b, c, d)):
            inp, out = PRICE_PER_MILLION[model]
            return ((a + c + d) * inp + b * out) / Decimal(1_000_000), "usage"
    return reservation(model), "reservation"


# ---------------------------------------------------------------- chain / manifest

class Chain:
    def __init__(self, path: Path):
        self.prev, self.seq = "0" * 64, 0
        self.handle = open(path, "xb")

    def add(self, kind: str, **fields):
        event = {"seq": self.seq, "kind": kind, "prev": self.prev, "utc": utc(), **fields}
        line = canonical(event) + b"\n"
        self.handle.write(line)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.prev = sha256(line)
        self.seq += 1
        return event

    def close(self):
        self.handle.close()


def verify_chain(path: Path):
    events, prev = [], "0" * 64
    for seq, line in enumerate(path.read_bytes().splitlines(keepends=True)):
        event = json.loads(line)
        if line != canonical(event) + b"\n" or event.get("seq") != seq or event.get("prev") != prev:
            raise ValueError("Event chain broken at line " + str(seq))
        prev = sha256(line)
        events.append(event)
    return events


def _tree(root: Path):
    skip = {".git", ".venv", "__pycache__"}
    return sorted(p for p in root.rglob("*") if p.is_file() and p.name not in ("SHA256SUMS", ".DS_Store")
                  and not p.name.startswith("._") and not any(part in skip for part in p.relative_to(root).parts))


def write_manifest(root: Path):
    lines = [f"{sha256(p.read_bytes())}  {p.relative_to(root).as_posix()}\n" for p in _tree(root)]
    (root / "SHA256SUMS").write_text("".join(lines))
    return len(lines)


def verify_manifest(root: Path) -> int:
    listed = {}
    for line in (root / "SHA256SUMS").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        listed[rel] = digest
    actual = {p.relative_to(root).as_posix(): p for p in _tree(root)}
    if set(listed) != set(actual):
        raise ValueError("Manifest inventory differs")
    for rel, path in actual.items():
        if sha256(path.read_bytes()) != listed[rel]:
            raise ValueError("Manifest hash differs: " + rel)
    return len(listed)


# ---------------------------------------------------------------- analysis

def _num(x):
    return int(x) if float(x).is_integer() else float(x)


def wilson(x: int, n: int, z: float = 1.959963984540054):
    if n == 0:
        return None
    p = x / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 6), round(centre + half, 6)]


def analyze(records, unverifiable: bool = False) -> dict:
    out = {}
    for model in MODELS:
        per_route = {}
        for route in ROUTES:
            zset = Z_SF if route == "SF" else Z_DA
            noncomp = NON_COMPLETION_SF if route == "SF" else NON_COMPLETION_DA
            cells = {}
            for text in INPUTS:
                rows = [r for r in records if (r["model"], r["route"], r["input"]) == (model, route, text)]
                classes = Counter(r["native"] for r in rows)
                z = sum(classes[c] for c in zset)
                completions = sum(v for c, v in classes.items() if c not in noncomp)
                cells[text] = {"scheduled": TRIALS, "attempted": len(rows), "completions": completions,
                               "classes": dict(sorted(classes.items())), "Z": z, "R": classes["R"], "NV": classes["NV"],
                               "Z_wilson95": wilson(z, completions)}
            nulls = [cells[t] for t in NULLS]
            ctrls = [cells[t] for t in CONTROLS]
            rows_route = [r for r in records if (r["model"], r["route"]) == (model, route)]
            served = Counter(r.get("returned_model") for r in rows_route if r["native"] not in noncomp and r.get("returned_model"))
            in_tok = [r["input_tokens"] for r in rows_route if r["native"] not in noncomp and type(r.get("input_tokens")) is int]
            per_route[route] = {
                "cells": cells,
                "null_Z": sum(c["Z"] for c in nulls), "null_attempted": sum(c["attempted"] for c in nulls),
                "null_completions": sum(c["completions"] for c in nulls),
                "control_Z": sum(c["Z"] for c in ctrls), "control_attempted": sum(c["attempted"] for c in ctrls),
                "control_completions": sum(c["completions"] for c in ctrls),
                "control_R": sum(c["R"] for c in ctrls),
                "zero_byte_forms": {c: sum(1 for r in rows_route if r["native"] == c) for c in sorted(zset)},
                "non_completions": sum(1 for r in rows_route if r["native"] in noncomp),
                "non_completion_errors": dict(sorted(Counter((r.get("sf_error_code") or r.get("error") or r["native"]) for r in rows_route if r["native"] in noncomp).items())),
                "served_models": dict(served),
                "median_input_tokens": (_num(statistics.median(in_tok)) if in_tok else None),
                "zero_byte_toxicity_scanned": sum(1 for r in rows_route if r["native"] in zset and r.get("toxicity_scan_present")),
                "zero_byte_toxicity_flagged": sum(1 for r in rows_route if r["native"] in zset and r.get("toxicity_detected")),
            }
        sf, da = per_route["SF"], per_route["DA"]
        rate = lambda r: (r["null_Z"] / r["null_completions"]) if r["null_completions"] else None
        agreement = None
        if rate(sf) is not None and rate(da) is not None:
            agreement = "yes" if abs(rate(sf) - rate(da)) <= 0.10 else "no"
        overhead = None
        if sf["median_input_tokens"] is not None and da["median_input_tokens"] is not None:
            overhead = sf["median_input_tokens"] - da["median_input_tokens"]
        out[model] = {"routes": per_route, "route_agreement_within_10pp": "not evaluable" if unverifiable or agreement is None else agreement,
                      "trust_layer_input_token_overhead_median": overhead}
    return out
