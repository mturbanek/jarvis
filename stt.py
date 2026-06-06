import threading
import numpy as np
from faster_whisper import WhisperModel
from config import WHISPER_MODEL

_model: "WhisperModel | None" = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        print(f"[STT] Loading Whisper '{WHISPER_MODEL}' model (first run only)...")
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
        print("[STT] Model ready.")
    return _model


def prewarm() -> None:
    """Load the Whisper model in the background so the first transcription is instant."""
    threading.Thread(target=_get_model, daemon=True, name="stt-prewarm").start()


def transcribe(audio: np.ndarray) -> str:
    model = _get_model()
    segments, _ = model.transcribe(audio, language="en", vad_filter=True)
    return " ".join(seg.text.strip() for seg in segments).strip()
