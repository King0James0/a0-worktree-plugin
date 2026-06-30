"""Background maintenance for a0_worktree (driven by the throttled job_loop/_60 extension).

Two best-effort, fail-safe jobs:

  1. **Orphan sweep.** Remove a `usr/chats/<id>/` folder that per-chat isolation STRANDED: it has a
     `workdir/` (our footprint) but NO `chat.json`, is NOT a live in-memory `AgentContext`, and is
     older than a grace window. This closes the gap where a stale code-execution shell re-creates an
     isolated workdir AFTER its chat was deleted (A0's chat reaping is context-driven — `chat_remove`
     and the API-chat reaper both start from an in-memory context; NOTHING scans the chats directory,
     so a folder that has lost its `chat.json` is invisible to every cleanup path and lingers forever).

  2. **Name index.** Maintain a read-only `usr/chats/by-name/<slug>__<id> -> ../<id>` symlink farm so
     chats can be browsed/searched by their title instead of their random 8-char id. Rebuilt each
     pass; the real id-keyed folders are NEVER renamed, moved, or written to.

Good-neighbour rules: only a folder bearing OUR footprint is ever removed (never enumerate-and-nuke
"all chat folders"), a folder with a `chat.json` is NEVER touched, and everything is wrapped so this
can never raise into the job loop.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time

PLUGIN_NAME = "a0_worktree"
_BY_NAME = "by-name"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
# Don't sweep a folder younger than this — avoids racing a chat that is mid-creation (workdir made
# microseconds before its first chat.json save) on a clock where liveness can't yet be confirmed.
ORPHAN_GRACE_SECS = 30 * 60


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[{PLUGIN_NAME}] {msg}")
    except Exception:
        print(f"[{PLUGIN_NAME}] {msg}")


def _chats_dir() -> str | None:
    """Absolute path to usr/chats. None on failure (fail-safe → callers no-op)."""
    try:
        from helpers import files

        return files.get_abs_path("usr/chats")
    except Exception:
        return None


def _live_ids() -> set[str] | None:
    """Set of in-memory context ids. None means 'unknown' → the sweep stays its hand (conservative)."""
    try:
        from agent import AgentContext

        return {str(c.id) for c in AgentContext.all()}
    except Exception:
        return None


def slugify(name: str | None) -> str:
    """Filesystem-safe slug from a chat title; never empty (falls back to 'chat')."""
    s = (name or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    if len(s) > 40:
        s = s[:40].rstrip("-")
    return s or "chat"


def _chat_name(chat_dir: str) -> str:
    try:
        with open(os.path.join(chat_dir, "chat.json"), encoding="utf-8") as f:
            return json.load(f).get("name") or ""
    except Exception:
        return ""


def sweep_orphans(now: float | None = None) -> list[str]:
    """Remove stranded isolation folders. Returns the ids removed. Best-effort; never raises."""
    removed: list[str] = []
    chats = _chats_dir()
    if not chats or not os.path.isdir(chats):
        return removed
    live = _live_ids()
    now = time.time() if now is None else now
    try:
        entries = os.listdir(chats)
    except Exception:
        return removed
    for entry in entries:
        if entry == _BY_NAME or not _SAFE_ID.match(entry):
            continue
        d = os.path.join(chats, entry)
        if not os.path.isdir(d):
            continue
        # A real chat ALWAYS has chat.json — never touch it.
        if os.path.exists(os.path.join(d, "chat.json")):
            continue
        # Only OUR footprint: a stranded isolation folder is a workdir/ with no chat.json.
        if not os.path.isdir(os.path.join(d, "workdir")):
            continue
        # Live context (chat mid-creation, before first save) — never touch. Unknown → also skip.
        if live is None or entry in live:
            continue
        try:
            if now - os.path.getmtime(d) < ORPHAN_GRACE_SECS:
                continue
        except Exception:
            continue
        try:
            shutil.rmtree(d)
            removed.append(entry)
        except Exception:
            pass
    return removed


def remove_name_index() -> None:
    """Delete the by-name symlink farm (on toggle-off or uninstall). Best-effort."""
    chats = _chats_dir()
    if not chats:
        return
    by_name = os.path.join(chats, _BY_NAME)
    try:
        if os.path.isdir(by_name):
            shutil.rmtree(by_name)  # unlinks symlinks; never follows them into real chat folders
    except Exception:
        pass


def rebuild_name_index() -> int:
    """Wipe + rebuild usr/chats/by-name/<slug>__<id> -> ../<id>. Returns the link count. Best-effort.

    Wipe-and-rebuild clears stale entries after a rename or delete. rmtree on a tree of symlinks
    unlinks them WITHOUT following, so the real id-keyed chat folders are never at risk.
    """
    chats = _chats_dir()
    if not chats or not os.path.isdir(chats):
        return 0
    by_name = os.path.join(chats, _BY_NAME)
    try:
        if os.path.isdir(by_name):
            shutil.rmtree(by_name)
        os.makedirs(by_name, exist_ok=True)
    except Exception:
        return 0
    n = 0
    try:
        entries = sorted(os.listdir(chats))
    except Exception:
        return 0
    for entry in entries:
        if entry == _BY_NAME or not _SAFE_ID.match(entry):
            continue
        d = os.path.join(chats, entry)
        if not os.path.isdir(d) or not os.path.exists(os.path.join(d, "chat.json")):
            continue
        link = os.path.join(by_name, f"{slugify(_chat_name(d))}__{entry}")
        try:
            os.symlink(os.path.join("..", entry), link)  # relative target, points at usr/chats/<id>
            n += 1
        except Exception:
            pass
    return n


def run(enable_name_index: bool) -> None:
    """One maintenance pass: always sweep orphans; rebuild or tear down the name index per the toggle."""
    try:
        swept = sweep_orphans()
        if swept:
            _log(f"swept {len(swept)} stranded chat folder(s): {swept}")
    except Exception as e:
        _log(f"orphan sweep failed (non-fatal): {e}")
    try:
        if enable_name_index:
            rebuild_name_index()
        else:
            remove_name_index()
    except Exception as e:
        _log(f"name index failed (non-fatal): {e}")
