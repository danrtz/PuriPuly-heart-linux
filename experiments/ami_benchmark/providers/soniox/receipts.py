"""Verify completed native results and predictions; emit seven-case per-arm receipts.

No provider requests. Reference speech/labels are never loaded by this script.
"""
from __future__ import annotations
import argparse

from hashlib import sha256
import json
from pathlib import Path

from run import ARMS, BENCH, ROOT, mapped_intervals


def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=ARMS, help="Verify one completed arm instead of all four")
    args = parser.parse_args()
    manifest = json.loads((BENCH / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["cases"]) == 7
    for arm in (args.arm,) if args.arm else ARMS:
        receipts = []
        for case in manifest["cases"]:
            case_id = case["id"]
            native = Path("results") / case_id / f"{arm}.json"
            result_path = ROOT / native
            result = json.loads(result_path.read_text(encoding="utf-8"))
            prediction = ROOT / "predictions" / arm / f"{case_id}.rttm"
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
            intervals, diagnostic = mapped_intervals(result["tokens"], result["timeline"], case["duration_s"])
            expected = "".join(f"SPEAKER {case_id} 1 {a:.6f} {b-a:.6f} <NA> <NA> {speaker} <NA> <NA>\n"
                for a, b, speaker in intervals)
            if prediction.read_text(encoding="utf-8") != expected or digest(prediction) != result["prediction_sha256"]:
                raise ValueError(f"Wrong RTTM/native projection: {case_id}/{arm}")
            if diagnostic != result["conversion"]:
                raise ValueError(f"Changed diagnostics: {case_id}/{arm}")
            receipts.append({"id": case_id, "input_pcm_sha256": case["clip_pcm_sha256"],
                             "prediction_rttm_sha256": digest(prediction), "completed": True,
                             "native_result": native.as_posix(), "native_result_sha256": digest(result_path)})
        directory = ROOT / "predictions" / arm
        if sorted(path.name for path in directory.glob("*.rttm")) != sorted(f"{case['id']}.rttm" for case in manifest["cases"]):
            raise ValueError(f"Extra/missing RTTM in {arm}")
        receipt = {"model": "stt-async-v5" if arm == "async_full_file" else "stt-rt-v5",
                   "mode": arm, "cases": receipts}
        (directory / "provenance.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(f"verified={arm} cases={len(receipts)}")


if __name__ == "__main__":
    main()
