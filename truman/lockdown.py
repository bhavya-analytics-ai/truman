"""
lockdown.py — Security lockdown screen
Shows aggressive visual for 6 seconds, then sleeps the display.
ESC key exits the screen at any time and returns to normal.

trigger_lockdown() spawns itself as a subprocess so it's safe to call
from any thread (pygame requires the main thread for NSWindow on Mac).
"""

import os
import sys
import subprocess


def trigger_lockdown():
    """Call from any thread — runs the screen in a fresh subprocess."""
    subprocess.Popen([sys.executable, __file__])


def _run_screen():
    import pygame
    import random
    import math
    import time
    pygame.display.init()
    pygame.font.init()

    info   = pygame.display.Info()
    W, H   = info.current_w, info.current_h
    screen = pygame.display.set_mode((W, H), pygame.FULLSCREEN | pygame.NOFRAME)
    clock  = pygame.time.Clock()

    font_big = pygame.font.SysFont("Courier", 32, bold=True)
    font_sm  = pygame.font.SysFont("Courier", 13)
    font_esc = pygame.font.SysFont("Courier", 16)

    nodes = [
        {"x": random.randint(0, W), "y": random.randint(0, H),
         "vx": random.uniform(-5, 5), "vy": random.uniform(-5, 5)}
        for _ in range(80)
    ]
    particles = []
    start     = time.time()
    duration  = 10
    running   = True

    while running and (time.time() - start < duration):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    # ESC — exit lockdown screen immediately, return to normal
                    pygame.display.quit()
                    return

        screen.fill((0, 0, 0))

        # moving nodes
        for n in nodes:
            n["vx"] += random.uniform(-0.5, 0.5)
            n["vy"] += random.uniform(-0.5, 0.5)
            n["vx"]  = max(-8, min(8, n["vx"]))
            n["vy"]  = max(-8, min(8, n["vy"]))
            n["x"]  += n["vx"]
            n["y"]  += n["vy"]
            if n["x"] < 0 or n["x"] > W: n["vx"] *= -1
            if n["y"] < 0 or n["y"] > H: n["vy"] *= -1

        # connections between nodes
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"])
                if dist < 200:
                    alpha = int(255 * (1 - dist / 200))
                    pygame.draw.line(screen, (0, alpha, 0),
                                     (int(a["x"]), int(a["y"])),
                                     (int(b["x"]), int(b["y"])), 1)

        for n in nodes:
            pygame.draw.circle(screen, (0, 255, 60), (int(n["x"]), int(n["y"])), 5)

        # matrix rain
        for _ in range(5):
            particles.append({"x": random.randint(0, W), "y": 0,
                               "speed": random.uniform(10, 25),
                               "char": chr(random.randint(33, 126))})
        for p in particles[:]:
            p["y"] += p["speed"]
            if p["y"] > H:
                particles.remove(p)
                continue
            screen.blit(font_sm.render(p["char"], True,
                        (0, random.randint(150, 255), 0)), (p["x"], int(p["y"])))

        # flashing warning text
        elapsed = time.time() - start
        if int(elapsed * 3) % 2 == 0:
            warn = font_big.render("⚠  UNAUTHORIZED ACCESS DETECTED  ⚠", True, (255, 0, 0))
            screen.blit(warn, (W // 2 - warn.get_width() // 2, H // 2 - 50))
            sub = font_big.render("NOTIFYING OM — LOCKING SYSTEM", True, (255, 100, 0))
            screen.blit(sub, (W // 2 - sub.get_width() // 2, H // 2 + 10))

        # ESC hint at bottom
        esc_hint = font_esc.render("Press ESC to dismiss", True, (100, 100, 100))
        screen.blit(esc_hint, (W // 2 - esc_hint.get_width() // 2, H - 40))

        pygame.display.flip()
        clock.tick(60)

    pygame.display.quit()
    subprocess.Popen(["pmset", "displaysleepnow"])


if __name__ == "__main__":
    _run_screen()
