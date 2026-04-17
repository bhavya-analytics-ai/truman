import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
import csv
import io
import urllib.request

# load YAMNet once at import
print("Loading YAMNet sound classifier...")
_model = hub.load("https://tfhub.dev/google/yamnet/1")

# load class names
_class_map_url = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
with urllib.request.urlopen(_class_map_url) as f:
    reader = csv.DictReader(io.TextIOWrapper(f))
    _class_names = [r["display_name"] for r in reader]

print("YAMNet ready.")

COUGH_LABELS = {"cough", "sneeze", "throat clearing"}
CLAP_LABELS = {"clapping", "hands", "applause"}
CONFIDENCE_THRESHOLD = 0.3


def classify(raw_pcm: bytes, sample_rate: int = 16000) -> str | None:
    """
    Returns 'cough', 'clap', or None.
    raw_pcm: raw int16 PCM bytes
    """
    audio = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0

    scores, embeddings, spectrogram = _model(audio)
    mean_scores = tf.reduce_mean(scores, axis=0).numpy()

    top_indices = np.argsort(mean_scores)[::-1][:5]

    for idx in top_indices:
        label = _class_names[idx].lower()
        score = mean_scores[idx]
        if score < CONFIDENCE_THRESHOLD:
            continue
        if any(c in label for c in COUGH_LABELS):
            return "cough"
        if any(c in label for c in CLAP_LABELS):
            return "double_clap"

    return None
