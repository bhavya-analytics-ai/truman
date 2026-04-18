"""
hotkey.py — Global hotkey listener for Truman
Cmd+Option+T → toggle realtime session on/off from anywhere on the Mac.

Cmd+Shift+T was claimed by Claude Code / browser "reopen closed tab".
Option key is also named Alt; pynput uses keyboard.Key.alt for it.

Install if missing:
    pip install pynput
"""
import threading
from pynput import keyboard

# Accept either Option (alt) modifier; pynput reports either .alt, .alt_l, or .alt_r
_ALT_KEYS = {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}
_CMD_KEYS = {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r}
_KEY_T = keyboard.KeyCode(char='t')
# pynput sometimes delivers Option+T as the special char '†' (dagger) on macOS
_KEY_T_OPT_MAC = keyboard.KeyCode(char='†')

_pressed   = set()
_toggle_fn = None
_fired     = False   # debounce — don't fire twice per press


def _has_cmd() -> bool:
    return any(k in _pressed for k in _CMD_KEYS)


def _has_alt() -> bool:
    return any(k in _pressed for k in _ALT_KEYS)


def _on_press(key):
    global _fired
    _pressed.add(key)

    # Cmd+Option+T — on macOS the T keystroke with Option pressed may arrive as '†'
    t_down = (_KEY_T in _pressed) or (_KEY_T_OPT_MAC in _pressed) or (key == _KEY_T) or (key == _KEY_T_OPT_MAC)

    if t_down and _has_cmd() and _has_alt() and not _fired:
        _fired = True
        if _toggle_fn:
            threading.Thread(target=_toggle_fn, daemon=True).start()


def _on_release(key):
    global _fired
    _pressed.discard(key)
    # reset debounce when T (or its Option-variant) is released
    if key in (_KEY_T, _KEY_T_OPT_MAC):
        _fired = False


def start(toggle_fn):
    """
    Start the global hotkey listener.
    toggle_fn is called each time Cmd+Option+T is pressed.
    """
    global _toggle_fn
    _toggle_fn = toggle_fn
    listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
    listener.daemon = True
    listener.start()
    print("[Hotkey] Cmd+Option+T → toggle Truman listening")
