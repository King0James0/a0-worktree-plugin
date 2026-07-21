"""Background maintenance for a0_worktree (driven by the throttled job_loop/_60 extension).

Three best-effort, fail-safe jobs (all runs recorded in a durable marker at
`usr/a0_worktree-runtime/maintenance.json` — see write_marker):

  1. **Orphan sweep.** Remove a `usr/chats/<id>/` folder that per-chat isolation STRANDED: it has a
     `workdir/` (our footprint) but NO `chat.json`, is NOT a live in-memory `AgentContext`, and is
     older than a grace window. This closes the gap where a stale code-execution shell re-creates an
     isolated workdir AFTER its chat was deleted (A0's chat reaping is context-driven — `chat_remove`
     and the API-chat reaper both start from an in-memory context; NOTHING scans the chats directory,
     so a folder that has lost its `chat.json` is invisible to every cleanup path and lingers forever).

  2. **Stale iso-ref sweep (v1.3.0).** Clear persisted `_a0wt_iso_*` project references from chat
     contexts and scheduler task records — they are never legitimately stored (isolation names are
     computed at read time) and a dangling one crashes prompt-prep for the context carrying it.
     See sweep_stale_iso_refs for the full story and the good-neighbour rules.

  3. **Name index.** Maintain a read-only `usr/chats/by-name/<slug>__<id> -> ../<id>` symlink farm so
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
from datetime import datetime, timezone

PLUGIN_NAME = "a0_worktree"
_BY_NAME = "by-name"
_ISO_PREFIX = "_a0wt_iso_"  # must match helpers/isolation.py
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


def _tasks_json_path() -> str | None:
    """Absolute path to the scheduler's tasks.json. None on failure (fail-safe → leg no-ops)."""
    try:
        from helpers import files

        return files.get_abs_path("usr/scheduler/tasks.json")
    except Exception:
        return None


def _runtime_dir() -> str | None:
    """Durable runtime-state dir OUTSIDE the watched plugin tree (survives plugin reinstalls,
    never triggers the watchdog). None on failure (fail-safe → marker writes no-op)."""
    try:
        from helpers import files

        d = files.get_abs_path("usr", f"{PLUGIN_NAME}-runtime")
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        return None


def write_marker(sets: dict | None = None, increments: dict | None = None) -> None:
    """Merge values into the durable maintenance marker (usr/a0_worktree-runtime/maintenance.json):
    `sets` overwrite, `increments` add to existing numeric counters. Proves the sweeps run —
    ephemeral logs a host can swallow are not evidence. Best-effort; never raises."""
    d = _runtime_dir()
    if not d:
        return
    p = os.path.join(d, "maintenance.json")
    cur: dict = {}
    try:
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                cur = json.load(f) or {}
    except Exception:
        cur = {}
    for k, v in (sets or {}).items():
        cur[k] = v
    for k, v in (increments or {}).items():
        try:
            cur[k] = int(cur.get(k, 0)) + int(v)
        except Exception:
            cur[k] = v
    try:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cur, f, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass


def remove_runtime_dir() -> None:
    """Delete the runtime-state dir. Since v1.3.1 NOT called on uninstall — the dir carries the
    config stash that must survive the A0 update's uninstall→install cycle. Kept as the manual /
    future purge path. Best-effort."""
    try:
        d = _runtime_dir()
        if d and os.path.isdir(d):
            shutil.rmtree(d)
    except Exception:
        pass


_CONFIG_STASH = "config-stash.json"


def _plugin_dir() -> str | None:
    """Absolute path to our plugin dir (where the framework writes config.json). None on failure."""
    try:
        from helpers import files

        return files.get_abs_path("usr/plugins", PLUGIN_NAME)
    except Exception:
        return None


def stash_config(cfg: dict | None = None) -> None:
    """Config-survives-upgrade, write half (v1.3.1 — the vivy v1.8.10 pattern; motivated by the
    2026-07-20 v1.3.0 install wiping both toggles + the by-name farm): A0's plugin UPDATE is
    uninstall→install and DELETES the plugin dir INCLUDING config.json, losing every operator
    setting. The runtime dir survives an update by design, so mirror the config there on every
    save + at uninstall; `restore_config_stash` brings it back at install. `cfg` given (the save
    hook's dict) is written as-is; else the on-disk config.json is copied. Best-effort."""
    try:
        d = _runtime_dir()
        if not d:
            return
        if cfg is None:
            pd = _plugin_dir()
            src = os.path.join(pd, "config.json") if pd else ""
            if not (src and os.path.exists(src)):
                return
            with open(src, encoding="utf-8") as f:
                cfg = json.load(f)
        if isinstance(cfg, dict) and cfg:
            tmp = os.path.join(d, _CONFIG_STASH + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            os.replace(tmp, os.path.join(d, _CONFIG_STASH))
    except Exception:
        pass


def restore_config_stash() -> dict | None:
    """Config-survives-upgrade, restore half: when the plugin dir has NO config.json (a fresh
    place-down after an update wiped it) and the surviving runtime dir holds a stash, restore it
    BEFORE anything reads config — toggles come back without the manual re-enable. An EXISTING
    config.json always wins (never overwritten); a corrupt stash is ignored (validated before
    writing). Returns the restored dict (so install() can reconcile the farm/wrap), else None."""
    try:
        pd = _plugin_dir()
        if not pd:
            return None
        dst = os.path.join(pd, "config.json")
        if os.path.exists(dst):
            return None
        d = _runtime_dir()
        src = os.path.join(d, _CONFIG_STASH) if d else ""
        if not (src and os.path.exists(src)):
            return None
        with open(src, encoding="utf-8") as f:
            cfg = json.load(f)  # validate BEFORE touching the plugin dir
        if isinstance(cfg, dict) and cfg:
            with open(dst, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
            write_marker(sets={"config_restored_at": datetime.now(timezone.utc)
                               .strftime("%Y-%m-%dT%H:%M:%SZ")})
            return cfg
    except Exception:
        pass
    return None


def _iso_ref(value) -> str | None:
    """The iso pseudo-project name inside a persisted project ref (string or {'name': ...} dict),
    or None if the ref is empty / not iso-shaped."""
    name = value if isinstance(value, str) else (value.get("name") if isinstance(value, dict) else None)
    return name if isinstance(name, str) and name.startswith(_ISO_PREFIX) else None


def sweep_stale_iso_refs() -> dict:
    """Clear PERSISTED `_a0wt_iso_*` project references from chat contexts and scheduler task
    records. Any persisted iso ref is illegitimate — isolation names are computed at read time and
    never stored (see isolation.py); one only gets persisted when an outside writer copies it (the
    task scheduler was one), and it dangles once its chat dies, crashing prompt-prep for whatever
    context carries it. The v1.3.0 isolation guards stop NEW ones; this heals what already exists.

    Good-neighbour rules: a LIVE context is fixed through the framework's own
    `projects.deactivate_project` (memory + disk stay consistent); a chat.json is only edited
    directly when its context is definitely NOT in memory; unknown liveness → touch nothing.
    Returns {"contexts": [ids], "tasks": [names]}. Best-effort; never raises.
    """
    out: dict = {"contexts": [], "tasks": []}
    live = _live_ids()
    chats = _chats_dir()
    if chats and os.path.isdir(chats) and live is not None:
        try:
            entries = os.listdir(chats)
        except Exception:
            entries = []
        for entry in entries:
            if entry == _BY_NAME or not _SAFE_ID.match(entry):
                continue
            cj = os.path.join(chats, entry, "chat.json")
            if not os.path.isfile(cj):
                continue
            try:
                with open(cj, encoding="utf-8") as f:
                    text = f.read()
            except Exception:
                continue
            if _ISO_PREFIX not in text:
                continue
            if entry in live:
                # Live context: never touch its file behind its back — deactivate through the
                # framework so the in-memory context and the persisted chat.json both update.
                try:
                    from agent import AgentContext
                    from helpers import projects as _projects

                    ctx = AgentContext.get(entry)
                    raw = ctx.get_data("project") if ctx else None
                    if _iso_ref(raw):
                        _projects.deactivate_project(entry)
                        out["contexts"].append(entry)
                except Exception:
                    pass
                continue
            try:
                d = json.loads(text)
                hit = False
                for holder_key in ("data", "output_data"):
                    holder = d.get(holder_key)
                    if isinstance(holder, dict) and _iso_ref(holder.get("project")):
                        holder["project"] = None
                        hit = True
                if hit:
                    tmp = cj + ".a0wt-tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(d, f)
                    os.replace(tmp, cj)
                    out["contexts"].append(entry)
            except Exception:
                pass
    tj = _tasks_json_path()
    if tj and os.path.isfile(tj):
        try:
            with open(tj, encoding="utf-8") as f:
                text = f.read()
            if _ISO_PREFIX in text:
                d = json.loads(text)
                tasks = d.get("tasks") if isinstance(d, dict) else d
                cleared: list[str] = []
                if isinstance(tasks, list):
                    for t in tasks:
                        if isinstance(t, dict) and _iso_ref(t.get("project_name")):
                            t["project_name"] = None
                            t["project_color"] = None
                            cleared.append(str(t.get("name") or t.get("uuid") or "?"))
                if cleared:
                    tmp = tj + ".a0wt-tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(d, f, indent=2)
                    os.replace(tmp, tj)
                    out["tasks"] = cleared
        except Exception:
            pass
    return out


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
    """One maintenance pass: sweep stranded folders + stale iso refs (always); rebuild or tear
    down the name index per the toggle; record everything in the durable marker."""
    swept: list[str] = []
    iso: dict = {"contexts": [], "tasks": []}
    links: int | None = None
    try:
        swept = sweep_orphans()
        if swept:
            _log(f"swept {len(swept)} stranded chat folder(s): {swept}")
    except Exception as e:
        _log(f"orphan sweep failed (non-fatal): {e}")
    try:
        iso = sweep_stale_iso_refs()
        if iso.get("contexts") or iso.get("tasks"):
            _log(f"cleared stale isolation project refs — contexts: {iso['contexts']} tasks: {iso['tasks']}")
    except Exception as e:
        _log(f"iso-ref sweep failed (non-fatal): {e}")
    try:
        if enable_name_index:
            links = rebuild_name_index()
        else:
            remove_name_index()
    except Exception as e:
        _log(f"name index failed (non-fatal): {e}")
    write_marker(
        sets={
            "last_run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "orphans_removed_last": swept,
            "iso_cleared_last": iso,
            "name_index_links": links,
        },
        increments={
            "runs_total": 1,
            "orphans_removed_total": len(swept),
            "iso_contexts_cleared_total": len(iso.get("contexts") or []),
            "iso_tasks_cleared_total": len(iso.get("tasks") or []),
        },
    )
