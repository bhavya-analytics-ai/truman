import os
import numpy as np
import soundfile as sf
import tempfile
import threading
from resemblyzer import VoiceEncoder, preprocess_wav
from config import OPENAI_API_KEY

encoder = VoiceEncoder()

VOICE_PROFILE_PATH = os.path.join(os.path.dirname(__file__), "om_voice.npy")
SIMILARITY_THRESHOLD = 0.65

TRUMAN_SPEAKING = False  # flag to disable ambient detection while Truman speaks


def set_speaking(state: bool):
    global TRUMAN_SPEAKING
    TRUMAN_SPEAKING = state


def record_sample(duration=5):
    """Record a voice sample for enrollment."""
    import pyaudio
    import wave
    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=1, rate=16000, input=True, frames_per_buffer=1024)
    print(f"Recording for {duration} seconds...")
    frames = [stream.read(1024) for _ in range(int(16000 / 1024 * duration))]
    stream.stop_stream()
    stream.close()
    p.terminate()

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wf = wave.open(tmp.name, 'wb')
    wf.setnchannels(1)
    wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
    wf.setframerate(16000)
    wf.writeframes(b''.join(frames))
    wf.close()
    return tmp.name


def enroll_om():
    """Record Om's voice across 3 rounds and average the embeddings for a solid voice print."""
    embeddings = []
    rounds = 3
    duration = 10

    for i in range(rounds):
        print(f"\nRound {i+1}/{rounds} — speak naturally for {duration} seconds (talk about anything)...")
        path = record_sample(duration=duration)
        wav = preprocess_wav(path)
        emb = encoder.embed_utterance(wav)
        embeddings.append(emb)
        os.unlink(path)
        if i < rounds - 1:
            print("Good. Short break — next round in 2 seconds...")
            import time; time.sleep(2)

    # average all 3 embeddings — much more robust than single sample
    final_embedding = np.mean(embeddings, axis=0)
    final_embedding /= np.linalg.norm(final_embedding)  # normalize
    np.save(VOICE_PROFILE_PATH, final_embedding)
    print("\nVoice enrolled across 3 rounds. Truman knows you now.")


def verify_voice(audio_path) -> bool:
    """Returns True if the audio matches Om's voice."""
    if not os.path.exists(VOICE_PROFILE_PATH):
        return True
    try:
        wav = preprocess_wav(audio_path)
        if len(wav) < 16000 * 0.3:   # under 0.3s — too tiny to score
            return True
        om_embedding = np.load(VOICE_PROFILE_PATH)
        embedding    = encoder.embed_utterance(wav)
        similarity   = float(np.dot(om_embedding, embedding) / (
                           np.linalg.norm(om_embedding) * np.linalg.norm(embedding)))
        print(f"[Auth] Voice similarity: {similarity:.3f} (threshold: {SIMILARITY_THRESHOLD})")
        return similarity >= SIMILARITY_THRESHOLD
    except Exception as e:
        print(f"[Auth] Error: {e} — letting through")
        return True


def is_om_enrolled():
    return os.path.exists(VOICE_PROFILE_PATH)
