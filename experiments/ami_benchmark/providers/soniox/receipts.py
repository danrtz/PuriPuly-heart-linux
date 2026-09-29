"""Verify completed native results and predictions; emit seven-case per-arm receipts.

No provider requests. Reference speech/labels are never loaded by this script.
"""
from __future__ import annotations
import argparse

from hashlib import sha256
import json
from pathlib import Path

from run import ARMS, BENCH, ROOT, conversion


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=ARMS, help="Verify one completed arm instead of all four")
    args = parser.parse_args()
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cases"]) == 7
    lock = json.loads((ROOT / "sdk" / "package-lock.json").read_text(encoding="utf-8"))
    package = lock["packages"]["node_modules/@soniox/node"]
    if package["version"] != "2.3.0":
        raise ValueError("Wrong Soniox SDK installation pin")
    hypothesis = {"method": "soniox_sdk_speaker_segments", "package": "@soniox/node",
                  "version": "2.3.0", "source_commit": "8661b750e6cbd0a2c382f6b79c7c198e29c4a2b0",
                  "package_integrity": package["integrity"], "sdk_bridge_sha256": digest(ROOT / "sdk" / "segments.mjs"),
                  "group_by": ["speaker"], "interval": "first defined token start to last defined token end in each speaker run",
                  "post_group_gap_filling": False, "clock_correction": False}
    for arm in (args.arm,) if args.arm else ARMS:
        receipts = []
        for case in manifest["cases"]:
            case_id = case["id"]
            native = Path("results") / case_id / f"{arm}.json"
            result_path = ROOT / native
            result = json.loads(result_path.read_text(encoding="utf-8"))
            prediction = ROOT / "predictions" / arm / f"{case_id}.rttm"
            sdk_output = Path("sdk_output") / arm / f"{case_id}.json"
            if not result["completed"] or result["case_id"] != case_id or result["arm"] != arm:
                raise ValueError(f"Incomplete/wrong native result: {case_id}/{arm}")
            if result["source_pcm_sha256"] != case["clip_pcm_sha256"] or result["source_wav_sha256"] != case["clip_wav_sha256"]:
                raise ValueError(f"Wrong input: {case_id}/{arm}")
            if digest(BENCH / case["audio"]) != case["clip_wav_sha256"]:
                raise ValueError(f"Changed WAV: {case_id}/{arm}")
            if result["native_artifact_sha256"] != sha256(json.dumps({"tokens": result["tokens"],
                    "messages": result.get("messages", [])}, ensure_ascii=False, sort_keys=True).encode()).hexdigest():
                raise ValueError(f"Changed native tokens: {case_id}/{arm}")
            if arm != "async_full_file":
                state = result["lifecycle"]
                if (state["websocket_requests"] != 1 or state["finalize_requested"] != state["fin_received"]
                        or not state["finished_received"]):
                    raise ValueError(f"Incomplete realtime stream: {case_id}/{arm}")
            elif (result["lifecycle"]["status"] != "completed" or not result["cleanup"]["transcription_deleted"]
                  or not result["cleanup"]["file_deleted"] or result["error"]):
                raise ValueError(f"Incomplete async lifecycle: {case_id}/{arm}")
            expected, artifact = conversion(result, case["duration_s"])
            if prediction.read_text(encoding="utf-8") != expected:
                raise ValueError(f"Wrong RTTM/native SDK projection: {case_id}/{arm}")
            if json.loads((ROOT / sdk_output).read_text(encoding="utf-8")) != json.loads(json.dumps(artifact)):
                raise ValueError(f"Wrong SDK segment/projection artifact: {case_id}/{arm}")
            receipts.append({"id": case_id, "input_pcm_sha256": case["clip_pcm_sha256"],
                             "prediction_rttm_sha256": digest(prediction), "completed": True,
                             "native_result": native.as_posix(), "native_result_sha256": digest(result_path),
                             "sdk_output": sdk_output.as_posix(), "sdk_output_sha256": digest(ROOT / sdk_output),
                             "sdk_groups": len(artifact["sdk_segments"]),
                             "projection_diagnostics": artifact["projection_diagnostics"]})
        directory = ROOT / "predictions" / arm
        if sorted(path.name for path in directory.glob("*.rttm")) != sorted(f"{case['id']}.rttm" for case in manifest["cases"]):
            raise ValueError(f"Extra/missing RTTM in {arm}")
        receipt = {"model": "stt-async-v5" if arm == "async_full_file" else "stt-rt-v5",
                   "mode": arm, "hypothesis": hypothesis, "cases": receipts}
        (directory / "provenance.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"verified={arm} cases={len(receipts)}")
if __name__ == "__main__":
    main()
