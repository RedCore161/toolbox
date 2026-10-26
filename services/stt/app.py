"""Offline speech-to-text over HTTP using Vosk."""

import json
import os
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from vosk import KaldiRecognizer, Model, SetLogLevel

MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))
DEFAULT_LANGUAGE = os.environ.get("DEFAULT_LANGUAGE", "de")
SAMPLE_RATE = 16000
CHUNK_BYTES = 8000

SetLogLevel(-1)
app = FastAPI(title="toolbox-stt")


def available_languages() -> list[str]:
    return sorted(p.name for p in MODELS_DIR.iterdir() if p.is_dir())


@lru_cache(maxsize=None)
def load_model(language: str) -> Model:
    return Model(str(MODELS_DIR / language))


@app.on_event("startup")
def warm_up() -> None:
    if DEFAULT_LANGUAGE in available_languages():
        load_model(DEFAULT_LANGUAGE)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "languages": available_languages(), "default": DEFAULT_LANGUAGE}


@app.post("/transcribe")
def transcribe(audio: UploadFile = File(...), language: str = Form(DEFAULT_LANGUAGE)) -> dict:
    if language not in available_languages():
        raise HTTPException(400, f"language {language!r} not installed; have {available_languages()}")

    with tempfile.NamedTemporaryFile(suffix=Path(audio.filename or "").suffix) as src:
        src.write(audio.file.read())
        src.flush()
        # ffmpeg normalises any input format to 16 kHz mono PCM, which is what Vosk expects.
        ffmpeg = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", src.name,
             "-ar", str(SAMPLE_RATE), "-ac", "1", "-f", "s16le", "-"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        recognizer = KaldiRecognizer(load_model(language), SAMPLE_RATE)
        recognizer.SetWords(True)

        segments = []
        while chunk := ffmpeg.stdout.read(CHUNK_BYTES):
            if recognizer.AcceptWaveform(chunk):
                segments.append(json.loads(recognizer.Result()))
        segments.append(json.loads(recognizer.FinalResult()))
        if ffmpeg.wait() != 0:
            raise HTTPException(400, f"could not decode audio: {ffmpeg.stderr.read().decode().strip()}")

    segments = [s for s in segments if s.get("text")]
    words = [w for s in segments for w in s.get("result", [])]
    return {
        "language": language,
        "text": " ".join(s["text"] for s in segments),
        "words": words,
        "duration_s": words[-1]["end"] if words else 0.0,
    }
