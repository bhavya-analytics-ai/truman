"""
Truman Gesture Module — Level 3
MediaPipe GestureRecognizer (new Tasks API), on-demand only. Battery-safe.

Recognized gestures:
  Open_Palm  → stop Truman speaking
  Closed_Fist → trigger lockdown
  Pointing_Up → (reserved for future)

Activate:  say "gesture mode"  → start_gesture_mode()
Deactivate: say "stop gestures" → stop_gesture_mode()
"""

import os
import threading
import time
import cv2
import mediapipe as mp

_gesture_thread = None
_running = False

# path to downloaded model
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "gesture_recognizer.task")

BaseOptions       = mp.tasks.BaseOptions
GestureRecognizer = mp.tasks.vision.GestureRecognizer
GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
RunningMode       = mp.tasks.vision.RunningMode


def _gesture_loop(on_fist, on_palm):
    global _running

    if not os.path.exists(_MODEL_PATH):
        print("[Truman] Gesture model not found. Run: download_gesture_model()")
        _running = False
        return

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[Truman] Gesture mode: no camera found.")
        _running = False
        return

    print("[Truman] Gesture mode active — Open Palm = stop, Fist = lockdown")

    options = GestureRecognizerOptions(
        base_options=BaseOptions(model_asset_path=_MODEL_PATH),
        running_mode=RunningMode.IMAGE,
        num_hands=1,
        min_hand_detection_confidence=0.6,
        min_hand_presence_confidence=0.6,
        min_tracking_confidence=0.5,
    )

    last_trigger = 0
    COOLDOWN = 2.0  # seconds between same gesture triggers

    with GestureRecognizer.create_from_options(options) as recognizer:
        while _running:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

            result = recognizer.recognize(mp_image)

            if result.gestures:
                gesture_name = result.gestures[0][0].category_name
                now = time.time()

                if now - last_trigger > COOLDOWN:
                    if gesture_name == "Closed_Fist" and on_fist:
                        print("[Truman] Fist — locking down.")
                        on_fist()
                        last_trigger = now

                    elif gesture_name == "Open_Palm" and on_palm:
                        print("[Truman] Palm — stopping speech.")
                        on_palm()
                        last_trigger = now

            time.sleep(0.05)  # ~20fps — light on CPU

    cap.release()
    print("[Truman] Gesture mode off.")


def start_gesture_mode(on_fist=None, on_palm=None):
    """Start gesture tracking in background. Battery-safe — camera off when not called."""
    global _gesture_thread, _running

    if _running:
        print("[Truman] Gesture mode already running.")
        return

    _running = True
    _gesture_thread = threading.Thread(
        target=_gesture_loop,
        args=(on_fist, on_palm),
        daemon=True
    )
    _gesture_thread.start()


def stop_gesture_mode():
    """Stop gesture tracking and release camera."""
    global _running
    _running = False
