#!/usr/bin/env python3
"""Local ASR via faster-whisper (free, no quota). Model cached at ~/.cache/huggingface."""
import os, sys, time, logging

logger = logging.getLogger("LocalASR")
MODEL_NAME = os.environ.get("LELE_ASR_MODEL", "small")

_model = None

def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        t0 = time.time()
        _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        logger.info(f"whisper {MODEL_NAME} loaded in {time.time()-t0:.1f}s")
    return _model

def transcribe_wav(wav_bytes: bytes) -> str:
    import tempfile
    tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        tf.write(wav_bytes)
        tf.close()
        model = _get_model()
        segments, info = model.transcribe(tf.name, language="zh", beam_size=5, vad_filter=True,
                                          vad_parameters={"min_silence_duration_ms": 300})
        text = "".join(s.text for s in segments).strip()
        return text
    finally:
        os.unlink(tf.name)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    data = open(sys.argv[1], "rb").read()
    t0 = time.time()
    print(repr(transcribe_wav(data)), f"({time.time()-t0:.1f}s)")
