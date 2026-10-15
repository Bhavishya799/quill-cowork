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
    """Chunk-and-commit streaming session.

    Committed text lives outside the audio window. Each pass transcribes
    only the uncommitted window; stable segments are promoted and their
    audio dropped. A small overlap (default 0.8s) stays at the window
    start so Whisper has context and words aren't cut mid-syllable.
    The seam is deduped word-wise against committed text.
    """

    def __init__(self, sample_rate: int,
                 partial_interval: float = 1.2,
                 min_audio_for_partial: float = 0.8,
                 overlap_seconds: float = 0.8,
                 commit_after_seconds: float = 8.0):
        self.sample_rate = int(sample_rate) if sample_rate > 0 else 16000
        self.partial_interval = partial_interval
        self.min_audio_for_partial = min_audio_for_partial
        self.overlap_samples = int(overlap_seconds * self.sample_rate)
        self.commit_after_samples = int(commit_after_seconds * self.sample_rate)

        self.committed_text = ""
        self._active = np.zeros(0, dtype=np.int16)
        # Samples at the start of _active that are already committed
        # (the overlap region re-fed for context).
        self._overlap_in_active = 0
        self._last_partial_at = 0.0
        self._last_partial_text = ""
        self._debug = os.getenv("QUILL_AUDIO_DEBUG", "0") == "1"

    # --- input -------------------------------------------------------

    def add(self, pcm_i16: np.ndarray) -> None:
        if pcm_i16 is None or len(pcm_i16) == 0:
            return
        pcm_i16 = pcm_i16.astype(np.int16, copy=False)
        if self._active.size == 0:
            self._active = pcm_i16.copy()
        else:
            self._active = np.concatenate([self._active, pcm_i16])

    # --- state -------------------------------------------------------

    @property
    def duration(self) -> float:
        return len(self._active) / float(self.sample_rate)

    def should_emit_partial(self) -> bool:
        now = time.monotonic()
        if self.duration < self.min_audio_for_partial:
            return False
        if now - self._last_partial_at < self.partial_interval:
            return False
        return True

    # --- transcribe --------------------------------------------------

    async def partial(self) -> str:
        if len(self._active) == 0:
            return self.committed_text
        self._last_partial_at = time.monotonic()
        t = await transcribe_pcm_async(self._active, self.sample_rate)
        return self._compose(t)

    async def commit_if_ready(self) -> bool:
        """If the active window has grown past commit_after_seconds,
        transcribe it, promote the stable prefix to committed_text,
        drop that audio, keep overlap. Returns True if anything was
        committed."""
        if len(self._active) < self.commit_after_samples:
            return False

        t = await transcribe_pcm_async(self._active, self.sample_rate)
        if not t.segments:
            return False

        duration_samples = len(self._active)
        cutoff_samples = duration_samples - self.overlap_samples
        overlap_sec = self._overlap_in_active / float(self.sample_rate)

        commit_texts = []
        commit_until_samples = self._overlap_in_active

        for seg in t.segments:
            # Segments fully inside the already-committed overlap: skip.
            if seg.end <= overlap_sec:
                continue
            seg_end_samples = int(seg.end * self.sample_rate)
            # Segments that extend into the live edge: stop.
            if seg_end_samples > cutoff_samples:
                break
            text = (seg.text or "").strip()
            if text:
                commit_texts.append(text)
            commit_until_samples = seg_end_samples

        if not commit_texts:
            return False

        new_text = " ".join(commit_texts).strip()
        if not new_text:
            return False

        self.committed_text = (self.committed_text + " " + new_text).strip()

        # Drop committed audio, keep overlap at the front.
        drop_until = max(0, commit_until_samples - self.overlap_samples)
        self._active = self._active[drop_until:]
        self._overlap_in_active = commit_until_samples - drop_until
        self._last_partial_text = self.committed_text

        if self._debug:
            print(
                f"[audio] commit: +{len(new_text)} chars, "
                f"drop {drop_until} samples, "
                f"active now {len(self._active)} samples "
                f"({len(self._active) / self.sample_rate:.2f}s)",
                flush=True,
            )
        return True

    async def finalize(self) -> Transcript:
        if len(self._active) == 0:
            return Transcript(text=self.committed_text, duration=0.0)
        t = await transcribe_pcm_async(self._active, self.sample_rate)
        final_text = self._compose(t)
        return Transcript(
            text=final_text,
            language=t.language,
            duration=len(self._active) / float(self.sample_rate),
            segments=t.segments,
        )

    # --- internals ---------------------------------------------------

    def _compose(self, t: Transcript) -> str:
        """Committed text + the new portion of t, seam-deduped."""
        overlap_sec = self._overlap_in_active / float(self.sample_rate)
        new_parts = []
        for seg in t.segments:
            if seg.end <= overlap_sec:
                continue
            text = (seg.text or "").strip()
            if text:
                new_parts.append(text)

        raw_new = " ".join(new_parts).strip()
        if not raw_new:
            # Whisper returned no segments (or only overlap): fall back
            # to the whole text and dedupe against committed tail.
            raw_new = (t.text or "").strip()

        raw_new = _dedupe_tail_head(self.committed_text, raw_new)
        if not raw_new:
            return self.committed_text
        if not self.committed_text:
            return raw_new
        return (self.committed_text + " " + raw_new).strip()


def _dedupe_tail_head(committed: str, new_text: str,
                      max_words: int = 8) -> str:
    """If the tail of `committed` matches the head of `new_text`, drop
    the duplicate from `new_text`. Word-level, case-sensitive."""
    if not committed or not new_text:
        return new_text
    c_words = committed.split()
    n_words = new_text.split()
    limit = min(max_words, len(c_words), len(n_words))
    for k in range(limit, 1, -1):
        if c_words[-k:] == n_words[:k]:
            return " ".join(n_words[k:])
    return new_text


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
