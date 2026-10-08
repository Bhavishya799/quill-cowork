"""Local audio: streaming STT via faster-whisper, TTS via pyttsx3.

Design:
  - Lazy, thread-safe model load, cached for process lifetime.
  - Accepts int16 mono PCM at any rate; auto-resamples to 16 kHz.
  - Provides one-shot transcribe() and a StreamSession for live partials.
  - No network. Model downloads once on first use, then runs offline.

Env:
  WHISPER_MODEL   tiny | base | small | medium | large-v3   (default: base)
  WHISPER_DEVICE  auto | cpu | cuda                         (default: auto)
  WHISPER_COMPUTE int8 | float16 | float32                  (default: auto)
  TTS_RATE        speaking rate for pyttsx3                 (default: 180)
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

_WHISPER_LOCK = threading.Lock()
_WHISPER_MODEL = None
_WHISPER_ERR: Optional[str] = None
_WHISPER_SEM = asyncio.Semaphore(1)
_TTS_LOCK = threading.Lock()


def _model_name() -> str:
    return (os.getenv("WHISPER_MODEL", "base") or "base").strip().lower()


def _device() -> str:
    want = (os.getenv("WHISPER_DEVICE", "auto") or "auto").strip().lower()
    if want in ("cpu", "cuda"):
        return want
    try:
        import torch  # type: ignore
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _compute(device: str) -> str:
    want = (os.getenv("WHISPER_COMPUTE", "") or "").strip()
    if want:
        return want
    return "float16" if device == "cuda" else "int8"


def load_model():
    global _WHISPER_MODEL, _WHISPER_ERR
    if _WHISPER_MODEL is not None:
        return _WHISPER_MODEL
    with _WHISPER_LOCK:
        if _WHISPER_MODEL is not None:
            return _WHISPER_MODEL
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            _WHISPER_ERR = ("faster-whisper not installed "
                            "(pip install faster-whisper)")
            raise RuntimeError(_WHISPER_ERR) from e
        device = _device()
        compute = _compute(device)
        try:
            _WHISPER_MODEL = WhisperModel(
                _model_name(), device=device, compute_type=compute
            )
            _WHISPER_ERR = None
        except Exception as e:
            _WHISPER_ERR = f"failed to load whisper model: {type(e).__name__}: {e}"
            raise
        return _WHISPER_MODEL


def is_ready() -> bool:
    try:
        load_model()
        return True
    except Exception:
        return False


def _resample_to_16k(pcm: np.ndarray, src_rate: int) -> np.ndarray:
    if src_rate == 16000 or pcm is None or len(pcm) == 0:
        return pcm
    n_out = int(round(len(pcm) * 16000 / float(src_rate)))
    if n_out <= 0:
        return pcm[:0]
    src_idx = np.linspace(0.0, len(pcm) - 1.0, len(pcm), dtype=np.float32)
    dst_idx = np.linspace(0.0, len(pcm) - 1.0, n_out, dtype=np.float32)
    out = np.interp(dst_idx, src_idx, pcm.astype(np.float32))
    return out.astype(np.int16)


@dataclass
class Transcript:
    text: str = ""
    language: str = ""
    duration: float = 0.0
    segments: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "duration": round(self.duration, 2),
            "segments": self.segments,
        }


def transcribe_pcm(pcm_i16: np.ndarray, sample_rate: int = 16000,
                   language: Optional[str] = None) -> Transcript:
    if pcm_i16 is None or len(pcm_i16) == 0:
        return Transcript()
    pcm = _resample_to_16k(pcm_i16, sample_rate)
    audio = pcm.astype(np.float32) / 32768.0
    model = load_model()
    segs, info = model.transcribe(
        audio,
        beam_size=1,
        vad_filter=True,
        language=language or None,
        condition_on_previous_text=False,
    )
    out = Transcript()
    out.language = getattr(info, "language", "") or ""
    out.duration = float(getattr(info, "duration", 0.0) or 0.0)
    parts = []
    for s in segs:
        t = (s.text or "").strip()
        if t:
            parts.append(t)
        out.segments.append({
            "start": round(float(s.start), 2),
            "end": round(float(s.end), 2),
            "text": t,
        })
    out.text = " ".join(parts).strip()
    return out


async def transcribe_pcm_async(pcm_i16: np.ndarray,
                               sample_rate: int = 16000) -> Transcript:
    async with _WHISPER_SEM:
        return await asyncio.to_thread(transcribe_pcm, pcm_i16, sample_rate)


class StreamSession:
    """Accumulate PCM chunks; emit partials while the user speaks."""

    def __init__(self, sample_rate: int,
                 partial_interval: float = 1.2,
                 min_audio_for_partial: float = 0.8,
                 max_buffer_seconds: float = 45.0):
        self.sample_rate = int(sample_rate) if sample_rate > 0 else 16000
        self.partial_interval = partial_interval
        self.min_audio_for_partial = min_audio_for_partial
        self.max_buffer_seconds = max_buffer_seconds
        self._chunks: list = []
        self._total = 0
        self._last_partial_at = 0.0
        self._last_partial_text = ""

    def add(self, pcm_i16: np.ndarray) -> None:
        if pcm_i16 is None or len(pcm_i16) == 0:
            return
        self._chunks.append(pcm_i16)
        self._total += len(pcm_i16)
        cap = int(self.max_buffer_seconds * self.sample_rate)
        if self._total > cap:
            joined = self._joined()[self._total - cap:]
            self._chunks = [joined]
            self._total = len(joined)

    def _joined(self) -> np.ndarray:
        if not self._chunks:
            return np.zeros(0, dtype=np.int16)
        if len(self._chunks) == 1:
            return self._chunks[0]
        return np.concatenate(self._chunks)

    @property
    def duration(self) -> float:
        return self._total / float(self.sample_rate)

    def should_emit_partial(self) -> bool:
        now = time.monotonic()
        if self.duration < self.min_audio_for_partial:
            return False
        if now - self._last_partial_at < self.partial_interval:
            return False
        return True

    async def partial(self) -> str:
        pcm = self._joined()
        self._last_partial_at = time.monotonic()
        t = await transcribe_pcm_async(pcm, self.sample_rate)
        text = t.text.strip()
        if text:
            self._last_partial_text = text
        return text

    async def finalize(self) -> Transcript:
        pcm = self._joined()
        return await transcribe_pcm_async(pcm, self.sample_rate)


def synthesize_wav(text: str, rate: int = 180) -> bytes:
    if not text or not text.strip():
        return b""
    try:
        import pyttsx3
    except ImportError as e:
        raise RuntimeError("pyttsx3 not installed (pip install pyttsx3)") from e
    import tempfile
    with _TTS_LOCK:
        engine = pyttsx3.init()
        try:
            engine.setProperty("rate", rate)
        except Exception:
            pass
        import os as _os
        fd, tmp = tempfile.mkstemp(prefix="quill-tts-", suffix=".wav")
        _os.close(fd)
        try:
            engine.save_to_file(text, tmp)
            engine.runAndWait()
            with open(tmp, "rb") as f:
                return f.read()
        finally:
            try:
                _os.unlink(tmp)
            except Exception:
                pass
            try:
                engine.stop()
            except Exception:
                pass


async def synthesize(text: str, rate: int = 180) -> bytes:
    return await asyncio.to_thread(synthesize_wav, text, rate)


def status() -> dict:
    have = is_ready()
    return {
        "ready": have,
        "model": _model_name(),
        "device": _device(),
        "compute": _compute(_device()),
        "error": _WHISPER_ERR,
    }
