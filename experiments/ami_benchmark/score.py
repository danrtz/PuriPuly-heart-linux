import argparse
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path

from pyannote.core import Annotation, Segment, Timeline
from pyannote.metrics.diarization import DiarizationErrorRate

ROOT = Path(__file__).resolve().parent


def load_rttm(path, case_id, duration):
    if not path.is_file():
        raise FileNotFoundError(f"Missing completed-case RTTM (use an empty file for no speech): {path}")
    annotation = Annotation(uri=case_id)
    speakers = set()
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split()
        if len(parts) != 10 or parts[0] != "SPEAKER" or parts[1] != case_id or parts[2] != "1" or not parts[7] or parts[7] == "<NA>":
            raise ValueError(f"Invalid RTTM row {path}:{index}: {line}")
        try:
            start, length = float(parts[3]), float(parts[4])
        except ValueError as exc:
            raise ValueError(f"Invalid time at {path}:{index}") from exc
        if not all(map(math.isfinite, (start, length))) or start < 0 or length <= 0 or start + length > duration:
            raise ValueError(f"Out-of-bounds RTTM row {path}:{index}: {line}")
        annotation[Segment(start, start + length), index] = parts[7]
        speakers.add(parts[7])
    return annotation, speakers


def score_case(case, predictions):
    case_id = case["id"]
    duration = case["duration_s"]
    ref_path = ROOT / case["reference_rttm"]
    uem_path = ROOT / case["uem"]
    if hashlib.sha256(ref_path.read_bytes()).hexdigest() != case["clip_reference_sha256"] or hashlib.sha256(uem_path.read_bytes()).hexdigest() != case["uem_sha256"]:
        raise ValueError(f"Published reference/UEM digest mismatch: {case_id}")
    uem_parts = uem_path.read_text(encoding="utf-8").split()
    if uem_parts != [case_id, "1", "0", str(duration)]:
        raise ValueError(f"Expected full-duration UEM for {case_id}")
    reference, ref_speakers = load_rttm(ref_path, case_id, duration)
    hypothesis, hyp_speakers = load_rttm(predictions / f"{case_id}.rttm", case_id, duration)
    metric = DiarizationErrorRate(collar=0.0, skip_overlap=False)
    components = metric(reference, hypothesis, uem=Timeline([Segment(0, duration)], uri=case_id), detailed=True)
    measures = {key: float(components[key]) for key in ("total", "missed detection", "false alarm", "confusion")}
    return {"id": case_id, "pair_with": case["pair_with"], "duration_s": duration, "reference_speakers": len(ref_speakers), "predicted_speakers": len(hyp_speakers), "speaker_count_absolute_error": abs(len(ref_speakers) - len(hyp_speakers)), "der": float(components["diarization error rate"]), **measures}


def score(manifest_path, predictions):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("benchmark") != "AMItest-derived scenario subset" or len(manifest.get("cases", [])) != 7:
        raise ValueError("Expected the published seven-case scenario subset manifest")
    ids = [case["id"] for case in manifest["cases"]]
    if len(set(ids)) != len(ids):
        raise ValueError("Repeated case ID in manifest")
    unexpected = sorted(path.name for path in predictions.glob("*.rttm") if path.stem not in ids)
    if unexpected:
        raise ValueError(f"Unexpected prediction RTTM files: {unexpected}")
    results = [score_case(case, predictions) for case in manifest["cases"]]
    def aggregate(rows):
        sums = {key: sum(row[key] for row in rows) for key in ("total", "missed detection", "false alarm", "confusion")}
        return {"cases": len(rows), "der": sum(sums[k] for k in ("missed detection", "false alarm", "confusion")) / sums["total"], "speaker_count_accuracy": sum(row["speaker_count_absolute_error"] == 0 for row in rows) / len(rows), "speaker_count_mae": sum(row["speaker_count_absolute_error"] for row in rows) / len(rows), **sums}
    return {"benchmark": manifest["benchmark"], "metric": "pyannote.metrics DiarizationErrorRate; full-duration UEM; collar=0; skip_overlap=False; optimal speaker mapping; native RTTM time support", "pyannote_metrics_version": importlib.metadata.version("pyannote.metrics"), "independent_six": aggregate([row for row in results if row["pair_with"] is None]), "paired_far_field": aggregate([row for row in results if row["pair_with"] is not None]), "per_case": results}


def main():
    parser = argparse.ArgumentParser(description="Score seven AMItest-derived scenario cases, with paired far-field reported separately")
    parser.add_argument("--manifest", type=Path, default=ROOT / "manifest.json")
    parser.add_argument("--predictions", type=Path, required=True, help="Directory with one <case-id>.rttm per case, including explicit empty files")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(score(args.manifest, args.predictions), indent=2) + "\n"
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
