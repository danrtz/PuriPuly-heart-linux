from hashlib import sha256
import json
from pathlib import Path
import subprocess
import wave

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[1] / "soniox_diarization"
RATE = 16000
EXPECTED_SHA256 = "2eb1ab143c2a7dbaa7448c31b44dd8c517b85042e769f2da5d2ddaec14028762"


def main() -> None:
    manifest = json.loads((SOURCE / "fixture.json").read_text(encoding="utf-8"))
    audio = bytearray()
    silence = bytes(round(manifest["silence_between_clips_s"] * RATE) * 2)
    for clip in manifest["clips"]:
        path = SOURCE / "clips" / clip["utt_id"]
        decoded = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(RATE), "-f", "s16le", "pipe:1"],
            check=True,
            capture_output=True,
        ).stdout
        audio.extend(decoded)
        audio.extend(silence)
    digest = sha256(audio).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f"Original audio SHA-256 mismatch: {digest}")
    with wave.open(str(ROOT / "fixture.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(RATE)
        output.writeframes(audio)
    print(f"fixture_pcm_sha256={digest} sample_rate={RATE} samples={len(audio) // 2} duration_s={len(audio) / (2 * RATE):.3f}", flush=True)


if __name__ == "__main__":
    main()
