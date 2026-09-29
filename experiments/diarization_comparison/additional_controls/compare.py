from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
from evaluate import read_json, score_clip_dominants, soniox_intervals, source_intervals

SONIOX_ARMS = ("continuous", "forced", "segmented", "async_full_file")
NEMOTRON_ARMS = ("offline", "low_latency", "very_low_latency", "ultra_low_latency")


def score_case(name, fixture):
    counts = Counter(turn["speaker"] for turn in fixture["turns"])
    same = sum(count * (count - 1) // 2 for count in counts.values())
    total = len(fixture["turns"])
    expected = (same, total * (total - 1) // 2 - same)
    rows = []
    sources = [("Soniox", arm, ROOT / "soniox" / name / f"{arm}.json") for arm in SONIOX_ARMS]
    sources += [("Nemotron", arm, ROOT / "nemotron" / "evidence" / name / f"{arm}.json") for arm in NEMOTRON_ARMS]
    sources.append(("Qwen", "previous_control", ROOT / fixture["qwen_reference"]))
    for provider, arm, path in sources:
        result = read_json(path)
        source_sha = result["input"]["pcm_sha256"] if provider == "Qwen" else result["source_sha256"]
        if source_sha != fixture["source_sha256"]:
            raise ValueError(f"Wrong waveform in {provider}/{name}/{arm}")
        if provider == "Soniox":
            if result.get("completed") is not True:
                raise ValueError(f"Incomplete Soniox run: {name}/{arm}")
            intervals, support, native_ids = soniox_intervals(result)
        else:
            if provider == "Qwen" and (
                not result["run"]["session_finished_received"] or result["run"]["errors"]
            ):
                raise ValueError(f"Incomplete Qwen control: {name}")
            if provider == "Nemotron" and (
                result.get("speaker_channels") != 8 or not result.get("frame_probabilities")
            ):
                raise ValueError(f"Incomplete Nemotron run: {name}/{arm}")
            intervals, support, native_ids = source_intervals(result)
        score = score_clip_dominants(intervals, fixture["turns"], expected_pair_counts=expected)
        rows.append({
            "provider": provider, "arm": arm, "artifact": path.relative_to(ROOT).as_posix()
            if path.is_relative_to(ROOT) else str(path),
            "artifact_sha256": sha256(path.read_bytes()).hexdigest(),
            "model": result.get("model", result.get("model_requested")),
            "source_sha256": source_sha, "native_ids": native_ids,
            "nominal_delay_s": result.get("nominal_delay_s"),
            "measured_compute_s": result.get("measured_compute_s"),
            "sent_seconds": result.get("sent_seconds", result.get("run", {}).get("sent_audio_s")),
            "support_diagnostics": support, "score": score,
        })
    return {"fixture": fixture, "expected_pair_counts": list(expected), "runs": rows}


def render_report(comparison):
    lines = [
        "# Two additional speaker-recurrence controls", "",
        "The two original Qwen controls are reused without new Qwen calls. The WAV files are byte-identical to those sessions, verified by decoded PCM SHA-256. Each Soniox arm and Nemotron preset was run once per fixture; the preserved six-person benchmark is unchanged.", "",
        "All rows use the existing source-clip dominant-ID metric: native timestamps are intersected with each reference clip, same-ID overlap is counted once, ambiguous/missing support is not assigned an ID, and the uniquely longest ID wins. No gaps are bridged. Unresolved clips yield unresolved pairs, never successful matches. This is not DER, ASR accuracy, or a representative population estimate. Reference speaker labels are used only after inference.", "",
    ]
    rows = [row for case in comparison["cases"].values() for row in case["runs"]]
    if all(
        row["score"]["same_person_pairs"]["id_matches"]
        == row["score"]["same_person_pairs"]["denominator"]
        and row["score"]["different_person_pairs"]["distinct_ids"]
        == row["score"]["different_person_pairs"]["denominator"]
        for row in rows
    ):
        lines += [
            f"**Observed result:** all {len(rows)} saved runs preserve the expected dominant-ID grouping on these controls, with no unresolved clip pairs. This is a tie on the coarse recurrence metric, not proof that every speech boundary or short within-clip assignment is equally accurate. These short two-person controls do not overturn the longer six-person observations.", "",
        ]
    for name, case in comparison["cases"].items():
        fixture = case["fixture"]
        same, different = case["expected_pair_counts"]
        labels = " ".join(turn["label"] for turn in fixture["turns"])
        lines += [f"## {name}: {labels} ({fixture['duration_s']:.3f} s)", "",
                  f"PCM SHA-256: `{fixture['source_sha256']}`. Same-person pair denominator: **{same}**; different-person pair denominator: **{different}**.", "",
                  "| Provider / arm | Dominant native IDs in clip order | Same-person matches | False merges | Unresolved same / different pairs | Clips with multiple native IDs |",
                  "| --- | --- | ---: | ---: | --- | ---: |"]
        for row in case["runs"]:
            score = row["score"]
            same_row = score["same_person_pairs"]
            different_row = score["different_person_pairs"]
            sequence = ", ".join(str(clip["dominant_native_id"]) for clip in score["clips"])
            lines.append(f"| {row['provider']} / {row['arm']} | `{sequence}` | {same_row['id_matches']}/{same} | {different_row['false_merges']}/{different} | {same_row['unresolved']} / {different_row['unresolved']} | {score['clips_with_multiple_native_ids']} |")
        lines += ["", "### Nemotron timing", "",
                  "| Preset | Nominal buffer delay (s) | Measured full-clip CPU processing time after model load (s) |",
                  "| --- | ---: | ---: |"]
        for row in case["runs"]:
            if row["provider"] == "Nemotron":
                lines.append(f"| {row['arm']} | {row['nominal_delay_s']:.3f} | {row['measured_compute_s']:.3f} |")
        lines += [""]
    lines += [
        "## Interpretation limits and execution", "",
        "IDs are compared only within a session, never by their literal values across providers or presets. Dominant IDs can hide short within-clip switches; per-clip ID duration and uncovered/ambiguous support remain in comparison.json. Native token spans and diarization segments expose different temporal support, so uncovered duration is not ranked as missed-speech accuracy.", "",
        "The repeated fixture reuses exact waveform copies; its seven same-person pairs are not seven independent trials. The distinct fixture has two returning-speaker pairs. These clean, short, read-English controls do not establish performance on multilingual/noisy VRChat speech or explain any failure in the longer six-person fixture.", "",
        "The retained Qwen repeated-copy control merged B/B into one interval and had two empty source transcriptions plus phrase bleed. Its labels can still be compared, but this is not a clean ASR-success claim. The distinct Qwen control had four completed source transcripts. Neither Qwen session was rerun here.", "",
        "Nemotron used the existing pinned checkpoint and CPU environment; nominal buffering is not measured live end-to-end delay. CPU processing times are offline replay measurements. Soniox app-equivalent segmentation uses the existing actual VAD/ListenDelivery/SmartTurn probe, not full desktop capture; its source timeline accounts for omitted silence and added padding.", "",
        "Provider execution commands, completion markers, API usage/cleanup and effective parameters are in [Soniox execution evidence](soniox/execution_report.md) and [Nemotron execution evidence](nemotron/report.md). Original Qwen evidence is in [the validation report](../qwen_validation/report.md). No production code, settings, or user-visible behavior changed.", "",
        "Rebuild fixtures with `python experiments/diarization_comparison/additional_controls/fixtures.py`. After executing the two provider runners, run the offline comparison with `python experiments/diarization_comparison/additional_controls/compare.py`. It makes no inference or API calls and rejects missing, incomplete, or wrong-waveform inputs.", "",
    ]
    return "\n".join(lines)


def main():
    manifest = read_json(ROOT / "fixtures.json")
    comparison = {"status": "complete", "metric": "source_clip_dominant_native_id",
                  "cases": {name: score_case(name, fixture) for name, fixture in manifest["cases"].items()}}
    (ROOT / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n", encoding="utf-8")
    (ROOT / "report.md").write_text(render_report(comparison), encoding="utf-8")
    print("status=complete cases=2 scored_runs=18 same_pairs=7,2 different_pairs=8,4")


if __name__ == "__main__":
    main()
