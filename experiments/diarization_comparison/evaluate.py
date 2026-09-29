from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SONIOX = ROOT / "experiments" / "soniox_diarization"
OUTPUT_JSON = HERE / "comparison.json"
OUTPUT_REPORT = HERE / "report.md"
EXPECTED_PCM_SHA256 = "2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762"

# All Soniox arms retained from the original fixture use native token times and
# their saved provider-to-source timelines. The other models already expose
# source-timed speaker segments in their normalized artifacts.
INPUTS = (
    {"key": "soniox_continuous", "provider": "Soniox", "display": "Soniox realtime — continuous", "path": SONIOX / "continuous.json", "format": "soniox_tokens", "protocol": "Continuous realtime; one finalization at end"},
    {"key": "soniox_forced_6s", "provider": "Soniox", "display": "Soniox realtime — fixed 6-s control", "path": SONIOX / "forced.json", "format": "soniox_tokens", "protocol": "Fixed 6-s finalization control; not the app segmentation policy"},
    {"key": "soniox_app_segmented", "provider": "Soniox", "display": "Soniox realtime — app-segmentation equivalent", "path": SONIOX / "segmented.json", "format": "soniox_tokens", "protocol": "Saved app VAD/ListenDeliveryController source spans; not the full desktop capture pipeline"},
    {"key": "soniox_async", "provider": "Soniox", "display": "Soniox async full-file", "path": SONIOX / "async_full_file.json", "format": "soniox_tokens", "protocol": "Full-file asynchronous transcription"},
    {"key": "nemotron_offline", "provider": "NVIDIA NeMo", "display": "Nemotron-3-Diarization — offline-style", "path": HERE / "nemotron" / "offline.json", "format": "source_segments", "protocol": "Official offline-style configuration"},
    {"key": "nemotron_low_latency", "provider": "NVIDIA NeMo", "display": "Nemotron-3-Diarization — low latency", "path": HERE / "nemotron" / "low_latency.json", "format": "source_segments", "protocol": "Official low_latency streaming preset"},
    {"key": "nemotron_very_low_latency", "provider": "NVIDIA NeMo", "display": "Nemotron-3-Diarization — very low latency", "path": HERE / "nemotron" / "very_low_latency.json", "format": "source_segments", "protocol": "Official very_low_latency streaming preset"},
    {"key": "nemotron_ultra_low_latency", "provider": "NVIDIA NeMo", "display": "Nemotron-3-Diarization — ultra low latency", "path": HERE / "nemotron" / "ultra_low_latency.json", "format": "source_segments", "protocol": "Official ultra_low_latency streaming preset"},
    {"key": "qwen_realtime", "provider": "Qwen", "display": "Qwen 3.8 LiveTranslate realtime", "path": HERE / "qwen" / "result.json", "format": "source_segments", "protocol": "One saved realtime session"},
)


def read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object at {path}")
    return value


def is_old_metric_number(value: Any) -> bool:
    # Deliberately matches probe.py metrics(), which accepts Python bools as
    # numeric start/end values because bool subclasses int.
    return isinstance(value, (int, float))


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def source_hash(result: dict[str, Any]) -> str | None:
    direct = result.get("source_sha256")
    if isinstance(direct, str):
        return direct
    fixture = result.get("fixture")
    if isinstance(fixture, dict) and isinstance(fixture.get("source_sha256"), str):
        return fixture["source_sha256"]
    return None


def pair_denominators(anchors: list[dict[str, Any]]) -> tuple[int, int, dict[str, int]]:
    counts = Counter(anchor["true_speaker"] for anchor in anchors)
    same = sum(count * (count - 1) // 2 for count in counts.values())
    different = sum(
        counts[left] * counts[right]
        for index, left in enumerate(sorted(counts))
        for right in sorted(counts)[index + 1 :]
    )
    return same, different, dict(sorted(counts.items()))


def make_anchor_reference(continuous: dict[str, Any]) -> dict[str, Any]:
    """Freeze eligible source-time locations using the old Soniox metrics rules."""
    fixture = continuous.get("fixture")
    if not isinstance(fixture, dict):
        raise ValueError("Soniox continuous.json has no fixture provenance")
    turns = fixture.get("turns")
    timeline = continuous.get("timeline")
    tokens = continuous.get("tokens")
    if not isinstance(turns, list) or not isinstance(timeline, list) or not isinstance(tokens, list):
        raise ValueError("Soniox continuous.json is missing turns, timeline, or tokens")
    if source_hash(continuous) != EXPECTED_PCM_SHA256:
        raise ValueError("Soniox continuous.json is not the requested PCM fixture")

    anchors: list[dict[str, Any]] = []
    baseline_confusion: dict[str, Counter[str]] = defaultdict(Counter)
    skipped: Counter[str] = Counter()
    for token_index, token in enumerate(tokens):
        text = str(token.get("text") or "")
        if not any(character.isalnum() for character in text):
            skipped["nonlexical"] += 1
            continue
        start_ms, end_ms = token.get("start_ms"), token.get("end_ms")
        if not is_old_metric_number(start_ms) or not is_old_metric_number(end_ms):
            skipped["untimed"] += 1
            continue
        center_s = (start_ms + end_ms) / 2000
        mapped = [
            part
            for part in timeline
            if part["provider_start_s"] <= center_s < part["provider_end_s"]
        ]
        if len(mapped) != 1 or mapped[0].get("source_start_s") is None:
            skipped["outside_source"] += 1
            continue
        source_time_s = mapped[0]["source_start_s"] + center_s - mapped[0]["provider_start_s"]
        labeled = [turn for turn in turns if turn["start_s"] <= source_time_s < turn["end_s"]]
        if len(labeled) != 1:
            skipped["unlabeled_or_overlap"] += 1
            continue
        native_speaker = token.get("speaker")
        if native_speaker is None or isinstance(native_speaker, bool):
            skipped["missing_speaker"] += 1
            continue
        truth = str(labeled[0]["speaker"])
        baseline_confusion[truth][str(native_speaker)] += 1
        anchors.append(
            {
                "anchor_id": len(anchors),
                "source_token_index": token_index,
                "source_time_s": round(float(source_time_s), 9),
                "true_speaker": truth,
                "text": text,
            }
        )

    legacy = continuous.get("metrics")
    if not isinstance(legacy, dict):
        raise ValueError("Soniox continuous.json has no saved legacy metrics")
    same_pairs, different_pairs, truth_counts = pair_denominators(anchors)
    legacy_confusion = legacy.get("confusion", {})
    computed_confusion = {
        truth: dict(sorted(ids.items())) for truth, ids in sorted(baseline_confusion.items())
    }
    baseline_same_splits = sum(
        (count * count - sum(id_count * id_count for id_count in baseline_confusion[truth].values())) // 2
        for truth, count in truth_counts.items()
    )
    baseline_cross_merges = sum(
        left_count * right_count
        for left_index, left in enumerate(sorted(baseline_confusion))
        for right in sorted(baseline_confusion)[left_index + 1 :]
        for speaker_id, left_count in baseline_confusion[left].items()
        for right_id, right_count in baseline_confusion[right].items()
        if speaker_id == right_id
    )
    checks = {
        "anchor_count_matches_legacy": len(anchors) == legacy.get("identified_labeled_lexical_tokens"),
        "truth_confusion_matches_legacy": computed_confusion == legacy_confusion,
        "same_pair_denominator_matches_legacy": same_pairs == legacy.get("same_speaker_pairs"),
        "different_pair_denominator_matches_legacy": different_pairs == legacy.get("different_speaker_pairs"),
        "same_split_pairs_match_legacy": baseline_same_splits == legacy.get("same_speaker_split_pairs"),
        "different_merge_pairs_match_legacy": baseline_cross_merges == legacy.get("different_speaker_merge_pairs"),
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Frozen anchors do not reproduce old probe.py metrics: " + ", ".join(failed))

    return {
        "selection": "Midpoints of lexical final tokens from Soniox continuous.json, using the eligibility checks in soniox_diarization/probe.py metrics().",
        "reference_use": "Locations and original fixture speaker labels only; no reference labels or anchor list were sent to any inference run.",
        "eligibility": "Alphanumeric token text; numeric start_ms/end_ms; midpoint maps through exactly one timeline part to source audio; exactly one fixture truth interval contains it; native speaker ID is present and non-boolean, as in the old metrics().",
        "source_artifact": "experiments/soniox_diarization/continuous.json",
        "source_sha256": EXPECTED_PCM_SHA256,
        "anchor_count": len(anchors),
        "truth_anchor_counts": truth_counts,
        "same_reference_pair_denominator": same_pairs,
        "different_reference_pair_denominator": different_pairs,
        "legacy_validation": {"all_checks_passed": True, "checks": checks},
        "anchors": anchors,
        "excluded_by_old_eligibility": dict(sorted(skipped.items())),
    }


def segment_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    return str(value)


def soniox_intervals(result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    tokens = result.get("tokens")
    timeline = result.get("timeline")
    if not isinstance(tokens, list) or not isinstance(timeline, list):
        raise ValueError("Soniox artifact must contain native tokens and a provider/source timeline")
    intervals: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    stats: Counter[str] = Counter()
    invalid_timeline_parts = 0
    for token in tokens:
        speaker = segment_identifier(token.get("speaker"))
        if speaker is not None:
            observed_ids.add(speaker)
        else:
            stats["missing_id_records"] += 1
        start_ms, end_ms = token.get("start_ms"), token.get("end_ms")
        if not is_finite_number(start_ms) or not is_finite_number(end_ms) or end_ms <= start_ms:
            stats["invalid_timing_records"] += 1
            continue
        start_s, end_s = float(start_ms) / 1000, float(end_ms) / 1000
        stats["timed_records"] += 1
        if speaker is None:
            stats["missing_id_timed_records"] += 1
        mapped_pieces = 0
        for part in timeline:
            provider_start = part.get("provider_start_s")
            provider_end = part.get("provider_end_s")
            if not is_finite_number(provider_start) or not is_finite_number(provider_end) or provider_end <= provider_start:
                invalid_timeline_parts += 1
                continue
            piece_start = max(start_s, float(provider_start))
            piece_end = min(end_s, float(provider_end))
            if piece_end <= piece_start:
                continue
            source_start = part.get("source_start_s")
            if source_start is None:
                stats["unmapped_provider_pieces"] += 1
                continue
            if not is_finite_number(source_start):
                invalid_timeline_parts += 1
                continue
            source_piece_start = float(source_start) + piece_start - float(provider_start)
            source_piece_end = float(source_start) + piece_end - float(provider_start)
            intervals.append({"start_s": source_piece_start, "end_s": source_piece_end, "speaker": speaker})
            mapped_pieces += 1
        if mapped_pieces:
            stats["records_with_source_mapping"] += 1
        else:
            stats["records_without_source_mapping"] += 1
    stats["mapped_interval_pieces"] = len(intervals)
    stats["invalid_timeline_parts"] = invalid_timeline_parts
    return intervals, dict(sorted(stats.items())), sorted(observed_ids)


def source_intervals(result: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    segments = result.get("segments")
    if not isinstance(segments, list):
        raise ValueError("Normalized model artifact must contain source-time segments")
    intervals: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    stats: Counter[str] = Counter()
    for segment in segments:
        speaker = segment_identifier(segment.get("speaker"))
        if speaker is not None:
            observed_ids.add(speaker)
        else:
            stats["missing_id_records"] += 1
        start_s, end_s = segment.get("start_s"), segment.get("end_s")
        if not is_finite_number(start_s) or not is_finite_number(end_s) or end_s <= start_s:
            stats["invalid_timing_records"] += 1
            continue
        stats["timed_records"] += 1
        if speaker is None:
            stats["missing_id_timed_records"] += 1
        intervals.append({"start_s": float(start_s), "end_s": float(end_s), "speaker": speaker})
    stats["mapped_interval_pieces"] = len(intervals)
    return intervals, dict(sorted(stats.items())), sorted(observed_ids)

def score_clip_dominants(
    intervals: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    clips: list[dict[str, Any]] = []
    for turn in turns:
        start_s = float(turn["start_s"])
        end_s = float(turn["end_s"])
        if not math.isfinite(start_s) or not math.isfinite(end_s) or end_s <= start_s:
            raise ValueError(f"Invalid source clip interval: {turn.get('utt_id')!r}")

        clipped: list[tuple[float, float, str | None]] = []
        boundaries = {start_s, end_s}
        observed_ids: set[str] = set()
        for interval in intervals:
            speaker = segment_identifier(interval.get("speaker"))
            interval_start = interval.get("start_s")
            interval_end = interval.get("end_s")
            if not is_finite_number(interval_start) or not is_finite_number(interval_end):
                continue
            left = max(start_s, float(interval_start))
            right = min(end_s, float(interval_end))
            if right <= left:
                continue
            clipped.append((left, right, speaker))
            boundaries.update((left, right))
            if speaker is not None:
                observed_ids.add(speaker)

        by_id: Counter[str] = Counter()
        unknown_s = ambiguous_s = uncovered_s = 0.0
        points = sorted(boundaries)
        for left, right in zip(points, points[1:]):
            duration = right - left
            active_ids = {
                speaker
                for span_start, span_end, speaker in clipped
                if speaker is not None and span_start < right and span_end > left
            }
            active_unknown = any(
                speaker is None and span_start < right and span_end > left
                for span_start, span_end, speaker in clipped
            )
            if len(active_ids) > 1:
                ambiguous_s += duration
            elif active_unknown:
                unknown_s += duration
            elif active_ids:
                by_id[next(iter(active_ids))] += duration
            else:
                uncovered_s += duration

        unique_s = sum(by_id.values())
        clip_duration_s = end_s - start_s
        classified_s = unique_s + unknown_s + ambiguous_s + uncovered_s
        if not math.isclose(classified_s, clip_duration_s, rel_tol=0.0, abs_tol=1e-9):
            raise AssertionError(f"Clip support durations do not partition {turn.get('utt_id')!r}")

        dominant_id: str | None = None
        dominant_tie = False
        if by_id:
            maximum = max(by_id.values())
            leaders = [
                speaker
                for speaker, duration in by_id.items()
                if math.isclose(duration, maximum, rel_tol=1e-12, abs_tol=1e-9)
            ]
            dominant_tie = len(leaders) > 1
            if not dominant_tie:
                dominant_id = leaders[0]

        clips.append(
            {
                "clip_id": turn["utt_id"],
                "reference_speaker": str(turn["speaker"]),
                "start_s": start_s,
                "end_s": end_s,
                "clip_duration_s": round(clip_duration_s, 6),
                "dominant_native_id": dominant_id,
                "dominant_tie": dominant_tie,
                "dominant_id_reason": (
                    "tied_unique_duration_maximum"
                    if dominant_tie
                    else "no_uniquely_labeled_duration"
                    if dominant_id is None
                    else None
                ),
                "unique_id_durations_s": {
                    speaker: round(duration, 6) for speaker, duration in sorted(by_id.items())
                },
                "observed_native_ids": sorted(observed_ids),
                "uniquely_labeled_s": round(unique_s, 6),
                "unknown_s": round(unknown_s, 6),
                "ambiguous_s": round(ambiguous_s, 6),
                "uncovered_s": round(uncovered_s, 6),
            }
        )

    same_person = Counter()
    different_person = Counter()
    same_total = different_total = 0
    for left_index, left in enumerate(clips):
        for right in clips[left_index + 1 :]:
            same_reference = left["reference_speaker"] == right["reference_speaker"]
            counts = same_person if same_reference else different_person
            if same_reference:
                same_total += 1
            else:
                different_total += 1
            left_id = left["dominant_native_id"]
            right_id = right["dominant_native_id"]
            if left_id is None or right_id is None:
                counts["unresolved"] += 1
            elif same_reference and left_id == right_id:
                counts["id_matches"] += 1
            elif same_reference:
                counts["id_splits"] += 1
            elif left_id == right_id:
                counts["false_merges"] += 1
            else:
                counts["distinct_ids"] += 1

    if same_total != 6 or different_total != 60:
        raise ValueError(
            "The clip recurrence probe requires twelve clips from six speakers "
            f"(got {same_total} same-person and {different_total} different-person pairs)"
        )
    return {
        "same_person_pairs": {
            "id_matches": same_person["id_matches"],
            "id_splits": same_person["id_splits"],
            "unresolved": same_person["unresolved"],
            "denominator": same_total,
        },
        "different_person_pairs": {
            "false_merges": different_person["false_merges"],
            "distinct_ids": different_person["distinct_ids"],
            "unresolved": different_person["unresolved"],
            "denominator": different_total,
        },
        "unresolved_clip_count": sum(clip["dominant_native_id"] is None for clip in clips),
        "clips_with_multiple_native_ids": sum(
            len(clip["observed_native_ids"]) > 1 for clip in clips
        ),
        "clips": clips,
    }




def classify_anchor(anchor: dict[str, Any], intervals: list[dict[str, Any]]) -> dict[str, Any]:
    at_s = anchor["source_time_s"]
    active = [interval for interval in intervals if interval["start_s"] <= at_s < interval["end_s"]]
    ids = sorted({interval["speaker"] for interval in active if interval["speaker"] is not None})
    missing_id_spans = sum(interval["speaker"] is None for interval in active)
    if len(ids) > 1:
        classification, speaker = "ambiguous", None
    elif len(ids) == 1:
        classification, speaker = "identified", ids[0]
    else:
        classification, speaker = "missing", None
    return {
        "anchor_id": anchor["anchor_id"],
        "classification": classification,
        "speaker": speaker,
        "active_speaker_ids": ids,
        "active_missing_id_spans": missing_id_spans,
        "active_span_count": len(active),
        "missing_reason": "no_active_span" if not active else "no_active_identified_id" if not ids else None,
    }


def score_model(
    anchors: list[dict[str, Any]],
    intervals: list[dict[str, Any]],
    interval_stats: dict[str, Any],
    observed_ids: list[str],
) -> dict[str, Any]:
    assignments = [classify_anchor(anchor, intervals) for anchor in anchors]
    coverage = Counter(row["classification"] for row in assignments)
    if sum(coverage.values()) != len(anchors):
        raise AssertionError("Every common anchor must receive exactly one coverage classification")

    truth_counts = Counter(anchor["true_speaker"] for anchor in anchors)
    same_total = sum(count * (count - 1) // 2 for count in truth_counts.values())
    different_total = sum(
        truth_counts[left] * truth_counts[right]
        for index, left in enumerate(sorted(truth_counts))
        for right in sorted(truth_counts)[index + 1 :]
    )
    pairs: dict[str, Counter[str]] = {
        "same_reference": Counter(),
        "different_reference": Counter(),
    }
    for left_index, left_anchor in enumerate(anchors):
        left_prediction = assignments[left_index]
        for right_index in range(left_index + 1, len(anchors)):
            right_anchor = anchors[right_index]
            if left_anchor["true_speaker"] == right_anchor["true_speaker"]:
                outcome_group = "same_reference"
                correct_outcome, error_outcome = "correct", "split"
            else:
                outcome_group = "different_reference"
                correct_outcome, error_outcome = "correct", "merge"
            right_prediction = assignments[right_index]
            if left_prediction["classification"] != "identified" or right_prediction["classification"] != "identified":
                pairs[outcome_group]["unresolved"] += 1
            elif left_prediction["speaker"] == right_prediction["speaker"]:
                if outcome_group == "same_reference":
                    pairs[outcome_group][correct_outcome] += 1
                else:
                    pairs[outcome_group][error_outcome] += 1
            elif outcome_group == "same_reference":
                pairs[outcome_group][error_outcome] += 1
            else:
                pairs[outcome_group][correct_outcome] += 1
    if pairs["same_reference"]["correct"] + pairs["same_reference"]["split"] + pairs["same_reference"]["unresolved"] != same_total:
        raise AssertionError("Same-reference pair outcomes do not cover the fixed denominator")
    if pairs["different_reference"]["correct"] + pairs["different_reference"]["merge"] + pairs["different_reference"]["unresolved"] != different_total:
        raise AssertionError("Different-reference pair outcomes do not cover the fixed denominator")

    confusion: dict[str, Any] = {}
    for truth in sorted(truth_counts):
        by_id = Counter()
        missing = ambiguous = active_missing_id = 0
        for anchor, prediction in zip(anchors, assignments):
            if anchor["true_speaker"] != truth:
                continue
            if prediction["classification"] == "identified":
                by_id[prediction["speaker"]] += 1
            elif prediction["classification"] == "missing":
                missing += 1
            else:
                ambiguous += 1
            if prediction["active_missing_id_spans"]:
                active_missing_id += 1
        confusion[truth] = {
            "anchor_count": truth_counts[truth],
            "identified_by_native_id": dict(sorted(by_id.items())),
            "missing": missing,
            "ambiguous": ambiguous,
            "anchors_with_active_missing_id_spans": active_missing_id,
        }

    def pair_row(group: str, denominator: int, error_name: str) -> dict[str, Any]:
        counts = pairs[group]
        return {
            "identified_same_id_pairs" if group == "same_reference" else "identified_distinct_id_pairs": counts["correct"],
            error_name: counts[error_name],
            "unresolved": counts["unresolved"],
            "denominator": denominator,
        }

    return {
        "coverage": {
            "anchors_total": len(anchors),
            "identified": coverage["identified"],
            "missing": coverage["missing"],
            "ambiguous": coverage["ambiguous"],
            "missing_no_active_span": sum(row["missing_reason"] == "no_active_span" for row in assignments),
            "missing_only_missing_id_active": sum(row["missing_reason"] == "no_active_identified_id" for row in assignments),
            "anchors_with_active_missing_id_spans": sum(row["active_missing_id_spans"] > 0 for row in assignments),
        },
        "same_reference_pairs": pair_row("same_reference", same_total, "split"),
        "different_reference_pairs": pair_row("different_reference", different_total, "merge"),
        "observed_native_speaker_ids": observed_ids,
        "per_true_speaker_confusion": confusion,
        "interval_input_counts": interval_stats,
        "anchor_assignments": assignments,
    }


def model_capacity(provider: str) -> dict[str, Any]:
    if provider == "Soniox":
        return {
            "advertised_max_speakers_per_session": 15,
            "capacity_source": "https://soniox.com/docs/stt/concepts/speaker-diarization",
            "interpretation": "Documented support ceiling; not a guarantee of discovering or separating that many voices.",
        }
    if provider == "NVIDIA NeMo":
        return {
            "configured_speaker_capacity": 8,
            "parameter_scale": "100M",
            "interpretation": "Official NVIDIA Nemotron-3-Diarization 8speaker100M model/configuration.",
        }
    return {
        "speaker_detection_supported": True,
        "advertised_max_speakers": None,
        "interpretation": "The saved Qwen model configuration enables speaker_detection; no fixed maximum is evidenced by this run artifact.",
    }


def timing_summary(result: dict[str, Any]) -> dict[str, Any]:
    timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
    nominal = result.get("nominal_latency_s", result.get("nominal_delay_s"))
    if nominal is None:
        nominal = timing.get("nominal_latency_s", timing.get("nominal_delay_s"))
    measured_runtime = result.get("measured_runtime_s", result.get("wall_clock_runtime_s"))
    if measured_runtime is None:
        measured_runtime = timing.get("measured_runtime_s", timing.get("wall_clock_runtime_s"))
    measured_compute = result.get("measured_compute_s")
    if measured_compute is None:
        measured_compute = timing.get("preprocess_inference_postprocess_compute_s", timing.get("measured_compute_s"))
    sent_audio = result.get("sent_seconds", result.get("audio_sent_s"))
    if sent_audio is None:
        sent_audio = timing.get("sent_audio_s", timing.get("provider_audio_s"))
    source_audio = result.get("source_audio") if isinstance(result.get("source_audio"), dict) else {}
    input_duration = result.get("duration_s", source_audio.get("duration_s"))
    return {
        "nominal_latency_s": nominal,
        "measured_wall_runtime_s": measured_runtime,
        "measured_compute_s": measured_compute,
        "input_duration_s": input_duration,
        "sent_audio_s": sent_audio,
        "raw_timing_metadata": timing,
        "runtime_note": "No live wall-clock timing is inferred from audio duration or compute time.",
    }


def evaluate_one(
    spec: dict[str, Any],
    anchors: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> dict[str, Any]:
    path: Path = spec["path"]
    if not path.is_file():
        raise FileNotFoundError(f"Required model artifact is not ready: {path.relative_to(ROOT)}")
    result = read_json(path)
    digest = source_hash(result)
    if digest != EXPECTED_PCM_SHA256:
        raise ValueError(f"Wrong or missing PCM SHA-256 in {path.relative_to(ROOT)}: {digest!r}")
    if spec["format"] == "soniox_tokens":
        intervals, interval_stats, observed_ids = soniox_intervals(result)
    else:
        intervals, interval_stats, observed_ids = source_intervals(result)
    capacity = model_capacity(spec["provider"])
    if spec["provider"] == "NVIDIA NeMo":
        capacity["output_probability_channels"] = result.get("speaker_channels")
    model_weights_sha256 = result.get("model_weights_sha256")
    speaker_channels = result.get("speaker_channels")
    decision_threshold = result.get("decision_threshold")
    strict_anchor = score_model(anchors, intervals, interval_stats, observed_ids)
    clip_dominants = score_clip_dominants(intervals, turns)
    model = result.get("model")
    return {
        "key": spec["key"],
        "provider": spec["provider"],
        "display": spec["display"],
        "artifact": path.relative_to(ROOT).as_posix(),
        "protocol": spec["protocol"],
        "model": model,
        "model_weights_sha256": model_weights_sha256,
        "arm": result.get("arm"),
        "model_revision": result.get("model_revision"),
        "effective_config": result.get("effective_config", result.get("config")),
        "speaker_channels": speaker_channels,
        "decision_threshold": decision_threshold,
        "source_sha256": digest,
        "model_capacity": capacity,
        "timing": timing_summary(result),
        "clip_dominant_id_comparison": clip_dominants,
        "strict_anchor_diagnostic_not_ranked": strict_anchor,
    }


def not_evaluated_run(spec: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    safe_errors = [
        {key: error[key] for key in ("type", "code", "message") if key in error}
        for error in errors
        if isinstance(error, dict)
    ]
    reasons = [error.get("message") or error.get("code") or error.get("type") for error in safe_errors]
    timing = timing_summary(result)
    raw_timing = result.get("timing") if isinstance(result.get("timing"), dict) else {}
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
    run = result.get("run") if isinstance(result.get("run"), dict) else {}
    coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
    digest = source_hash(result)
    capacity = model_capacity(spec["provider"])
    requested_config = result.get("requested_config") if isinstance(result.get("requested_config"), dict) else {}
    turn_detection = requested_config.get("turn_detection") if isinstance(requested_config.get("turn_detection"), dict) else {}
    capacity["speaker_detection_requested"] = turn_detection.get("type") == "speaker_detection"
    capacity["advertised_max_speakers"] = result.get("documented_max_speaker_count")
    capacity["capacity_evidence_note"] = result.get("documented_max_speaker_count_note")
    return {
        "key": spec["key"],
        "provider": spec["provider"],
        "display": spec["display"],
        "artifact": spec["path"].relative_to(ROOT).as_posix(),
        "status": result.get("evaluation_status", result.get("status", "unknown")),
        "model": result.get("model"),
        "model_capacity": capacity,
        "reason": "; ".join(str(reason) for reason in reasons) or "No completed model-output artifact was produced.",
        "errors": safe_errors,
        "source_sha256": digest,
        "source_sha256_matches_fixture": digest == EXPECTED_PCM_SHA256,
        "documented_model_latency_claim_s": raw_timing.get("documented_model_latency_claim_s"),
        "documented_model_latency_claim_note": raw_timing.get("documented_model_latency_claim_note"),
        "command": run.get("command"),
        "websocket_connection_attempted": run.get("websocket_connection_attempted"),
        "workspace_id_available": run.get("workspace_id_available"),
        "api_key_available": run.get("api_key_available"),
        "input_audio_processed": coverage.get("source_audio_processed"),
        "session_finished": coverage.get("session_finished"),
        "websocket_requests_attempted": usage.get("websocket_requests_attempted"),
        "websocket_sessions_opened": usage.get("websocket_sessions_opened"),
        "audio_bytes_sent": run.get("audio_bytes_sent", usage.get("submitted_audio_bytes")),
        "timing": timing,
    }


def render_report(comparison: dict[str, Any]) -> str:
    fixture = comparison["fixture"]
    anchors = comparison["anchor_reference"]
    rows = comparison["evaluations"]
    not_evaluated = comparison.get("not_evaluated", [])
    lines = [
        "# Native-speaker recurrence across twelve source clips",
        "",
        "## Scope and primary metric",
        "",
        f"This offline comparison reuses the **{fixture['duration_s']:.3f}-second** 16-kHz mono fixture (SHA-256 `{fixture['source_sha256']}`): twelve known source clips from six LibriSpeech test-clean speakers, each speaker represented by two clips. It analyzes saved normalized spans only; no reference information was sent to inference.",
        "",
        "For each source clip, normalized native spans are clipped to the known source interval and swept at their exact endpoints. Duration contributes to an ID only where exactly one distinct non-null native ID is active and no null-ID span overlaps. Overlapping spans with the same ID count once. A null-ID overlap with fewer than two known IDs is unknown; two or more distinct known IDs are ambiguous; time with no active span is uncovered support. The dominant ID is the ID with the greatest uniquely labeled duration. No unique duration or a tied maximum makes the clip unresolved. No gap bridging or smoothing is applied; zero-duration spans contribute no duration.",
        "",
        "The primary comparison is deliberately a small **12-clip dominant-ID recurrence probe**, not DER or missed-speech accuracy. It counts same-person clip-pair ID matches out of 6 and different-person false merges out of 60. A pair with either clip unresolved is unresolved, never correct. IDs are compared only within one model run; ID values across providers and runs have no shared namespace.",
        "",
        "| Run | Same-person ID matches / 6 (splits; unresolved) | Different-person false merges / 60 (distinct IDs; unresolved) | Unresolved clips | Clips with >1 native ID |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    if not_evaluated:
        lines.extend(
            [
                "",
                f"**Incomplete:** {len(not_evaluated)} requested run(s) had no completed normalized output and are not assigned a result.",
                "",
            ]
        )
    for row in rows:
        clip_score = row["clip_dominant_id_comparison"]
        same = clip_score["same_person_pairs"]
        different = clip_score["different_person_pairs"]
        lines.append(
            f"| {row['display']} | {same['id_matches']} / 6 (splits {same['id_splits']}; unresolved {same['unresolved']}) | {different['false_merges']} / 60 (distinct {different['distinct_ids']}; unresolved {different['unresolved']}) | {clip_score['unresolved_clip_count']} | {clip_score['clips_with_multiple_native_ids']} |"
        )
    lines.extend(
        [
            "",
            "### Qwen follow-up: persistence is possible",
            "",
            "The Qwen 0/6 row is retained as the observed result of the original six-person session, not a general inability to reuse speaker IDs. [Two subsequent controls](qwen_validation/report.md) used the same endpoint, model and configuration: identical-waveform A A B B A A (22.28 s) returned native IDs 1, 1, 2, 1, 1 over five bounded turns; different-utterance A1 B1 A2 B2 (14.08 s) returned 1, 2, 1, 2, correctly reusing both people's IDs.",
            "",
            "These controls disprove the always-incrementing counter and inherent cross-utterance-persistence explanations. The original six-person run was not repeated; its raw evidence was audited. Speaker count, duration, ordering and intervening context differ from the controls, so the cause of its 0/6 outcome remains unisolated. Do not infer general model accuracy, a speaker-capacity limit, or general unsuitability for persistent labels from that single result.",
            "",
            "### Per-clip dominant labels and duration support",
            "",
            "Unique-ID durations include only uniquely labeled time. Unknown, ambiguous, and uncovered seconds partition the remainder of each known clip; uncovered time is a support diagnostic, not a missed-speech score. `Observed IDs` exposes within-clip changes that a single dominant label can hide.",
            "",
            "| Run | Clip | Reference | Dominant ID | Unique ID seconds | Unique total (s) | Unknown (s) | Ambiguous (s) | Uncovered (s) | Observed IDs |",
            "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in rows:
        for clip in row["clip_dominant_id_comparison"]["clips"]:
            dominant = clip["dominant_native_id"]
            if dominant is None:
                reason = "tie" if clip["dominant_tie"] else "no unique label"
                dominant_text = f"unresolved ({reason})"
            else:
                dominant_text = f"`{dominant}`"
            id_durations = ", ".join(
                f"`{speaker}`: {duration:.3f}"
                for speaker, duration in clip["unique_id_durations_s"].items()
            ) or "none"
            observed_ids = ", ".join(f"`{speaker}`" for speaker in clip["observed_native_ids"]) or "none"
            lines.append(
                f"| {row['display']} | `{clip['clip_id']}` | {clip['reference_speaker']} | {dominant_text} | {id_durations} | {clip['uniquely_labeled_s']:.3f} | {clip['unknown_s']:.3f} | {clip['ambiguous_s']:.3f} | {clip['uncovered_s']:.3f} | {observed_ids} |"
            )

    lines.extend(
        [
            "",
            "## Secondary fixed-173-anchor diagnostic (not ranked)",
            "",
            f"The saved common anchors are the {anchors['anchor_count']} continuous-Soniox lexical-token midpoints, validated against the previous continuous-arm eligibility/confusion counts. This point-span analysis is retained for diagnostics only: exact token-interval coverage is not a comparable speaker-accuracy measure across token and segment outputs. In particular, the low-coverage forced/app-segmented Soniox pair outcomes below are not accuracy percentages. The raw assignments remain under `strict_anchor_diagnostic_not_ranked` in `comparison.json`.",
            "",
            "| Run | Identified / missing / ambiguous anchors | Same-reference ID matches / splits / unresolved | Different-reference distinct IDs / merges / unresolved |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in rows:
        diagnostic = row["strict_anchor_diagnostic_not_ranked"]
        coverage = diagnostic["coverage"]
        same = diagnostic["same_reference_pairs"]
        different = diagnostic["different_reference_pairs"]
        lines.append(
            f"| {row['display']} | {coverage['identified']} / {coverage['missing']} / {coverage['ambiguous']} of {coverage['anchors_total']} | {same['identified_same_id_pairs']} / {same['split']} / {same['unresolved']} | {different['identified_distinct_id_pairs']} / {different['merge']} / {different['unresolved']} |"
        )
    lines.extend(
        [
            "",
            "The Nemotron rows retain the 171/173 identified anchors and zero identified-pair splits/merges across presets; the continuous Soniox row covers its own 173-anchor locations. The other Soniox strict token-span rows are support diagnostics only. The previous Soniox own-token pair proxies (including their own eligible-token denominators) remain in `../soniox_diarization/report.md` and are a separate metric, not a column in the clip recurrence table.",
            "",
            "The earlier strict-span quality ranking was withdrawn: 107 of the 116 app-segmented anchor misses still had the baseline whole word in that source clip's transcript. Exact word-token interval support differs from utterance-level support; a hole at another run's token midpoint is not evidence of a wrong speaker.",
            "",
            "## Nemotron preset latency",
            "",
            "| Preset | Nominal input-buffer delay (s) | Measured full-clip CPU processing time after model load (s) |",
            "| --- | ---: | ---: |",
        ]
    )
    for row in rows:
        if row["provider"] != "NVIDIA NeMo":
            continue
        timing = row["timing"]
        nominal = timing["nominal_latency_s"]
        compute = timing["measured_compute_s"]
        lines.append(
            f"| {row['display']} | {f'{nominal:.3f}' if is_finite_number(nominal) else 'not recorded'} | {f'{compute:.3f}' if is_finite_number(compute) else 'not recorded'} |"
        )
    lines.extend(
        [
            "",
            "Nemotron nominal values are configured input-buffer delays, not measured live end-to-end latency. CPU processing time is measured wall-clock preprocessing, inference and segment conversion for the whole fixture, after model load, without realtime pacing. Soniox own-token proxies and Qwen session details remain in their respective experiment records. Qwen's primary clip result above uses its completed, hash-matched normalized native intervals.",
            "",
            "## Reproduction and limits",
            "",
            "The evaluator makes no inference/API calls. Clip-level support durations are not missed-speech or DER estimates: the models expose different native span granularities, and silence/uncovered time is reported rather than scored as an error. Dominant IDs intentionally hide within-clip switching; the observed-ID lists and `clips_with_multiple_native_ids` count expose that limitation.",
            "",
            "This is one clean read-English audiobook concatenation, not a representative benchmark of multilingual or noisy VRChat speech. No production code, settings, or user-visible behavior was changed.",
            "",
            "Qwen's [speaker_id contract](https://help.aliyun.com/en/model-studio/live-translator-server-events) identifies speakers when speaker_detection is enabled but does not explicitly guarantee persistent IDs for returning people across turns. The observed 0/6 recurrence result fails this application's persistent-person-label requirement on this fixture; it is not evidence of violating an explicit vendor stability guarantee.",
            "",
            "Run the offline comparison from the repository root:",
            "",
            "```powershell",
            f"{sys.executable.replace(chr(92), '/') } experiments/diarization_comparison/evaluate.py",
            "```",
            "",
            f"Observed evaluator result: phase `{comparison['phase']}`, {len(rows)} completed normalized model runs, {len(not_evaluated)} not evaluated, all scored artifacts matched the fixture PCM hash. The fixed-anchor denominator remains {anchors['anchor_count']}; its point assignments are retained only as a secondary diagnostic.",
            "",
        ]
    )
    return "\n".join(lines)


def build_comparison(anchors_only: bool) -> dict[str, Any]:
    continuous = read_json(SONIOX / "continuous.json")
    anchor_reference = make_anchor_reference(continuous)
    fixture = continuous["fixture"]
    duration_s = continuous.get("duration_s")
    comparison: dict[str, Any] = {
        "schema_version": 2,
        "primary_metric": {
            "name": "same-12-source-clip dominant native-ID recurrence",
            "same_person_pair_denominator": 6,
            "different_person_pair_denominator": 60,
            "unresolved_rule": "Any pair with an unresolved clip is unresolved, never correct.",
            "support_categories": [
                "uniquely_labeled",
                "unknown",
                "ambiguous",
                "uncovered",
            ],
            "duration_rule": "Only source-mapped positive-duration spans contribute; same-ID overlap is deduplicated; no temporal gap is bridged.",
        },
        "fixture": {
            "dataset": fixture.get("dataset"),
            "license": fixture.get("license"),
            "duration_s": duration_s,
            "sample_rate_hz": 16000,
            "channels": 1,
            "source_sha256": EXPECTED_PCM_SHA256,
            "truth_turns": fixture["turns"],
            "true_speaker_ids": sorted({str(turn["speaker"]) for turn in fixture["turns"]}),
            "soniox_app_segmented_sent_s": read_json(SONIOX / "segmented.json").get("sent_seconds"),
        },
        "anchor_reference": anchor_reference,
    }
    if anchors_only:
        comparison["phase"] = "frozen_anchor_reference_only; no model comparison rows included"
        return comparison
    evaluations = []
    not_evaluated = []
    for spec in INPUTS:
        if not spec["path"].is_file():
            raise FileNotFoundError(f"Required model artifact is not ready: {spec['path'].relative_to(ROOT)}")
        if spec["provider"] == "Qwen":
            qwen_result = read_json(spec["path"])
            qwen_complete = (
                qwen_result.get("status") == "completed"
                and qwen_result.get("evaluation_status") == "evaluated"
                and isinstance(qwen_result.get("segments"), list)
            )
            if not qwen_complete:
                not_evaluated.append(not_evaluated_run(spec, qwen_result))
                continue
        evaluations.append(evaluate_one(spec, anchor_reference["anchors"], fixture["turns"]))
    comparison["evaluations"] = evaluations
    comparison["not_evaluated"] = not_evaluated
    comparison["phase"] = "blocked_by_unavailable_model_run" if not_evaluated else "complete"
    return comparison


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline source-clip dominant-ID comparison")
    parser.add_argument("--anchors-only", action="store_true", help="Freeze and validate common anchors without writing comparison rows")
    args = parser.parse_args()
    comparison = build_comparison(args.anchors_only)
    OUTPUT_JSON.write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.anchors_only:
        print(
            f"phase=anchors_only anchors={comparison['anchor_reference']['anchor_count']} "
            f"same_pairs={comparison['anchor_reference']['same_reference_pair_denominator']} "
            f"different_pairs={comparison['anchor_reference']['different_reference_pair_denominator']} legacy_checks=passed",
            flush=True,
        )
        return
    OUTPUT_REPORT.write_text(render_report(comparison), encoding="utf-8")
    print(
        f"phase={comparison['phase']} scored_runs={len(comparison['evaluations'])} "
        f"not_evaluated={len(comparison['not_evaluated'])} "
        f"anchors={comparison['anchor_reference']['anchor_count']} "
        f"same_pairs={comparison['anchor_reference']['same_reference_pair_denominator']} "
        f"different_pairs={comparison['anchor_reference']['different_reference_pair_denominator']} "
        f"scored_hashes=matched",
        flush=True,
    )


if __name__ == "__main__":
    main()
