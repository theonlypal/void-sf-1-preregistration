"""Offline VOID-SF-1 checks. No network access and no credentials."""
import hashlib
import json
import re
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import voidsf as v  # noqa: E402
import runner  # noqa: E402
import verify  # noqa: E402

ENV = {"SF_INSTANCE_URL": "https://example.my.salesforce.com", "SF_CLIENT_ID": "id", "SF_CLIENT_SECRET": "secret"}


def sf_payload(content, stop="end_turn", model="anthropic.claude-opus-4-6", in_tok=588, toxic=False, lie_len=None):
    text = content if isinstance(content, str) else ""
    payload = {"content_is_null": content is None,
               "content_len_chars": (len(content) if isinstance(content, str) else None) if lie_len is None else lie_len,
               "content_sha256": hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest(),
               "full": {"id": "resp-1", "generationDetails": {
                   "generations": [{"role": "assistant", "content": content,
                                    "contentQuality": {"scanToxicity": {"isDetected": toxic, "categories": []}}}],
                   "parameters": {"properties": {"type": "MESSAGE", "model": model, "stop_reason": stop,
                                                 "usage": {"inputTokenCount": in_tok, "outputTokenCount": 3}}}}}}
    return json.dumps({"compiled": True, "success": False, "line": 9, "column": 1,
                       "exceptionMessage": "System.StringException: RESULT:" + json.dumps(payload)}).encode()


def da_body(content_blocks, stop="end_turn", model="claude-opus-4-6", in_tok=36):
    return json.dumps({"id": "msg_1", "type": "message", "role": "assistant", "model": model, "content": content_blocks,
                       "stop_reason": stop, "stop_sequence": None,
                       "usage": {"input_tokens": in_tok, "output_tokens": 3}}).encode()


def fake_sf(scenario="void"):
    def send(env, apex, timeout=0):
        if scenario == "gatekeeper":
            raw = json.dumps({"compiled": True, "success": False, "line": 10, "column": 1,
                              "exceptionMessage": "System.StringException: ERROR:aiplatform.ModelsAPI.createChatGenerations_ResponseException|Script-thrown exception"}).encode()
            return {"http_status": 200, "raw": raw, "transport_error": None, "dispatch_utc": "2026-11-04T00:00:00Z", "receipt_utc": "2026-11-04T00:00:01Z"}
        alias = re.search(r"req\.modelName = '([^']+)'", apex).group(1)
        text = re.search(r"u\.content = '([^']+)'", apex).group(1)
        model = next(m for m in v.MODELS if v.MODELS[m]["sf_alias"] == alias)
        served = v.MODELS[model]["sf_served"] if scenario != "wrong_model" else "anthropic.claude-sonnet-4-6"
        if text in v.NULLS and scenario in ("void", "wrong_model"):
            raw = sf_payload(None, model=served)
        elif text in v.NULLS and scenario == "void_empty_string":
            raw = sf_payload("", model=served)
        else:
            raw = sf_payload("Speech is the sound of thought.", model=served)
        return {"http_status": 200, "raw": raw, "transport_error": None, "dispatch_utc": "2026-11-04T00:00:00Z", "receipt_utc": "2026-11-04T00:00:01Z"}
    return send


def fake_da(scenario="void", usage_tokens=None):
    def send(key, body, timeout=0):
        req = json.loads(body)
        text = req["messages"][0]["content"]
        model = req["model"]
        blocks = [] if (text in v.NULLS and scenario == "void") else [{"type": "text", "text": "Speech is the sound of thought."}]
        raw = da_body(blocks, model=model, in_tok=usage_tokens or 36)
        if usage_tokens:
            j = json.loads(raw); j["usage"]["output_tokens"] = usage_tokens; raw = json.dumps(j).encode()
        return {"http_status": 200, "raw": raw, "transport_error": None, "dispatch_utc": "2026-11-04T00:00:00Z", "receipt_utc": "2026-11-04T00:00:01Z"}
    return send


class Frozen(unittest.TestCase):
    def test_sources(self):
        v.check_frozen_sources()

    def test_prompt_hashes(self):
        self.assertEqual(hashlib.sha256(v.SYSTEM.encode()).hexdigest(), v.SYSTEM_SHA256)
        for t, d in v.INPUT_SHA256.items():
            self.assertEqual(hashlib.sha256(t.encode()).hexdigest(), d)
        prompts = json.loads((ROOT / "prompts.json").read_text())
        self.assertEqual(prompts["system"]["sha256"], v.SYSTEM_SHA256)
        for t in v.INPUTS:
            self.assertEqual(prompts["inputs"][t]["sha256"], v.INPUT_SHA256[t])

    def test_schedule(self):
        s = v.schedule()
        self.assertEqual(len(s), 360)
        for m in v.MODELS:
            for r in v.ROUTES:
                for t in v.INPUTS:
                    self.assertEqual(sorted(x["k"] for x in s if (x["model"], x["route"], x["input"]) == (m, r, t)), list(range(1, 31)))

    def test_apex_script_escaping_and_fields(self):
        script = v.apex_script("opus-4-6", "Be the null.")
        self.assertIn("req.modelName = 'sfdc_ai__DefaultBedrockAnthropicClaude46Opus';", script)
        self.assertIn("s.content = '" + v.SYSTEM + "'", script)
        self.assertIn("u.content = 'Be the null.'", script)
        self.assertEqual(v.apex_literal("it's \\ x"), "'it\\'s \\\\ x'")
        self.assertIn("Crypto.generateDigest('SHA-256'", script)
        self.assertIn("err.put('Code429', e.Code429)", script)
        self.assertNotIn("Code404", script)  # the Nov 4 probe: "Variable does not exist: Code404"
        self.assertIn("o.put('generations_count'", script)

    def test_da_body(self):
        body = json.loads(v.da_body("opus-4-6", "Be silence."))
        self.assertEqual(body, {"model": "claude-opus-4-6", "max_tokens": 4000, "system": v.SYSTEM,
                                "messages": [{"role": "user", "content": "Be silence."}]})


class Classification(unittest.TestCase):
    def test_sf_real_receipt(self):
        raw = (ROOT / "tests" / "fixtures" / "sonnet46_control.tooling.json").read_bytes()
        c = v.classify_sf(200, raw, None)
        self.assertEqual((c["native"], c["returned_model"], c["termination"], c["hash_match"], c["truncated"]),
                         ("R", "anthropic.claude-sonnet-4-6", "end_turn", True, False))
        self.assertEqual(c["input_tokens"], 588)

    def test_sf_zero_byte_cases(self):
        self.assertEqual(v.classify_sf(200, sf_payload(None), None)["native"], "Z2")
        self.assertEqual(v.classify_sf(200, sf_payload(""), None)["native"], "Z0")
        self.assertEqual(v.classify_sf(200, sf_payload("", stop="max_tokens"), None)["native"], "ZB")
        self.assertEqual(v.classify_sf(200, sf_payload("", stop="weird"), None)["native"], "ZU")
        self.assertEqual(v.classify_sf(200, sf_payload("..."), None)["native"], "NV")
        self.assertEqual(v.classify_sf(200, sf_payload("​"), None)["native"], "NV")
        self.assertEqual(v.classify_sf(200, sf_payload("LOCKED"), None)["native"], "R")
        emoji = "Hi! \U0001F44B"
        raw = sf_payload(emoji, lie_len=len(emoji.encode("utf-16-le")) // 2)  # Apex reports UTF-16 units
        self.assertEqual((v.classify_sf(200, raw, None)["native"], v.classify_sf(200, raw, None)["truncated"]), ("R", False))

    def test_sf_operational_and_integrity(self):
        self.assertEqual(v.classify_sf(401, b"", None)["native"], "OP")
        self.assertEqual(v.classify_sf(None, b"", "TimeoutError")["native"], "OP")
        self.assertEqual(v.classify_sf(200, b"not json", None)["error"], "malformed_tooling_body")
        err = json.dumps({"compiled": True, "success": False, "exceptionMessage": "System.StringException: ERROR:aiplatform.ModelsAPI.createChatGenerations_ResponseException|Script-thrown exception"}).encode()
        c = v.classify_sf(200, err, None)
        self.assertEqual((c["native"], c["sf_error_code"]), ("OP", None)); self.assertTrue(c["error"].startswith("apex:"))
        gate = json.dumps({"compiled": True, "success": False, "exceptionMessage": "System.StringException: ERROR:aiplatform.ModelsAPI.createChatGenerations_ResponseException|Script-thrown exception|"
                           + json.dumps({"Code400": None, "Code403": None, "Code423": None, "Code500": None, "defaultResponse": None,
                                         "Code429": {"errorCode": "LLM_GATEKEEPER", "messageCode": "E90000", "message": "You have exceeded your rate limit."}})}).encode()
        c = v.classify_sf(200, gate, None)
        self.assertEqual((c["native"], c["sf_error_code"]), ("OP", "Code429:LLM_GATEKEEPER"))
        comp = json.dumps({"compiled": False, "compileProblem": "Variable does not exist"}).encode()
        self.assertTrue(v.classify_sf(200, comp, None)["error"].startswith("compile:"))
        c = v.classify_sf(200, sf_payload("hello", lie_len=99), None)
        self.assertEqual((c["native"], c["error"], c["truncated"]), ("OP", "content_integrity", True))
        c = v.classify_sf(200, sf_payload("\ud800"), None)
        self.assertEqual((c["native"], c["error"]), ("OP", "unencodable_content"))

    def test_da_vendored(self):
        self.assertEqual(v.classify_da(200, da_body([]), None)["native"], "V2")
        self.assertEqual(v.classify_da(200, da_body([{"type": "text", "text": ""}]), None)["native"], "V0")
        self.assertEqual(v.classify_da(200, da_body([{"type": "text", "text": "hi"}]), None)["native"], "R")
        self.assertEqual(v.classify_da(429, b'{"type":"error","error":{"type":"rate_limit_error","message":"x"}}', None)["native"], "E")

    def test_model_mismatch(self):
        ok = v.classify_sf(200, sf_payload("x"), None)
        self.assertFalse(v.model_mismatch("SF", "opus-4-6", ok))
        bad = v.classify_sf(200, sf_payload("x", model="anthropic.claude-sonnet-4-6"), None)
        self.assertTrue(v.model_mismatch("SF", "opus-4-6", bad))
        dated = v.classify_sf(200, sf_payload("x", model="anthropic.claude-opus-4-6-v1:0"), None)
        self.assertFalse(v.model_mismatch("SF", "opus-4-6", dated))  # a versioned id of the same model verifies; Q6 records the exact string
        self.assertFalse(v.model_mismatch("SF", "opus-4-6", v.classify_sf(401, b"", None)))


class Ledger(unittest.TestCase):
    def test_charges(self):
        self.assertEqual(v.reservation("opus-4-6"), Decimal("0.105"))
        self.assertEqual(v.da_charge("opus-4-6", 200, {"input_tokens": 36, "output_tokens": 3}, None), (Decimal("0.000255"), "usage"))
        self.assertEqual(v.da_charge("opus-4-6", 200, None, None), (Decimal("0.105"), "reservation"))
        self.assertEqual(v.da_charge("opus-4-6", 200, {"input_tokens": 1, "output_tokens": 1}, "IncompleteRead"), (Decimal("0.105"), "reservation"))


class EndToEnd(unittest.TestCase):
    def run_once(self, sf="void", da="void", usage_tokens=None):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        out = Path(tmp.name) / "run"
        status = runner.execute(out, {"commit": "test-commit", "repo_manifest_sha256": "m"}, ENV, "key", sf_transport=fake_sf(sf), da_transport=fake_da(da, usage_tokens),
                                sleep=lambda s: None)
        return out, status

    def test_void_everywhere(self):
        out, status = self.run_once()
        self.assertEqual(status, "COMPLETE")
        r = verify.verify(out, expected_commit="test-commit", expected_manifest_sha256="m")
        self.assertFalse(r["unverifiable"])
        a = r["analysis"]["opus-4-6"]
        self.assertEqual((a["routes"]["SF"]["null_Z"], a["routes"]["DA"]["null_Z"], a["routes"]["SF"]["control_Z"]), (90, 90, 0))
        self.assertEqual(a["route_agreement_within_10pp"], "yes")
        self.assertEqual(a["trust_layer_input_token_overhead_median"], 552)
        self.assertEqual(a["routes"]["SF"]["served_models"], {"anthropic.claude-opus-4-6": 180})
        with self.assertRaises(ValueError):
            verify.verify(out, expected_commit="other")
        with self.assertRaises(ValueError):
            verify.verify(out, expected_manifest_sha256="other")
        run = json.loads((out / "RUN.json").read_bytes()); run["commit"] = None
        (out / "RUN.json").write_bytes(v.canonical(run))
        with self.assertRaises(ValueError):
            verify.verify(out)  # RUN.json is bound to the chain; rewriting it is detected


    def test_route_disagreement(self):
        out, _ = self.run_once(sf="speak", da="void")
        a = verify.verify(out)["analysis"]["opus-4-6"]
        self.assertEqual((a["routes"]["SF"]["null_Z"], a["routes"]["DA"]["null_Z"], a["route_agreement_within_10pp"]), (0, 90, "no"))

    def test_failed_sf_arm_is_not_evaluable(self):
        out, status = self.run_once(sf="gatekeeper")
        self.assertEqual(status, "COMPLETE")
        r = verify.verify(out); a = r["analysis"]["opus-4-6"]
        self.assertFalse(r["unverifiable"])
        self.assertEqual((a["routes"]["SF"]["non_completions"], a["routes"]["SF"]["null_completions"], a["routes"]["SF"]["null_Z"]), (180, 0, 0))
        self.assertEqual(list(a["routes"]["SF"]["non_completion_errors"]), ["apex:System.StringException: ERROR:aiplatform.ModelsAPI.createChatGenerations_ResponseException|Script-thrown exception"])
        self.assertEqual(a["route_agreement_within_10pp"], "not evaluable")
        self.assertIsNone(a["trust_layer_input_token_overhead_median"])

    def test_zero_byte_forms_and_in_org_null_test(self):
        out, _ = self.run_once()
        sf = verify.verify(out)["analysis"]["opus-4-6"]["routes"]["SF"]
        self.assertEqual(sf["zero_byte_forms"], {"Z0": 0, "Z2": 90})
        self.assertEqual((sf["zero_byte_toxicity_scanned"], sf["zero_byte_toxicity_flagged"]), (90, 0))
        c = v.classify_sf(200, sf_payload(None), None)
        self.assertEqual((c["content_is_null"], c["serialized_content_null"], c["native"]), (True, True, "Z2"))
        lying = json.loads(sf_payload(None)); msg = lying["exceptionMessage"]; p = json.loads(msg[msg.index("RESULT:") + 7:])
        p["full"]["generationDetails"]["generations"][0]["content"] = ""  # serializer carried "" for an in-org null
        lying["exceptionMessage"] = "System.StringException: RESULT:" + json.dumps(p)
        c = v.classify_sf(200, json.dumps(lying).encode(), None)
        self.assertEqual((c["content_is_null"], c["serialized_content_null"], c["native"]), (True, False, "Z2"))

    def test_empty_string_is_Z0(self):
        out, _ = self.run_once(sf="void_empty_string")
        cells = verify.verify(out)["analysis"]["opus-4-6"]["routes"]["SF"]["cells"]
        self.assertEqual(cells["Be silence."]["classes"], {"Z0": 30})

    def test_wrong_served_model_is_unverifiable(self):
        out, _ = self.run_once(sf="wrong_model")
        r = verify.verify(out)
        self.assertTrue(r["unverifiable"]); self.assertEqual(r["analysis"]["opus-4-6"]["route_agreement_within_10pp"], "not evaluable")

    def test_tamper_detected(self):
        out, _ = self.run_once()
        target = out / "receipts" / "0001" / "response.bin"
        target.write_bytes(target.read_bytes() + b" ")
        with self.assertRaises(ValueError):
            verify.verify(out)
        v.write_manifest(out)
        with self.assertRaises(ValueError):
            verify.verify(out)

    def test_da_spend_cap_stops_da_lane_only(self):
        out, status = self.run_once(usage_tokens=166_000)  # USD 4.98 per request at list price; cap reached after five
        self.assertEqual(status, "INCOMPLETE")
        r = verify.verify(out)
        self.assertEqual(r["reason"], "da_spend_cap")
        self.assertEqual(r["attempted"] + (360 - r["attempted"]), 360)
        self.assertLessEqual(Decimal(r["da_accounted_spend"]), v.DA_SPEND_CAP)
        sf = r["analysis"]["opus-4-6"]["routes"]["SF"]
        self.assertEqual((sf["null_attempted"], sf["control_attempted"]), (90, 90))  # the SF lane runs to completion

    def test_existing_output_refused(self):
        from unittest import mock
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        fake_root = Path(tmp.name) / "root"; fake_root.mkdir(); (fake_root / "PREREG.md").write_text("x"); v.write_manifest(fake_root)
        with mock.patch("runner.git", return_value=None), mock.patch.object(v, "ROOT", fake_root), \
             mock.patch.object(v, "check_frozen_sources", lambda: None), self.assertRaises(SystemExit) as c:
            runner.preflight(Path(tmp.name))
        self.assertIn("never resumed", str(c.exception))


class Smoke(unittest.TestCase):
    def test_smoke_targets(self):
        import smoke
        self.assertIn("req.modelName = 'sfdc_ai__DefaultBedrockAnthropicClaude46Sonnet';", smoke.smoke_apex("sonnet-4-6", "Be speech."))
        self.assertEqual(json.loads(smoke.smoke_da_body("sonnet-5", "Be speech."))["model"], "claude-sonnet-5")
        self.assertIn("u.content = 'Say hi.'", smoke.probe_script("sfdc_ai__DefaultBedrockAnthropicClaude46Opus"))


class Documents(unittest.TestCase):
    def test_questions_numbered(self):
        n = [int(m) for m in re.findall(r"^(\d+)\. ", (ROOT / "PREDICTION_QUESTIONS.md").read_text(), re.M)]
        self.assertEqual(n, list(range(1, 11)))

    def test_no_secrets_or_local_paths(self):
        patterns = [re.compile(rb"/" + rb"Users/[^/\s]+/"), re.compile(rb"sk-" + rb"[A-Za-z0-9_-]{32,}"),
                    re.compile(rb"3MVG9" + rb"[A-Za-z0-9_.]{40,}"), re.compile(rb"[0-9A-F]{64}SECRET")]
        for p in ROOT.rglob("*"):
            rel = p.relative_to(ROOT)
            if not p.is_file() or any(x in {".git", ".venv", "__pycache__"} for x in rel.parts):
                continue
            data = p.read_bytes()
            for pat in patterns:
                self.assertIsNone(pat.search(data), str(rel))


if __name__ == "__main__":
    unittest.main()
