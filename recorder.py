import threading
import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
CHUNK_MS = 50
CHUNK_SIZE = int(SAMPLE_RATE * CHUNK_MS / 1000)

# Tuning knobs
SILENCE_THRESHOLD = 0.008   # RMS below this = silence
SILENCE_DURATION = 1.8      # seconds of silence → stop recording
PRE_SPEECH_TIMEOUT = 5.0    # give up if no speech detected within this time
MAX_DURATION = 30.0         # hard ceiling on recording length


def record_voice(
    interrupt: "threading.Event | None" = None,
    on_level: "callable | None" = None,
) -> "np.ndarray | None":
    """
    Record from the default microphone until the user stops speaking.
    Returns a float32 numpy array (mono, 16 kHz) or None if no speech detected.
    Pass an interrupt Event to cancel recording early from another thread.
    """
    frames = []
    speech_detected = False
    silent_chunks = 0
    pre_speech_chunks = 0
    stop_event = threading.Event()

    silence_needed = int(SILENCE_DURATION * 1000 / CHUNK_MS)
    pre_speech_limit = int(PRE_SPEECH_TIMEOUT * 1000 / CHUNK_MS)
    max_chunks = int(MAX_DURATION * 1000 / CHUNK_MS)

    def callback(indata, frame_count, time_info, status):
        nonlocal speech_detected, silent_chunks, pre_speech_chunks

        if interrupt and interrupt.is_set():
            stop_event.set()
            return

        chunk = indata.copy()
        frames.append(chunk)
        rms = float(np.sqrt(np.mean(chunk ** 2)))
        if on_level:
            on_level(rms)

        if rms > SILENCE_THRESHOLD:
            speech_detected = True
            silent_chunks = 0
        else:
            if speech_detected:
                silent_chunks += 1
                if silent_chunks >= silence_needed:
                    stop_event.set()
            else:
                pre_speech_chunks += 1
                if pre_speech_chunks >= pre_speech_limit:
                    stop_event.set()

        if len(frames) >= max_chunks:
            stop_event.set()

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        blocksize=CHUNK_SIZE,
        callback=callback,
    ):
        stop_event.wait(MAX_DURATION + PRE_SPEECH_TIMEOUT + 1)

    if not speech_detected or not frames:
        return None

    return np.concatenate(frames, axis=0).flatten()
