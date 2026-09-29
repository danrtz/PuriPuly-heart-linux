from collections import Counter
from hashlib import sha256
import argparse
import json
from pathlib import Path

from score import score, score_case

ROOT = Path(__file__).resolve().parent
SONIOX_ARMS = ("continuous", "forced", "segmented", "async_full_file")


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def collect_run(provider, arm, owner, predictions, recorded_score, manifest, allow_incomplete=False):
    provenance_path = predictions / "provenance.json"
    provenance = read_json(provenance_path)
    expected = {case["id"]: case for case in manifest["cases"]}
    receipts = provenance["cases"]
    completed_ids = {row["id"] for row in receipts}
    if len(receipts) != len(completed_ids) or not completed_ids <= set(expected):
        raise ValueError(f"Unknown or repeated provenance cases: {provider}/{arm}")
    missing = [case_id for case_id in expected if case_id not in completed_ids]
    if missing and (
        not allow_incomplete or provenance.get("status") != "incomplete"
        or set(provenance.get("missing_cases", [])) != set(missing)
    ):
        raise ValueError(f"Incomplete provenance cases: {provider}/{arm}: {missing}")
    if {path.stem for path in predictions.glob("*.rttm")} != completed_ids:
        raise ValueError(f"Prediction files differ from completed receipts: {provider}/{arm}")
    if provenance["mode"] != arm:
        raise ValueError(f"Wrong provenance mode: {provider}/{arm}")
    token_widths = Counter()
    for row in receipts:
        case = expected[row["id"]]
        if row["input_pcm_sha256"] != case["clip_pcm_sha256"]:
            raise ValueError(f"Wrong input waveform: {provider}/{arm}/{case['id']}")
        if row["prediction_rttm_sha256"] != digest(predictions / f"{case['id']}.rttm"):
            raise ValueError(f"Changed prediction: {provider}/{arm}/{case['id']}")
        if provider != "Nemotron":
            if row.get("completed") is not True:
                raise ValueError(f"Incomplete inference: {provider}/{arm}/{case['id']}")
            native_path = owner / row["native_result"]
            if digest(native_path) != row["native_result_sha256"]:
                raise ValueError(f"Changed native result: {provider}/{arm}/{case['id']}")
            if provider == "Soniox":
                for token in read_json(native_path)["tokens"]:
                    start, end = token.get("start_ms"), token.get("end_ms")
                    if isinstance(start, (int, float)) and isinstance(end, (int, float)):
                        token_widths[end - start] += 1
    if missing:
        computed = {
            "independent_six": None,
            "paired_far_field": None,
            "per_case": [score_case(case, predictions) for case in manifest["cases"]
                         if case["id"] in completed_ids],
        }
    else:
        computed = score(ROOT / "manifest.json", predictions)
        if computed != read_json(recorded_score):
            raise ValueError(f"Recorded score no longer matches RTTMs: {provider}/{arm}")
    return {
        "provider": provider,
        "arm": arm,
        "model": provenance["model"],
        "status": "incomplete" if missing else "complete",
        "missing_cases": missing,
        "reused_prior_inference": provider == "Nemotron",
        "provenance": provenance_path.relative_to(ROOT).as_posix(),
        "provenance_sha256": digest(provenance_path),
        "score_artifact": None if missing else recorded_score.relative_to(ROOT).as_posix(),
        "score_artifact_sha256": None if missing else digest(recorded_score),
        "score": computed,
        "native_token_width_counts_ms": {str(width): count for width, count in sorted(token_widths.items())},
    }


def compare(allow_incomplete=False):
    manifest = read_json(ROOT / "manifest.json")
    rows = []
    soniox = ROOT / "providers" / "soniox"
    for arm in SONIOX_ARMS:
        rows.append(collect_run("Soniox", arm, soniox, soniox / "predictions" / arm,
                                soniox / "scores" / f"{arm}.json", manifest))
    qwen = ROOT / "providers" / "qwen"
    rows.append(collect_run("Qwen", "realtime", qwen, qwen / "predictions",
                            qwen / "score.json", manifest, allow_incomplete=allow_incomplete))
    rows.append(collect_run("Nemotron", "ultra_low_latency", ROOT,
                            ROOT / "predictions" / "nemotron_ultra_low_latency",
                            ROOT / "nemotron_ultra_low_latency_score.json", manifest))
    return {
        "benchmark": manifest["benchmark"],
        "manifest_sha256": digest(ROOT / "manifest.json"),
        "status": "incomplete" if any(row["missing_cases"] for row in rows) else "complete",
        "new_completed_case_runs": sum(len(row["score"]["per_case"]) for row in rows
                                       if not row["reused_prior_inference"]),
        "expected_new_case_runs": 35,
        "reused_case_runs": 7,
        "cases": [{key: case[key] for key in ("id", "duration_s", "pair_with", "clip_pcm_sha256")}
                  for case in manifest["cases"]],
        "runs": rows,
    }


def render_report(comparison):
    rows = comparison["runs"]
    lines = [
        "# AMI scenario subset: native-output provider comparison", "",
        f"Status: **{comparison['status']}**. Newly completed case/arm runs: **{comparison['new_completed_case_runs']}/{comparison['expected_new_case_runs']}**. The seven prior Nemotron ultra-low-latency CPU inferences are reused without new model calls. A missing case has no score, is not an empty completed prediction, and prevents that arm's complete benchmark aggregate. The far-field case repeats the overlap case's content through a different microphone and is excluded from the six-primary-case aggregate.", "",
        "**Interpretation:** these are standard DER scores of each provider's native timestamped output, not a controlled ranking of speaker-identity recognition alone. Soniox exposes word-token spans, Qwen speech-event spans, and Nemotron diarization segments. Their speech-time support differs. No reference-based gap filling, token stretching, or dominant-speaker reduction is applied. Read miss, false alarm, confusion and speaker counts together.", "",
        "The standard scoring protocol is unchanged: pyannote.metrics 4.0.0, collar 0, overlapping speech included, complete clip UEM and optimal speaker-label mapping per case. `score_case` exposes the existing per-case calculation for explicitly incomplete evidence without relaxing the seven-case `score.py` CLI. Complete-arm scores must match their retained score artifacts; input, native-result and prediction digests are checked against provenance.", "",
        "Native intervals are intersected with actual mapped source-audio support and the fixed clip UEM. Entirely out-of-audio spans are omitted and boundary-straddling spans are clipped, with original outputs and conversion diagnostics retained. This does not shift timestamps to fit the reference: native in-window timestamp errors remain scored errors. Unconfirmed event tails are not completed using the reference.", "",
        "## Six primary windows: pooled speaker-time errors", "",
        "All error columns are percentages of scored reference speaker-time. DER = Miss + FA + Confusion; individual displayed values are rounded.", "",
        "| Provider / arm | DER % | Miss % | FA % | Confusion % | Speaker-count accuracy | Count MAE |", 
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        value = row["score"]["independent_six"]
        if value is None:
            lines.append(f"| {row['provider']} / {row['arm']} | INCOMPLETE | — | — | — | — | — |")
            continue
        parts = [100 * value[key] / value["total"] for key in ("missed detection", "false alarm", "confusion")]
        lines.append(f"| {row['provider']} / {row['arm']} | {100 * value['der']:.2f} | {parts[0]:.2f} | {parts[1]:.2f} | {parts[2]:.2f} | {100 * value['speaker_count_accuracy']:.2f}% | {value['speaker_count_mae']:.3f} |")
    lines += ["", "## Soniox native time-support diagnostics", "",
              "Counts below come from all seven saved native outputs per arm, before source/UEM projection. A short token pulse is not a continuous speech region. High missed-speech DER under this literal-support protocol does not mean the same percentage of words or speaker identities is wrong.", "",
              "| Arm | Native token widths in ms: count |",
              "| --- | --- |"]
    for row in rows:
        if row["provider"] == "Soniox":
            widths = ", ".join(f"{width}: {count}" for width, count in row["native_token_width_counts_ms"].items())
            lines.append(f"| {row['arm']} | {widths} |")
    lines += ["", "## Per-case DER (%)", "",
              "| Case | " + " | ".join(f"{row['provider']} / {row['arm']}" for row in rows) + " |",
              "| --- | " + " | ".join("---:" for _ in rows) + " |"]
    indexed = [{case["id"]: case for case in row["score"]["per_case"]} for row in rows]
    for case in comparison["cases"]:
        values = " | ".join(f"{100 * result[case['id']]['der']:.2f}" if case["id"] in result
                            else "NOT COMPLETED" for result in indexed)
        lines.append(f"| {case['id']} | {values} |")
    lines += ["", "## Reference / predicted speaker counts", "",
              "| Case | Reference | " + " | ".join(f"{row['provider']} / {row['arm']}" for row in rows) + " |",
              "| --- | ---: | " + " | ".join("---:" for _ in rows) + " |"]
    for case in comparison["cases"]:
        values = " | ".join(str(result[case["id"]]["predicted_speakers"]) if case["id"] in result
                            else "NOT COMPLETED" for result in indexed)
        lines.append(f"| {case['id']} | {indexed[0][case['id']]['reference_speakers']} | {values} |")
    lines += [
        "", "## Execution evidence and limits", "",
        "- [Soniox execution and conversion](providers/soniox/execution_report.md): continuous RT, fixed-six-second finalize RT, actual app-equivalent VAD/SmartTurn segmentation RT, and full-file async. Segmented provider time is mapped back to original source time; padding is not speech evidence.",
        "- [Qwen execution and conversion](providers/qwen/execution_report.md): native speech-start speaker IDs correlated with native stop events; item IDs are not speaker IDs.",
        "- [Retained Nemotron execution](report.md): official ultra-low-latency preset, nominal 0.32-second input buffer. Unpaced CPU compute time is not live end-to-end latency.",
        "- Each case starts fresh state; the 600-second case retains one continuous session/cache. Speaker identity is not compared across cases. Six primary windows are nonduplicated audio, not independent participants; several meetings can share participants.",
        "- This is an annotation-selected AMI test subset, not the full AMI test score, ASR/translation accuracy, a statistically independent population estimate, or evidence about six-plus speakers and VRChat. The forced-aligned reference covers words, not all vocal sounds; boundaries and missing annotations can affect DER.",
        "- No oracle speaker counts or reference timings are supplied to inference. Unattributed output is reported by each provider but never invented as an optimally mappable reference speaker. Native output gaps remain gaps; a completed run is not necessarily a complete speech transcription.",
        "- Benchmark waveforms, references, scoring semantics and previous Nemotron evidence remain unchanged. No production UI, configuration or application behavior changes.",
        "", "Rebuild this comparison offline with `experiments/ami_benchmark/.venv/bin/python experiments/ami_benchmark/compare_providers.py` under Linux/WSL. It makes no provider/model calls and normally requires all 35 new completed runs plus seven retained predictions. `--allow-incomplete` explicitly permits declared incomplete Qwen receipts, reports only completed per-case values, and withholds Qwen aggregate scores. It does not satisfy the outstanding inference requirement.", "",
    ]
    for row in rows:
        if row["missing_cases"]:
            lines += [f"**Outstanding:** {row['provider']} / {row['arm']}: {', '.join(row['missing_cases'])}. See the provider execution report for the preserved failure and transport evidence; no full comparison completion is claimed.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Compare recorded AMI provider outputs without new inference")
    parser.add_argument("--allow-incomplete", action="store_true")
    args = parser.parse_args()
    comparison = compare(allow_incomplete=args.allow_incomplete)
    (ROOT / "provider_comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    (ROOT / "provider_comparison.md").write_text(render_report(comparison), encoding="utf-8")
    print(f"status={comparison['status']} new_completed_case_runs={comparison['new_completed_case_runs']}/35 reused_case_runs=7 cases=7 provider_arms=6")


if __name__ == "__main__":
    main()
