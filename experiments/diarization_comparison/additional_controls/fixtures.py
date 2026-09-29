from hashlib import sha256
import json
from pathlib import Path
import subprocess
import wave

ROOT = Path(__file__).resolve().parent
COMPARISON = ROOT.parent
SONIOX = COMPARISON.parent / "soniox_diarization"
RATE = 16000
REFERENCES = {"repeated": "result.json", "distinct": "result_distinct.json"}


def prepare() -> dict:
    original = json.loads((SONIOX / "fixture.json").read_text(encoding="utf-8"))
    speakers = {clip["utt_id"]: clip["speaker"] for clip in original["clips"]}
    decoded = {}
    cases = {}
    audio_dir = ROOT / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for name, reference_name in REFERENCES.items():
        reference_path = COMPARISON / "qwen_validation" / reference_name
        reference = json.loads(reference_path.read_text(encoding="utf-8"))["input"]
        pcm = bytearray()
        turns = []
        for index, item in enumerate(reference["intervals"]):
            clip = item["source_clip"]
            if clip not in decoded:
                decoded[clip] = subprocess.run(
                    ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(SONIOX / "clips" / clip),
                     "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
                    capture_output=True, check=True,
                ).stdout
            chunk = decoded[clip]
            start = len(pcm) / (RATE * 2)
            pcm.extend(chunk)
            end = len(pcm) / (RATE * 2)
            if (start, end, len(chunk), sha256(chunk).hexdigest()) != (
                item["start_s"], item["end_s"], item["copy_bytes"], item["copy_sha256"]
            ):
                raise ValueError(f"Qwen reference interval differs: {name}/{index}")
            turns.append({"utt_id": f"{index + 1}:{clip}", "source_clip": clip,
                          "label": item["label"], "speaker": speakers[clip],
                          "start_s": start, "end_s": end})
            pcm.extend(bytes(RATE))
        digest = sha256(pcm).hexdigest()
        if digest != reference["pcm_sha256"] or len(pcm) != reference["pcm_bytes"]:
            raise ValueError(f"Qwen reference waveform differs: {name}")
        with wave.open(str(audio_dir / f"{name}.wav"), "wb") as output:
            output.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
            output.writeframes(pcm)
        cases[name] = {"source_sha256": digest, "pcm_bytes": len(pcm),
                       "duration_s": len(pcm) / (RATE * 2), "turns": turns,
                       "audio": f"audio/{name}.wav",
                       "qwen_reference": f"../qwen_validation/{reference_name}"}
    manifest = {"sample_rate_hz": RATE, "sample_width_bytes": 2, "channels": 1,
                "silence_after_every_clip_s": 0.5, "cases": cases}
    (ROOT / "fixtures.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    print(json.dumps({name: {key: item[key] for key in ("source_sha256", "duration_s", "pcm_bytes")}
                      for name, item in prepare()["cases"].items()}))
