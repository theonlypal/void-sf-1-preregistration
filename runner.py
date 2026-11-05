"""Frozen VOID-SF-1 runner. Credentials enter only through two private files and are never written; the instance host is recorded in RUN.json."""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import threading
import time
from decimal import Decimal
from pathlib import Path

import voidsf as v


def git(*args):
    try:
        return subprocess.check_output(["git", "-C", str(v.ROOT), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def preflight(output: Path) -> dict:
    if not (v.ROOT / "PREREG.md").is_file():
        raise SystemExit("Predictions are not registered: PREREG.md is absent")
    v.check_frozen_sources()
    v.verify_manifest(v.ROOT)
    commit = git("rev-parse", "HEAD")
    if commit is not None and git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Tracked checkout differs from the frozen commit")
    resolved = output.resolve()
    if resolved == v.ROOT or v.ROOT in resolved.parents:
        raise SystemExit("Output must be outside the repository")
    if output.exists():
        raise SystemExit("Output exists; a partial run is never resumed")
    return {"commit": commit, "repo_manifest_sha256": v.sha256((v.ROOT / "SHA256SUMS").read_bytes())}


def execute(output: Path, identity: dict, sf_env: dict, da_key: str, sf_transport=v.sf_transport, da_transport=v.da_transport,
            sf_pause: float = v.SF_PAUSE_SECONDS, da_pause: float = v.DA_PAUSE_SECONDS, sleep=time.sleep) -> str:
    output.mkdir(parents=True)
    (output / "receipts").mkdir()
    run = {"study": "VOID-SF-1", **identity, "schedule_sha256": v.sha256(v.schedule_bytes()),
           "system_sha256": v.SYSTEM_SHA256, "input_sha256": v.INPUT_SHA256, "vendor_sha256": v.VENDOR_SHA256,
           "models": v.MODELS, "da_max_tokens": v.DA_MAX_TOKENS, "sf_pause_seconds": sf_pause, "da_pause_seconds": da_pause,
           "price_per_million": {m: [str(a), str(b)] for m, (a, b) in v.PRICE_PER_MILLION.items()},
           "reservation": {m: str(v.reservation(m)) for m in v.MODELS}, "da_spend_cap": str(v.DA_SPEND_CAP),
           "timeout_seconds": v.TIMEOUT_SECONDS, "sf_instance_host": v.urllib.parse.urlparse(sf_env["SF_INSTANCE_URL"]).hostname,
           "python": platform.python_version(), "platform": platform.platform()}
    run_bytes = v.canonical(run)
    (output / "RUN.json").write_bytes(run_bytes)
    chain = v.Chain(output / "events.jsonl")
    lock = threading.Lock()
    chain.add("run_start", run_sha256=v.sha256(run_bytes))
    slots = v.schedule()
    lanes = {r: [s for s in slots if s["route"] == r] for r in v.ROUTES}
    state = {"accounted": Decimal("0"), "attempted": 0, "stop": {"SF": False, "DA": False}, "reason": None}

    def record(slot, request_bytes, result, extra):
        folder = output / "receipts" / slot["slot"]
        folder.mkdir()
        (folder / "request.json").write_bytes(request_bytes)
        (folder / "response.bin").write_bytes(result["raw"])
        c = v.classify(slot["route"], result["http_status"], result["raw"], result["transport_error"])
        meta = {**slot, "http_status": result["http_status"], "transport_error": result["transport_error"],
                "dispatch_utc": result["dispatch_utc"], "receipt_utc": result["receipt_utc"], **c, **extra}
        (folder / "meta.json").write_bytes(v.canonical(meta))
        files = {p.name: v.sha256(p.read_bytes()) for p in sorted(folder.iterdir())}
        with lock:
            chain.add("trial_end", slot=slot["slot"], files=files)
            state["attempted"] += 1

    def da_lane():
        for i, slot in enumerate(lanes["DA"]):
            if state["stop"]["DA"]:
                break
            reserve = v.reservation(slot["model"])
            with lock:
                if v.DA_SPEND_CAP - state["accounted"] < reserve:
                    state["stop"]["DA"], state["reason"] = True, "da_spend_cap"
                    break
                chain.add("trial_start", slot=slot["slot"], request_sha256=v.sha256(v.da_body(slot["model"], slot["input"])),
                          accounted=str(state["accounted"]), reservation=str(reserve))
            body = v.da_body(slot["model"], slot["input"])
            result = da_transport(da_key, body, v.TIMEOUT_SECONDS)
            c_usage = None
            try:
                c_usage = json.loads(result["raw"]).get("usage")
            except Exception:
                pass
            amount, basis = v.da_charge(slot["model"], result["http_status"], c_usage, result["transport_error"])
            with lock:
                state["accounted"] += amount
                accounted = state["accounted"]
            record(slot, body, result, {"charge": str(amount), "charge_basis": basis, "accounted_after": str(accounted)})
            if i < len(lanes["DA"]) - 1:
                sleep(da_pause)

    def sf_lane():
        for i, slot in enumerate(lanes["SF"]):
            if state["stop"]["SF"]:
                break
            request_bytes = v.sf_request_record(slot["model"], slot["input"])
            with lock:
                chain.add("trial_start", slot=slot["slot"], request_sha256=v.sha256(request_bytes))
            result = sf_transport(sf_env, v.apex_script(slot["model"], slot["input"]), v.TIMEOUT_SECONDS)
            record(slot, request_bytes, result, {"token_status": result.get("token_status")})
            if i < len(lanes["SF"]) - 1:
                sleep(sf_pause)

    threads = [threading.Thread(target=sf_lane, name="SF"), threading.Thread(target=da_lane, name="DA")]
    interrupted = False
    try:
        for t in threads:
            t.start()
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.5)
    except KeyboardInterrupt:
        interrupted = True
        state["stop"]["SF"] = state["stop"]["DA"] = True
        state["reason"] = state["reason"] or "interrupted"
        for t in threads:
            t.join()
    if state["attempted"] == len(slots):
        status, reason = "COMPLETE", None
    else:
        status, reason = "INCOMPLETE", state["reason"] or ("interrupted" if interrupted else "unknown")
    chain.add("run_end", status=status, reason=reason, interrupted=interrupted, scheduled=len(slots),
              attempted=state["attempted"], unattempted=len(slots) - state["attempted"], da_accounted_spend=str(state["accounted"]))
    chain.close()
    v.write_manifest(output)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sf-credentials", required=True, help="Private file with SF_INSTANCE_URL, SF_CLIENT_ID, SF_CLIENT_SECRET")
    parser.add_argument("--anthropic-key-file", required=True, help="Private file containing the Anthropic API key")
    parser.add_argument("--authorize", action="store_true", help="Required. Confirms authorization to spend Einstein requests and up to USD 25 on the direct arm.")
    args = parser.parse_args()
    if not args.authorize:
        raise SystemExit("Execution requires --authorize")
    identity = preflight(args.output)
    sf_env = v.read_env_file(args.sf_credentials)
    da_key = open(os.path.expanduser(args.anthropic_key_file)).read().strip()
    status = execute(args.output, identity, sf_env, da_key)
    print(json.dumps({"status": status, "output": str(args.output)}))


if __name__ == "__main__":
    main()
