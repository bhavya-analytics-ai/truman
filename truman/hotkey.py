"""
hotkey.py — Global hotkey listener for Truman
Cmd+Shift+T → toggle realtime session on/off from anywhere on the Mac.

Install if missing:
    pip install pynput
"""
import threading
from pynput import keyboard

_MODS  = {keyboard.Key.cmd, keyboard.Key.shift}
_KEY_T = keyboard.KeyCode(char='t')

_pressed   = set()
_toggle_fn = None
_fired     = False   # debounce — don't fire twice per press


def _on_press(key):
    global _fired
    _pressed.add(key)

    # Cmd+Shift+T
    if _KEY_T in _pressed and _MODS.issubset(_pressed) and not _fired:
        _fired = True
        if _toggle_fn:
            threading.Thread(target=_toggle_fn, daemon=True).start()


def _on_release(key):
    global _fired
    _pressed.discard(key)
    # reset debounce when T is released
    if key == _KEY_T:
        _fired = False


def start(toggle_fn):
    """
    Start the global hotkey listener.
    toggle_fn is called each time Cmd+Shift+T is pressed.
    """
    global _toggle_fn
    _toggle_fn = toggle_fn
    listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    print("[Hotkey] Cmd+Shift+T → toggle Truman listening")
