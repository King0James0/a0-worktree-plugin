"""Plugin setup helpers (run in the Agent Zero framework runtime, /opt/venv-a0).

a0_worktree installs nothing on the system — it only uses `git` (already present) and A0's
project system. ensure() just verifies git and is otherwise a no-op; cleanup() reclaims the
worktree CHECKOUTS this plugin created (always preserving their branches). Best-effort: never raise.
"""

from __future__ import annotations

import shutil

PLUGIN_NAME = "a0_worktree"  # must match plugin.yaml `name` and the plugin folder name


def _log(msg: str) -> None:
    try:
        from helpers.print_style import PrintStyle

        PrintStyle(font_color="cyan").print(f"[{PLUGIN_NAME}] {msg}")
    except Exception:
        print(f"[{PLUGIN_NAME}] {msg}")


def ensure() -> None:
    """Idempotent, best-effort. a0_worktree has nothing to install; just confirm git is available."""
    try:
        if shutil.which("git") is None:
            _log("WARNING: git not found on PATH — a0_worktree needs git to create worktrees.")
    except Exception as e:
        _log(f"ensure() check failed (non-fatal): {e}")


def cleanup() -> None:
    """On uninstall, reclaim the worktree checkouts we created (branches are always preserved so
    no work is lost). Out-of-tree state lives only as worktrees under usr/projects/<key>, each
    carrying our ownership marker — we touch nothing else."""
    try:
        from usr.plugins.a0_worktree.helpers import worktree

        removed = worktree.cleanup_all_owned()
        _log(f"cleanup() — reclaimed {removed} worktree checkout(s); branches preserved.")
    except Exception as e:
        _log(f"cleanup() failed (non-fatal): {e}")
