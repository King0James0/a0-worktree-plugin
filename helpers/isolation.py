"""Per-chat workdir isolation (opt-in, default OFF).

When the `isolate_chat_workdir` toggle is on, every chat that has NO explicit project gets its
own working directory at `usr/chats/<chat_id>/workdir` instead of the shared `usr/workdir`. The
chat's code execution, the file list the agent is shown, and saved office documents all resolve
there — consistently — because every one of those consumers asks A0's `helpers.projects` resolver
the same question ("does this context have a project?"). We answer it.

Mechanism: at boot we WRAP three `helpers.projects` functions so that, for a flagged chat, they
behave as if the chat had a project whose folder is the chat's own directory — without ever
creating a real project, writing to disk, or tagging the context. So nothing leaks into the
project list/selector or the sidebar, and real/explicit projects are completely untouched.

This is a deliberate, declared dependency on A0 framework internals (the same archetype as
a0_reranker wrapping a built-in). It is therefore FAIL-SAFE in every path: on any error, or if a
future A0 renames these functions, it falls straight through to A0's original behaviour (the
shared workdir) — isolation simply doesn't apply; nothing breaks. Re-verify on each A0 upgrade.
"""

from __future__ import annotations

import os
import re

PLUGIN_NAME = "a0_worktree"

# Synthetic project-name prefix. Never persisted; only ever returned in-memory from the wrapped
# resolver, so it cannot appear in the project list, the selector, or project_chat_view.
_ISO_PREFIX = "_a0wt_iso_"
# Chat ids are short tokens; constrain hard before using one to build a filesystem path.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")

# Module state. Originals are stashed once; the sentinel makes install/uninstall idempotent.
_wrapped = False
_orig = {}
_enabled = False


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[{PLUGIN_NAME}] {msg}")
    except Exception:
        print(f"[{PLUGIN_NAME}] {msg}")


def refresh_enabled(settings: dict | None = None) -> bool:
    """Re-read the toggle. Pass the incoming settings dict from the save hook for an instant
    update; otherwise read the saved plugin config. Defaults OFF on any failure (fail-safe)."""
    global _enabled
    try:
        if isinstance(settings, dict):
            cfg = settings
        else:
            from helpers import plugins

            cfg = plugins.get_plugin_config(PLUGIN_NAME) or {}
        _enabled = bool(cfg.get("isolate_chat_workdir", False))
    except Exception:
        _enabled = False
    return _enabled


def _context_is_live(chat_id: str) -> bool:
    """True if a live in-memory AgentContext owns this id. FAIL-SAFE to True when we can't tell, so a
    real chat is never denied its workdir — the guard only ever WITHHOLDS creation on a definite miss."""
    try:
        from agent import AgentContext

        return AgentContext.get(str(chat_id)) is not None
    except Exception:
        return True


def _chat_workdir(chat_id: str) -> str | None:
    """Absolute path to a chat's own workdir, created best-effort. None if the id is unsafe.

    Liveness guard: a stale code-execution shell can call this AFTER its chat was deleted (the chat
    folder is gone). Do NOT resurrect a dead chat's directory — re-creating it strands an orphan with
    no chat.json that nothing reaps (helpers/maintenance.py exists to sweep ones already stranded).
    Only create when the chat folder still exists (a real chat) OR a live context owns the id (a chat
    mid-creation, before its first save). On a definite miss, return the path WITHOUT creating it.
    """
    if not (isinstance(chat_id, str) and _SAFE_ID.match(chat_id)):
        return None
    try:
        from helpers import files

        chat_dir = files.get_abs_path("usr/chats", chat_id)
        path = files.get_abs_path("usr/chats", chat_id, "workdir")
        if not os.path.isdir(chat_dir) and not _context_is_live(chat_id):
            return path  # deleted chat / orphaned caller — return path but do NOT create it
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
        return path
    except Exception:
        return None


def _synthetic_basic_data() -> dict:
    """A minimal BasicProjectData for a synthetic isolation 'project'. Its file_structure mirrors
    the GLOBAL workdir_* settings so the agent's file-tree view of the isolated workdir behaves
    exactly as the normal shared workdir would (same depth/caps/gitignore)."""
    fs = {"enabled": True, "max_depth": 5, "max_files": 20,
          "max_folders": 20, "max_lines": 250, "gitignore": ""}
    try:
        from helpers import settings as _settings

        s = _settings.get_settings() or {}
        fs = {
            "enabled": True,
            "max_depth": int(s.get("workdir_max_depth", fs["max_depth"])),
            "max_files": int(s.get("workdir_max_files", fs["max_files"])),
            "max_folders": int(s.get("workdir_max_folders", fs["max_folders"])),
            "max_lines": int(s.get("workdir_max_lines", fs["max_lines"])),
            "gitignore": str(s.get("workdir_gitignore", fs["gitignore"])),
        }
    except Exception:
        pass
    return {"title": "", "description": "", "instructions": "",
            "color": "", "git_url": "", "file_structure": fs}


def install_wrap() -> None:
    """Idempotently wrap the three projects resolvers. Safe to call on every boot/install."""
    global _wrapped
    refresh_enabled()
    if _wrapped:
        return
    try:
        from helpers import projects
    except Exception as e:
        _log(f"isolation: helpers.projects unavailable — isolation disabled ({e})")
        return

    try:
        _orig["gcpn"] = projects.get_context_project_name
        _orig["gpf"] = projects.get_project_folder
        _orig["lbpd"] = projects.load_basic_project_data
    except Exception as e:
        _log(f"isolation: resolver functions not found — isolation disabled ({e})")
        return

    def gcpn(context, *a, **kw):
        # An explicit project / worktree ALWAYS wins; isolation only fills the empty case.
        try:
            real = _orig["gcpn"](context, *a, **kw)
            if real:
                return real
            if _enabled and context is not None:
                cid = getattr(context, "id", None)
                if cid and _SAFE_ID.match(str(cid)):
                    return _ISO_PREFIX + str(cid)
            return real
        except Exception:
            try:
                return _orig["gcpn"](context, *a, **kw)
            except Exception:
                return None

    def gpf(name, *a, **kw):
        try:
            if isinstance(name, str) and name.startswith(_ISO_PREFIX):
                path = _chat_workdir(name[len(_ISO_PREFIX):])
                if path:
                    return path
            return _orig["gpf"](name, *a, **kw)
        except Exception:
            return _orig["gpf"](name, *a, **kw)

    def lbpd(name, *a, **kw):
        try:
            if isinstance(name, str) and name.startswith(_ISO_PREFIX):
                return _synthetic_basic_data()
            return _orig["lbpd"](name, *a, **kw)
        except Exception:
            return _orig["lbpd"](name, *a, **kw)

    try:
        projects.get_context_project_name = gcpn
        projects.get_project_folder = gpf
        projects.load_basic_project_data = lbpd
        _wrapped = True
        _log(f"isolation: per-chat workdir wrap installed (enabled={_enabled}).")
    except Exception as e:
        _log(f"isolation: failed to install wrap (non-fatal): {e}")


def uninstall_wrap() -> None:
    """Restore A0's original resolvers. Idempotent; tolerant of already-restored."""
    global _wrapped
    if not _wrapped:
        return
    try:
        from helpers import projects

        if _orig.get("gcpn"):
            projects.get_context_project_name = _orig["gcpn"]
        if _orig.get("gpf"):
            projects.get_project_folder = _orig["gpf"]
        if _orig.get("lbpd"):
            projects.load_basic_project_data = _orig["lbpd"]
    except Exception as e:
        _log(f"isolation: uninstall wrap failed (non-fatal): {e}")
    finally:
        _wrapped = False
