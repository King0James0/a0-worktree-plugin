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

Two companion GUARDS (v1.3.0) keep the synthetic names from ever being persisted by OUTSIDE
writers: `projects.activate_project` refuses `_a0wt_iso_*` names (the task scheduler activates a
task's stored project onto its context each run), and `SchedulerTaskList.add_task` strips them
from new task records (the webui task-create modal defaults its project to the creating chat's
active project — for an isolated chat, our synthetic name). Plus fail-soft healing for state
poisoned before these guards existed: the name resolver IGNORES a persisted iso name (they are
never legitimately stored), and the folder resolver falls back to the SHARED workdir when an iso
path's chat is dead, so a dangling reference can never crash prompt-prep again.

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


def _default_workdir() -> str | None:
    """Absolute path of A0's SHARED default workdir — the stock behaviour for a chat with no
    project. Used as the fail-soft target when an isolation path can no longer exist (dead chat)."""
    try:
        from helpers import files

        wp = ""
        try:
            from helpers import settings as _settings

            wp = str((_settings.get_settings() or {}).get("workdir_path") or "")
        except Exception:
            wp = ""
        wp = wp or "usr/workdir"
        return wp if os.path.isabs(wp) else files.get_abs_path(wp)
    except Exception:
        return None


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

    # A previous incarnation of this module (before a plugin purge/reinstall) may have already
    # wrapped the resolvers. Wrapping AGAIN would stash the wrapper as "orig" — a double-wrap
    # whose uninstall restores a wrapper. The live closures keep working; just install the
    # sentinel-guarded companion guards and mark done.
    if getattr(getattr(projects, "get_context_project_name", None), "_a0wt_wrapper", False):
        _wrapped = True
        _install_activate_guard(projects)
        _install_task_guard()
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
            # A PERSISTED iso name is always illegitimate: isolation names are computed at read
            # time and never stored, so one can only come back from the original resolver if an
            # outside writer copied it onto the context (the task scheduler's activate_project
            # was one). It dangles once its chat dies — heal by treating it as "no project".
            if isinstance(real, str) and real.startswith(_ISO_PREFIX):
                real = None
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
                if path and os.path.isdir(path):
                    return path
                # Dead chat (folder gone, no live context — _chat_workdir declined to create it):
                # NEVER hand out a nonexistent path; downstream consumers (get_file_structure →
                # file_tree) raise on it and that exception kills prompt-prep for the whole
                # monologue. Fall back to the SHARED workdir — stock A0 behaviour for no-project.
                fallback = _default_workdir()
                if fallback:
                    return fallback
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
        for fn in (gcpn, gpf, lbpd):
            fn._a0wt_wrapper = True  # purge-survival sentinel (see the early-return above)
        projects.get_context_project_name = gcpn
        projects.get_project_folder = gpf
        projects.load_basic_project_data = lbpd
        _wrapped = True
        _log(f"isolation: per-chat workdir wrap installed (enabled={_enabled}).")
    except Exception as e:
        _log(f"isolation: failed to install wrap (non-fatal): {e}")
    _install_activate_guard(projects)
    _install_task_guard()


def strip_iso_project(task) -> bool:
    """Null an iso pseudo-project off a scheduler task object. True if it stripped anything.
    The strip logic lives here (not in the wrap closure) so tests can exercise it directly."""
    try:
        pn = getattr(task, "project_name", None)
        if isinstance(pn, str) and pn.startswith(_ISO_PREFIX):
            task.project_name = None
            task.project_color = None
            return True
    except Exception:
        pass
    return False


def _install_activate_guard(projects) -> None:
    """Wrap `projects.activate_project` to REFUSE iso pseudo-project names. Isolation names are
    internal, computed-at-read-time artifacts — persisting one onto any context (which is all
    activate_project does) is never legitimate and is exactly how the scheduled-task poisoning
    happened: the webui task-create modal captured the creating chat's active project and the
    scheduler re-activated it onto the task's context every run. Idempotent via sentinel."""
    try:
        cur = getattr(projects, "activate_project", None)
        if cur is None or getattr(cur, "_a0wt_wrapper", False):
            return
        _orig["ap"] = cur

        def ap(context_id, name, *a, **kw):
            try:
                if isinstance(name, str) and name.startswith(_ISO_PREFIX):
                    _log(f"refused activate_project({name!r}) — isolation pseudo-projects are internal and never persist")
                    return None
            except Exception:
                pass
            return _orig["ap"](context_id, name, *a, **kw)

        ap._a0wt_wrapper = True
        projects.activate_project = ap
    except Exception as e:
        _log(f"isolation: activate guard not installed (non-fatal): {e}")


def _install_task_guard() -> None:
    """Wrap `SchedulerTaskList.add_task` (the funnel every task-creation path passes through) to
    strip iso pseudo-projects off new task RECORDS — so `_a0wt_iso_*` can never be stamped onto a
    task again (the UI create modal defaults its project to the creating chat's active project,
    which for an isolated chat is our synthetic name). Fail-safe: on any miss, tasks flow
    through untouched. Idempotent via sentinel."""
    try:
        from helpers import task_scheduler as ts

        target = getattr(ts, "SchedulerTaskList", None)
        add = getattr(target, "add_task", None)
        if add is None or getattr(add, "_a0wt_wrapper", False):
            return
        _orig["add_task"] = add

        async def add_task(self, task, *a, **kw):
            try:
                if strip_iso_project(task):
                    _log(f"stripped isolation pseudo-project from new task {getattr(task, 'name', '?')!r}")
            except Exception:
                pass
            return await _orig["add_task"](self, task, *a, **kw)

        add_task._a0wt_wrapper = True
        target.add_task = add_task
    except Exception as e:
        _log(f"isolation: task guard not installed (non-fatal): {e}")


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
        if _orig.get("ap"):
            projects.activate_project = _orig["ap"]
    except Exception as e:
        _log(f"isolation: uninstall wrap failed (non-fatal): {e}")
    try:
        if _orig.get("add_task"):
            from helpers import task_scheduler as ts

            ts.SchedulerTaskList.add_task = _orig["add_task"]
    except Exception as e:
        _log(f"isolation: uninstall task guard failed (non-fatal): {e}")
    finally:
        _wrapped = False
