#!/usr/bin/env python3
"""Idempotently fill managed keys in a .env file — used by deploy/install_voice.sh.

Contract, per managed key:
  - missing from the file        -> appended as KEY=value
  - present with an empty value  -> value filled in (KEY=, KEY="", KEY='', or
                                    KEY= # comment; an `export ` prefix, leading
                                    whitespace and any trailing comment are kept)
  - present with a non-empty value -> left exactly as-is, never overwritten

Every other byte of the file — unrelated keys, secrets, comments, blank lines,
line endings — is preserved. Commented-out lines (`# KEY=...`) are not keys.
If a key appears more than once, the LAST occurrence is the effective one (this
matches python-dotenv, which ciphlet/config.py uses), so that is the one judged
and, if blank, filled. Nothing is written when nothing changes, so re-running
is a no-op (file contents, mtime and permissions all untouched).

Usage:
  env_defaults.py --env PATH [--set KEY=VALUE]... [--set-if-file KEY=PATH]...

  --set KEY=VALUE        manage KEY with VALUE.
  --set-if-file KEY=PATH manage KEY with PATH only if PATH is an existing file;
                         otherwise KEY is skipped entirely (nothing added, and
                         any existing value is preserved).

Stdlib only. Never prints values other than the ones it is managing.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile

_SAFE_UNQUOTED = re.compile(r"^[A-Za-z0-9_./:@%+=,~-]+$")


def _quote(value: str) -> str:
    """Quote only when needed so dotenv reads the value back exactly."""
    if _SAFE_UNQUOTED.match(value):
        return value
    if "'" not in value:
        return f"'{value}'"  # single quotes: no $-expansion, no escapes
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _line_key_re(key: str) -> re.Pattern[str]:
    # ^ indent, optional `export `, KEY, optional spaces, `=`, then the rest.
    return re.compile(r"^(?P<head>[ \t]*(?:export[ \t]+)?" + re.escape(key) + r"[ \t]*=)(?P<rest>.*)$")


def _split_eol(line: str) -> tuple[str, str]:
    body = line.rstrip("\r\n")
    return body, line[len(body):]


def _split_value(rest: str) -> tuple[str, str]:
    """Split the text after '=' into (value, trailing_comment_with_leading_space).

    Only recognises the shapes that count as "blank"; anything else is treated
    as a non-empty value in its entirety and is never edited.
    """
    stripped = rest.strip()
    if stripped == "" or stripped in ('""', "''"):
        return "", ""
    if stripped.startswith("#"):  # `KEY= # note` — dotenv reads this as empty
        return "", " " + stripped
    for q in ('"', "'"):  # `KEY="" # note`
        if stripped.startswith(q * 2) and stripped[2:].lstrip().startswith("#"):
            return "", " " + stripped[2:].lstrip()
    return rest, ""


def get_value(text: str, key: str) -> str:
    """Effective value of `key` (last occurrence wins, like python-dotenv) with
    surrounding quotes removed; "" if the key is absent or blank."""
    pattern = _line_key_re(key)
    value = ""
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            value, _ = _split_value(m.group("rest"))
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
    return value


def apply_defaults(text: str, managed: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Return (new_text, {key: 'added'|'filled'|'kept'}). Pure function."""
    lines = text.splitlines(keepends=True)
    first_eol = next((_split_eol(ln)[1] for ln in lines if _split_eol(ln)[1]), "\n")
    status: dict[str, str] = {}

    for key, value in managed.items():
        pattern = _line_key_re(key)
        last_idx = None
        for i, ln in enumerate(lines):
            if pattern.match(_split_eol(ln)[0]):
                last_idx = i
        if last_idx is None:
            if lines and not _split_eol(lines[-1])[1]:
                lines[-1] += first_eol  # terminate an unterminated last line
            lines.append(f"{key}={_quote(value)}{first_eol}")
            status[key] = "added"
            continue

        body, eol = _split_eol(lines[last_idx])
        m = pattern.match(body)
        assert m is not None
        current, comment = _split_value(m.group("rest"))
        if current.strip():
            status[key] = "kept"
            continue
        lines[last_idx] = f"{m.group('head')}{_quote(value)}{comment}{eol}"
        status[key] = "filled"

    return "".join(lines), status


def update_env_file(path: str, managed: dict[str, str]) -> dict[str, str]:
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            original = fh.read()
    except FileNotFoundError:
        original = ""
        existed = False
    else:
        existed = True

    updated, status = apply_defaults(original, managed)
    if updated == original and existed:
        return status  # nothing to change: don't touch the file at all

    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".env.", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(updated)
        if existed:
            shutil.copymode(path, tmp)  # keep e.g. 0600 on a secrets file
        else:
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return status


def _parse_pair(arg: str) -> tuple[str, str]:
    key, sep, value = arg.partition("=")
    if not sep or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key) or value == "":
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE with a non-empty value, got {arg!r}")
    return key, value


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", required=True, help="path to the .env file (created if missing)")
    ap.add_argument("--set", dest="sets", action="append", default=[], type=_parse_pair, metavar="KEY=VALUE")
    ap.add_argument("--set-if-file", dest="set_if_file", action="append", default=[], type=_parse_pair, metavar="KEY=PATH")
    args = ap.parse_args(argv)

    managed = dict(args.sets)
    skipped = []
    for key, path in args.set_if_file:
        if os.path.isfile(path):
            managed[key] = path
        else:
            skipped.append(key)

    status = update_env_file(args.env, managed) if managed else {}
    for key in managed:
        verb = {"added": "added", "filled": "filled blank", "kept": "kept existing"}[status[key]]
        shown = "" if status[key] == "kept" else f" = {managed[key]}"
        print(f"  {key}: {verb}{shown}")
    for key in skipped:
        print(f"  {key}: skipped (no file to point at; existing value, if any, preserved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
