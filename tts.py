import asyncio
import os
import subprocess
import tempfile
import threading
from config import TTS_VOICE

_proc_lock = threading.Lock()
_current_proc: "subprocess.Popen | None" = None

# One persistent event loop avoids the overhead of creating/closing a loop per call
_loop = asyncio.new_event_loop()
threading.Thread(target=_loop.run_forever, daemon=True, name="tts-loop").start()


async def _synthesize(text: str, path: str) -> None:
    import edge_tts
    await edge_tts.Communicate(text, TTS_VOICE).save(path)


def speak(text: str) -> None:
    """Synthesize text with edge-tts and play via mpv. Blocks until done."""
    global _current_proc

    text = text.strip()
    if not text:
        return
    if len(text) > 600:
        text = text[:597] + "..."

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp = f.name

    try:
        future = asyncio.run_coroutine_threadsafe(_synthesize(text, tmp), _loop)
        future.result()

        proc = subprocess.Popen(
            ["mpv", "--no-terminal", "--really-quiet", tmp],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with _proc_lock:
            _current_proc = proc
        proc.wait()
    finally:
        with _proc_lock:
            _current_proc = None
        try:
            os.unlink(tmp)
        except OSError:
            pass


def stop() -> None:
    """Interrupt any currently playing speech."""
    with _proc_lock:
        if _current_proc and _current_proc.poll() is None:
            _current_proc.terminate()
