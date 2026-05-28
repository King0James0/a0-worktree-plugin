"""Stable, versioned API that other plugins delegate to when they need worktree isolation.

This is the authoritative-owner contract: when a0_worktree is installed, a consumer plugin (e.g.
A0 Swarm's `isolated` mode) probes for this exact module and calls these functions instead of
managing worktrees itself, so there is a single owner of worktree lifecycle. Keep this surface
small and backward-compatible; bump CONTRACT_VERSION only for breaking changes.

  create_worktree(repo_path, branch, key) -> project_name
      Make a worktree of repo_path on `branch` at usr/projects/<key>, register it as an A0
      project, and return its name. Non-interactive. The caller activates it on its own context.

  remove_worktree(key) -> None
      Tear down the worktree CHECKOUT for `key`. Idempotent and tolerant of already-gone. The
      branch (and its commits) are ALWAYS preserved — the caller's work must survive for merging.
      Any uncommitted changes are auto-committed to the branch first. Never deletes a branch.
"""

from __future__ import annotations

CONTRACT_VERSION = 1


def create_worktree(repo_path: str, branch: str, key: str) -> str:
    from usr.plugins.a0_worktree.helpers import worktree

    return worktree.create(repo_path, branch, key)


def remove_worktree(key: str) -> None:
    from usr.plugins.a0_worktree.helpers import worktree

    worktree.remove(key, delete_branch=False)
