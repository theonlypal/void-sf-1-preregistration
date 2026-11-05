"""Offline VOID-SF-1 verifier: manifest, event chain, request bytes, re-classification, direct-arm ledger, analysis."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import voidsf as v


def verify(run_dir: Path, expected_commit=None, expected_manifest_sha256=None) -> dict:
    run_dir = Path(run_dir)
    files = v.verify_manifest(run_dir)
    run_bytes = (run_dir / "RUN.json").read_bytes()
    run = json.loads(run_bytes)
    expected = {"study": "VOID-SF-1", "schedule_sha256": v.sha256(v.schedule_bytes()), "system_sha256": v.SYSTEM_SHA256,
                "input_sha256": v.INPUT_SHA256, "vendor_sha256": v.VENDOR_SHA256, "models": v.MODELS,
                "da_max_tokens": v.DA_MAX_TOKENS, "da_spend_cap": str(v.DA_SPEND_CAP),
                "reservation": {m: str(v.reservation(m)) for m in v.MODELS},
                "sf_pause_seconds": v.SF_PAUSE_SECONDS, "da_pause_seconds": v.DA_PAUSE_SECONDS, "timeout_seconds": v.TIMEOUT_SECONDS}
    for key, value in expected.items():
        if run.get(key) != value:
            raise ValueError("Run metadata differs from the frozen protocol: " + key)
    if expected_manifest_sha256 is not None and run.get("repo_manifest_sha256") != expected_manifest_sha256:
        raise ValueError("Run repository manifest differs from the verifying checkout")
    if expected_commit is not None and run.get("commit") is not None and run.get("commit") != expected_commit:
        raise ValueError("Run commit differs from the verifying checkout")
    events = v.verify_chain(run_dir / "events.jsonl")
    if not events or events[0]["kind"] != "run_start" or events[0]["run_sha256"] != v.sha256(run_bytes) or events[-1]["kind"] != "run_end":
        raise ValueError("Run metadata not bound to the event chain")
    by_slot = {s["slot"]: s for s in v.schedule()}
    started, ended, accounted, records, mismatches = {}, [], Decimal("0"), [], []
    for e in events[1:-1]:
        if e["kind"] == "trial_start":
            slot = by_slot[e["slot"]]
            req = (run_dir / "receipts" / slot["slot"] / "request.json").read_bytes()
            expected_req = v.da_body(slot["model"], slot["input"]) if slot["route"] == "DA" else v.sf_request_record(slot["model"], slot["input"])
            if req != expected_req or e["request_sha256"] != v.sha256(req):
                raise ValueError("Request bytes differ at slot " + slot["slot"])
            if slot["route"] == "DA":
                reserve = v.reservation(slot["model"])
                if e["reservation"] != str(reserve) or v.DA_SPEND_CAP - Decimal(e["accounted"]) < reserve:
                    raise ValueError("Direct-arm ledger or dispatch rule differs at slot " + slot["slot"])
            started[slot["slot"]] = e
        elif e["kind"] == "trial_end":
            slot = by_slot[e["slot"]]
            if slot["slot"] not in started:
                raise ValueError("Completion without dispatch at slot " + slot["slot"])
            folder = run_dir / "receipts" / slot["slot"]
            if e["files"] != {p.name: v.sha256(p.read_bytes()) for p in sorted(folder.iterdir())}:
                raise ValueError("Receipt bytes not bound to the event chain at slot " + slot["slot"])
            meta = json.loads((folder / "meta.json").read_bytes())
            raw = (folder / "response.bin").read_bytes()
            c = v.classify(slot["route"], meta["http_status"], raw, meta["transport_error"])
            for k, val in c.items():
                if meta.get(k) != val:
                    raise ValueError(f"Re-classification differs at slot {slot['slot']}: {k}")
            if slot["route"] == "DA":
                usage = None
                try:
                    usage = json.loads(raw).get("usage")
                except Exception:
                    pass
                amount, basis = v.da_charge(slot["model"], meta["http_status"], usage, meta["transport_error"])
                if meta["charge"] != str(amount) or meta["charge_basis"] != basis:
                    raise ValueError("Direct-arm charge differs at slot " + slot["slot"])
                accounted += amount
            if v.model_mismatch(slot["route"], slot["model"], c):
                mismatches.append(slot["slot"])
            records.append({**slot, **c})
            ended.append(slot["slot"])
        else:
            raise ValueError("Unexpected event kind")
    if set(started) != set(ended):
        raise ValueError("Dispatched slots without completion")
    if {p.name for p in (run_dir / "receipts").iterdir()} != set(ended):
        raise ValueError("Receipt folder set differs from completed slots")
    end = events[-1]
    scheduled = len(by_slot)
    status = "COMPLETE" if len(ended) == scheduled else "INCOMPLETE"
    if (end["status"], end["attempted"], end["unattempted"], end["da_accounted_spend"]) != (status, len(ended), scheduled - len(ended), str(accounted)):
        raise ValueError("Terminal event differs from the reconstructed run")
    unverifiable = bool(mismatches)
    return {"status": status, "reason": end["reason"], "interrupted": end["interrupted"], "scheduled": scheduled, "attempted": len(ended),
            "files": files, "da_accounted_spend": str(accounted), "unverifiable": unverifiable, "model_mismatch_slots": mismatches,
            "analysis": v.analyze(records, unverifiable)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    v.verify_manifest(v.ROOT)
    manifest = v.sha256((v.ROOT / "SHA256SUMS").read_bytes())
    try:
        commit = subprocess.check_output(["git", "-C", str(v.ROOT), "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        commit = None
    result = verify(args.run_dir, expected_commit=commit, expected_manifest_sha256=manifest)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    if result["unverifiable"]:
        print("UNVERIFIABLE: served-model mismatch at " + ", ".join(result["model_mismatch_slots"]))
        sys.exit(2)
    print(f"VERIFIED: {result['attempted']}/{result['scheduled']} slots; {result['status']}; SHA256SUMS OK ({result['files']} files); "
          f"event chain, request bytes, classes and direct-arm ledger match.")


if __name__ == "__main__":
    main()
