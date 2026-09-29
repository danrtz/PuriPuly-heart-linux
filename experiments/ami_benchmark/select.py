import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from fetch_references import MEETINGS, REVISION, ROOT

DURATIONS = {"low_overlap": 120, "rapid_turn_taking": 120, "overlap_heavy": 120, "long_return_gap": 180, "brief_interjections": 120, "long_context": 600}


def segments(meeting):
    rows = []
    for line in (ROOT / "references" / "source" / f"{meeting}.rttm").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        start, duration = float(parts[3]), float(parts[4])
        if duration <= 0:
            raise ValueError(f"Nonpositive reference segment: {line}")
        rows.append((start, start + duration, parts[7]))
    return sorted(rows)


def union_intervals(intervals):
    merged = []
    for a, b in sorted(intervals):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def features(rows, start, duration):
    end = start + duration
    clipped = [(max(a, start), min(b, end), speaker) for a, b, speaker in rows if a < end and b > start]
    by_speaker = defaultdict(list)
    for a, b, speaker in clipped:
        by_speaker[speaker].append((a, b))
    events = []
    for intervals in by_speaker.values():
        for a, b in union_intervals(intervals):
            events.extend(((a, 1), (b, -1)))
    events.sort()
    count = 0
    previous = start
    speech = overlap = 0.0
    for t, delta in events:
        span = t - previous
        speech += span * (count > 0)
        overlap += span * (count > 1)
        count += delta
        previous = t
    turns = []
    for speaker, intervals in by_speaker.items():
        a, b = intervals[0]
        for next_a, next_b in intervals[1:]:
            if next_a - b <= 0.6:
                b = max(b, next_b)
            else:
                turns.append((a, b, speaker))
                a, b = next_a, next_b
        turns.append((a, b, speaker))
    turns.sort()
    changes = sum(left[2] != right[2] for left, right in zip(turns, turns[1:]))
    short = sum(b - a <= 0.7 for a, b, _ in turns)
    returns = []
    for speaker in by_speaker:
        own = sorted((a, b) for a, b, s in turns if s == speaker)
        for (before_a, before_b), (after_a, after_b) in zip(own, own[1:]):
            gap = after_a - before_b
            if gap < 40 or before_a <= start + 1 or after_b >= end - 1 or before_b - before_a < 1 or after_b - after_a < 1:
                continue
            other = [(max(a, before_b), min(b, after_a), s) for a, b, s in clipped if s != speaker and a < after_a and b > before_b]
            other_seconds = sum(b - a for a, b in union_intervals((a, b) for a, b, _ in other))
            if other_seconds >= 20:
                returns.append({"speaker": speaker, "before_s": round(before_a - start, 3), "before_end_s": round(before_b - start, 3), "after_s": round(after_a - start, 3), "after_end_s": round(after_b - start, 3), "gap_s": round(gap, 3), "intervening_other_speaker_seconds": round(other_seconds, 3), "intervening_speakers": len({s for _, _, s in other})})
    longest = max(returns, key=lambda item: item["gap_s"], default=None)
    return {"active_speakers": len(by_speaker), "speech_s": round(speech, 3), "overlap_s": round(overlap, 3), "overlap_fraction_of_speech": round(overlap / speech, 4) if speech else 0, "turns": len(turns), "speaker_changes": changes, "short_turns_le_0_7_s": short, "qualified_return_gaps_ge_40_s": len(returns), "longest_return_gap_s": longest["gap_s"] if longest else 0, "return_event": longest}


def candidates():
    inventory = json.loads((ROOT / "references" / "source_inventory.json").read_text(encoding="utf-8"))
    if inventory["repository_revision"] != REVISION or {entry["meeting"] for entry in inventory["files"]} != set(MEETINGS):
        raise ValueError("Reference inventory does not match pinned AMI test set")
    result = {kind: [] for kind in DURATIONS}
    all_stats = []
    for entry in inventory["files"]:
        meeting = entry["meeting"]
        path = ROOT / "references" / "source" / f"{meeting}.rttm"
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["reference_sha256"]:
            raise ValueError(f"Reference digest mismatch: {meeting}")
        rows = segments(meeting)
        end = max(b for _, b, _ in rows)
        all_stats.append({"meeting": meeting, "last_annotation_s": round(end, 3), "annotated_speakers": len({s for _, _, s in rows}), "segments": len(rows)})
        for kind, duration in DURATIONS.items():
            for start in range(0, int(end - duration), 10):
                stat = features(rows, start, duration)
                if stat["active_speakers"] < 3 or stat["speech_s"] < duration * 0.4:
                    continue
                if kind == "low_overlap" and stat["overlap_fraction_of_speech"] > 0.03:
                    continue
                if kind == "overlap_heavy" and stat["overlap_fraction_of_speech"] < 0.12:
                    continue
                if kind == "long_return_gap" and stat["longest_return_gap_s"] < 60:
                    continue
                if kind == "brief_interjections" and stat["short_turns_le_0_7_s"] < 8:
                    continue
                stat.update(meeting=meeting, start_s=start, duration_s=duration)
                result[kind].append(stat)
    return result, all_stats


def main():
    pool, source_stats = candidates()
    criteria = {"low_overlap": lambda s: (s["overlap_fraction_of_speech"], -s["speech_s"]), "rapid_turn_taking": lambda s: (-s["speaker_changes"], -s["active_speakers"]), "overlap_heavy": lambda s: (-s["overlap_fraction_of_speech"], -s["overlap_s"]), "long_return_gap": lambda s: (-s["longest_return_gap_s"], -s["qualified_return_gaps_ge_40_s"]), "brief_interjections": lambda s: (-s["short_turns_le_0_7_s"], -s["speaker_changes"]), "long_context": lambda s: (-s["speaker_changes"], -s["active_speakers"])}
    for kind in pool:
        pool[kind].sort(key=lambda s: (*criteria[kind](s), s["meeting"], s["start_s"]))
        print(kind, "candidates", len(pool[kind]), "top", pool[kind][:3], flush=True)
    selected = []
    for kind in DURATIONS:
        possible = (s for s in pool[kind] if s["meeting"] not in {case["meeting"] for case in selected} and all(s["meeting"] != other["meeting"] or s["start_s"] + s["duration_s"] <= other["start_s"] or other["start_s"] + other["duration_s"] <= s["start_s"] for other in selected))
        choice = next(possible, None)
        if choice is None:
            raise ValueError(f"No distinct-meeting valid candidate for {kind}")
        selected.append({"id": kind, **choice})
    if not any(s["active_speakers"] == 3 for s in selected) or not any(s["active_speakers"] == 4 for s in selected):
        raise ValueError(f"Need both three- and four-speaker cases: {[(s['id'], s['active_speakers']) for s in selected]}")
    (ROOT / "selection.json").write_text(json.dumps({"method": "10-second grid, six distinct meetings, >=40% annotated speech and >=3 speakers, scenario-specific constraints and lexicographic feature ranks; turns join same-speaker annotation intervals separated by <=0.6 s for selection only", "source_stats": source_stats, "candidate_counts": {k: len(v) for k, v in pool.items()}, "cases": selected}, indent=2) + "\n", encoding="utf-8")
    print("SELECTED", selected, flush=True)


if __name__ == "__main__":
    main()
