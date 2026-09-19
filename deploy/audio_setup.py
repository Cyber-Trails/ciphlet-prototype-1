#!/usr/bin/env python3
"""Detect, verify and configure the Pi's speaker for Ciphlet (stdlib only).
Called by deploy/install_voice.sh; safe to re-run.

What it does:
  1. Lists playback cards (`aplay -l`) and picks one: a USB card first, then any
     non-HDMI card, then HDMI last.
  2. Unmutes / raises the playback volume on that card ONLY where a control is
     muted or below 50% (a muted USB-speaker "PCM"/"Speaker" control is a
     classic cause of "it plays but I hear nothing").
  3. Plays a short beep through each candidate ALSA device (a `plughw:` route,
     so ALSA converts rate/format for speakers that only do 44.1/48 kHz) and
     keeps the first that plays without error.
  4. Writes it to CIPHLET_AUDIO_OUTPUT_DEVICE in .env — only if that key is
     missing or blank. A non-empty value is never changed; it is just tested.

Nothing here can prove you *heard* the beep — `ciphlet voice --selftest` asks.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass

import env_defaults  # same directory (the script dir is first on sys.path)

KEY = "CIPHLET_AUDIO_OUTPUT_DEVICE"
_CARD_RE = re.compile(r"^card (\d+): (\S+) \[(.*?)\], device (\d+): (.*?) \[(.*?)\]", re.MULTILINE)


@dataclass(frozen=True)
class Card:
    index: int
    id: str
    name: str
    dev: int
    dev_name: str
    desc: str


def parse_aplay_l(text: str) -> list[Card]:
    return [
        Card(int(m.group(1)), m.group(2), m.group(3), int(m.group(4)), m.group(5), m.group(6))
        for m in _CARD_RE.finditer(text)
    ]


def rank(card: Card) -> int:
    """0 = USB (an external speaker/headset), 1 = other, 2 = HDMI (usually a monitor)."""
    blob = f"{card.name} {card.dev_name} {card.desc}".lower()
    if "hdmi" in blob or "vc4" in blob:
        return 2
    return 0 if "usb" in blob else 1


def choose_card(cards: list[Card]) -> Card | None:
    return min(cards, key=rank, default=None)  # min is stable: first of equal rank wins


def candidate_devices(card: Card) -> list[str]:
    # By card *id* (stable), not number: USB card numbers can change between boots.
    return [f"plughw:CARD={card.id},DEV={card.dev}", f"sysdefault:CARD={card.id}"]


def normalize_device(device: str) -> str:
    """Same rule as PiperTTS: a bare hw: has no rate conversion, plughw: does."""
    return "plug" + device if device.startswith("hw:") else device


@dataclass(frozen=True)
class MixerFix:
    name: str
    args: list[str]  # amixer sset arguments after the control name


def parse_amixer(text: str) -> list[MixerFix]:
    """Playback controls that are muted or under 50% -> the sset to fix them."""
    fixes = []
    for block in text.split("Simple mixer control '")[1:]:
        name = block.split("'", 1)[0]
        caps = re.search(r"Capabilities:(.*)", block)
        caps_s = caps.group(1) if caps else ""
        has_vol, has_sw = "pvolume" in caps_s, "pswitch" in caps_s
        if not (has_vol or has_sw):
            continue  # capture-only or unrelated control
        muted = "[off]" in block
        pct = [int(p) for p in re.findall(r"\[(\d+)%\]", block)]
        low = has_vol and pct and min(pct) < 50
        if muted or low:
            args = (["80%"] if has_vol and (low or not has_sw) else []) + (["unmute"] if has_sw else [])
            fixes.append(MixerFix(name, args))
    return fixes


def make_beep(path: str, seconds: float = 0.5, freq: float = 660.0, rate: int = 48000) -> None:
    n = int(rate * seconds)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        fade = int(rate * 0.02)
        frames = bytearray()
        for i in range(n):
            env = min(1.0, i / fade, (n - i) / fade)  # short fade in/out: no click
            frames += struct.pack("<h", int(9000 * env * math.sin(2 * math.pi * freq * i / rate)))
        w.writeframes(bytes(frames))


def run(cmd: list[str], timeout: float = 15.0) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return r.returncode == 0, (r.stderr or r.stdout).strip()


def unmute(card: Card) -> None:
    ok, out = run(["amixer", "-c", str(card.index), "scontents"])
    if not ok:
        return
    for fix in parse_amixer(out):
        done, err = run(["amixer", "-c", str(card.index), "-q", "sset", fix.name, *fix.args])
        print(f"  mixer: card {card.index} '{fix.name}' -> {' '.join(fix.args)}" + ("" if done else f" (failed: {err})"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default=".env")
    args = ap.parse_args(argv)

    if shutil.which("aplay") is None:
        print("  aplay not found (sudo apt-get install -y alsa-utils) — skipping speaker setup")
        return 0
    ok, out = run(["aplay", "-l"])
    cards = parse_aplay_l(out) if ok else []
    if not cards:
        print("  no ALSA playback devices found — plug in the speaker and re-run this installer")
        return 0
    print("  playback devices:")
    for c in cards:
        print(f"    card {c.index} [{c.id}] {c.desc}")

    try:
        with open(args.env, encoding="utf-8") as fh:
            existing = env_defaults.get_value(fh.read(), KEY)
    except FileNotFoundError:
        existing = ""

    with tempfile.TemporaryDirectory() as tmp:
        beep = os.path.join(tmp, "beep.wav")
        make_beep(beep)

        if existing:  # user-configured: never overwrite, just report whether it plays
            good, err = run(["aplay", "-q", "-D", normalize_device(existing), beep])
            print(f"  {KEY}={existing} kept (" + ("plays OK" if good else f"WARNING: playback failed: {err}") + ")")
            return 0

        card = choose_card(cards)
        assert card is not None
        print(f"  using card {card.index} [{card.id}] ({card.desc})")
        unmute(card)
        print("  playing a short beep...")
        errors = []
        for device in candidate_devices(card):
            good, err = run(["aplay", "-q", "-D", device, beep])
            if good:
                env_defaults.update_env_file(args.env, {KEY: device})
                print(f"  {KEY}={device}")
                return 0
            errors.append(f"{device}: {err}")
        print("  WARNING: could not play through the detected card, leaving " + KEY + " unset:")
        for e in errors:
            print(f"    {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
