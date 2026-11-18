"""Synthesize a prepared Mandarin walkthrough from the ECS model environment."""
import argparse
import base64
import io
import json
import os
import time
import wave
from pathlib import Path

from services.api import models

MODEL = "gemini-3.8-flash-tts"
VOICE = "Charon"


def configure_limits():
    projects = {project for project, _ in models._choose(MODEL)}
    if not projects:
        raise SystemExit("TTS has no configured project")
    limits = json.loads(os.getenv("RT_MODEL_PROJECT_LIMITS", "{}"))
    prior = limits.get(MODEL, [3, 50000, 10])
    limits[MODEL] = [min(3, prior[0]), prior[1], min(10, prior[2])]
    caps = json.loads(os.getenv("RT_MODEL_DAILY_LIMITS", "{}"))
    caps[MODEL] = min(caps.get(MODEL, 20), 10 * len(projects))
    os.environ["RT_MODEL_PROJECT_LIMITS"] = json.dumps(limits)
    os.environ["RT_MODEL_DAILY_LIMITS"] = json.dumps(caps)


def audio_bytes(candidate):
    for part in candidate.get("content", {}).get("parts", []):
        if inline := part.get("inlineData"):
            raw = base64.b64decode(inline["data"], validate=True)
            if raw.startswith(b"RIFF"):
                with wave.open(io.BytesIO(raw), "rb") as source:
                    if (source.getnchannels(), source.getsampwidth(), source.getframerate()) != (1, 2, 24000):
                        raise ValueError("Unexpected audio parameters")
                    return source.readframes(source.getnframes())
            if inline["mimeType"].lower().startswith("audio/l16") and len(raw) % 2 == 0:
                return raw
    raise ValueError("No audio returned")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    lines = [line for scene in json.loads(args.script.read_text()) for line in scene["lines"]]
    configure_limits()
    args.output.mkdir(mode=0o700, exist_ok=True)
    receipts = args.output / "attempts.jsonl"
    if receipts.exists():
        raise SystemExit("Attempt ledger already exists; review it before any rerun")
    with receipts.open("x", buffering=1) as log:
        for start in range(0, len(lines), 5):
            group = lines[start:start + 5]
            prompt = "请以自然、清晰的普通话朗读下列文本。\n\n" + "\n".join(group)
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}},
                },
            }
            meta = {"line": start, "count": len(group), "model": MODEL, "day": models.quota_day()}
            print(json.dumps({**meta, "status": "pending"}), file=log)
            before = time.monotonic()
            try:
                result, _ = models.request(MODEL, "generateContent", payload, None, len(prompt.encode()))
                candidate = result["candidates"][0]
                meta["quota_id"] = result["_quota_id"]
                meta["finish"] = candidate.get("finishReason")
                if meta["finish"] != "STOP":
                    raise ValueError("Incomplete narration")
                data = audio_bytes(candidate)
                seconds = len(data) / 48000
                if not 2 <= seconds <= 60:
                    raise ValueError("Narration duration outside expected range")
                target = args.output / f"line-{start:02d}.wav"
                with wave.open(str(target), "wb") as stream:
                    stream.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                    stream.writeframes(data)
                meta.update(status="ok", seconds=round(seconds, 3))
            except models.SentRequestError as exc:
                meta.update(status=exc.outcome, http_status=exc.http_status, quota_id=exc.quota_id)
            except models.QuotaRefusal as exc:
                meta.update(status="not_sent", reason=exc.code)
            except (ValueError, KeyError, IndexError, wave.Error) as exc:
                meta.update(status="invalid_audio", error=type(exc).__name__)
            meta["elapsed"] = round(time.monotonic() - before, 2)
            print(json.dumps(meta), file=log)
            print(json.dumps(meta), flush=True)


if __name__ == "__main__":
    main()
