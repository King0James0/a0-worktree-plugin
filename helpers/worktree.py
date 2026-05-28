"""Core worktree engine for a0_worktree (framework runtime, /opt/venv-a0).

Gives a context its own git worktree + branch of a repo, registered as an A0 project so the
agent's code-exec cwd follows into it. Used two ways:

  * the `worktree` tool (interactive / agent-driven) -> tool_create / remove / list_owned
  * the pinned contract (helpers/contract.py) that A0 Swarm's isolated mode delegates to
    -> create(repo_path, branch, key) / remove(key)

Good-neighbor design: every worktree we make carries our ownership marker; we ONLY ever act on
worktrees carrying it (never enumerate-and-remove "all worktrees"), create at unique paths and
fail safe on collision, and never delete a branch unless explicitly told to (work is preserved).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid

from helpers import projects, files

OWNER = "a0_worktree"
MARKER_NAME = ".a0_worktree_owner.json"  # written into the worktree project's .a0proj meta dir


# ------------------------------------------------------------------------------------------------
# small utilities
# ------------------------------------------------------------------------------------------------
def _git(args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({r.returncode}): {r.stderr.strip()[:300]}")
    return r


def _is_git_repo(path: str) -> bool:
    if not path or not os.path.isdir(path):
        return False
    return _git(["-C", path, "rev-parse", "--is-inside-work-tree"], check=False).returncode == 0


def _new_key() -> str:
    return f"wt_{uuid.uuid4().hex[:8]}"


def _looks_like_url(s: str) -> bool:
    s = s.lower()
    return s.startswith(("http://", "https://", "ssh://", "git@")) or s.endswith(".git")


def _repo_name_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return "".join(c for c in tail if c.isalnum() or c in "._-") or "repo"


def _secret(key: str | None) -> str | None:
    if not key:
        return None
    try:
        from helpers.secrets import get_default_secrets_manager

        return (get_default_secrets_manager().load_secrets() or {}).get(key) or None
    except Exception:
        return None


# ------------------------------------------------------------------------------------------------
# ownership marker (good-neighbor: only ever touch what carries OUR marker)
# ------------------------------------------------------------------------------------------------
def _marker_path(key: str) -> str:
    return os.path.join(projects.get_project_meta(key), MARKER_NAME)


def _write_marker(key, repo_path, branch, ctx_id=None):
    meta = projects.get_project_meta(key)
    files.create_dir(meta)
    with open(_marker_path(key), "w") as f:
        json.dump(
            {"owner": OWNER, "key": key, "repo_path": repo_path, "branch": branch,
             "ctx_id": ctx_id, "created": time.time()},
            f,
        )


def _read_marker(key):
    try:
        with open(_marker_path(key)) as f:
            d = json.load(f)
        return d if d.get("owner") == OWNER else None
    except Exception:
        return None


def _has_marker(key) -> bool:
    return _read_marker(key) is not None


# ------------------------------------------------------------------------------------------------
# source resolution: project name | local git path | remote URL (clone as a project)
# ------------------------------------------------------------------------------------------------
def resolve_source(source: str, token_secret: str | None = None) -> str:
    """Return a local repo path to branch from. Accepts an A0 git-project name, a local git-repo
    path, or a remote URL (cloned as a normal A0 git project first, then reused)."""
    source = (source or "").strip()
    if not source:
        raise ValueError("no source given")

    if _looks_like_url(source):
        name = _repo_name_from_url(source)
        token = _secret(token_secret) or ""
        actual = projects.clone_git_project(name, source, token, {"title": name})
        return projects.get_project_folder(actual)

    # explicit path (has a separator) -> treat as a local repo path
    if os.path.isabs(source) or "/" in source or "\\" in source:
        if _is_git_repo(source):
            return os.path.abspath(source)
        raise ValueError(f"path is not a git repo: {source}")

    # bare name -> an existing A0 git project
    proj_folder = projects.get_project_folder(source)
    if _is_git_repo(proj_folder):
        return proj_folder
    raise ValueError(f"'{source}' is not a known A0 git project, a git-repo path, or a git URL")


# ------------------------------------------------------------------------------------------------
# create / remove / list  (create + remove are the pinned-contract entry points)
# ------------------------------------------------------------------------------------------------
def create(repo_path: str, branch: str, key: str, ctx_id: str | None = None) -> str:
    """Add a worktree of repo_path on `branch` at usr/projects/<key>, register it as an A0 project,
    mark ownership, and return the project name (== key). Raises FileExistsError on path collision
    (the caller should retry with a fresh key — we NEVER overwrite an existing dir)."""
    target = projects.get_project_folder(key)
    if os.path.exists(target):
        raise FileExistsError(target)

    branch_exists = _git(
        ["-C", repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], check=False
    ).returncode == 0
    add = ["-C", repo_path, "worktree", "add"]
    add += [target, branch] if branch_exists else ["-b", branch, target]
    r = _git(add, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git worktree add failed: {r.stderr.strip()[:300]}")

    # keep our project meta out of the worktree's git status
    try:
        ex = _git(["-C", target, "rev-parse", "--git-path", "info/exclude"]).stdout.strip()
        ex_abs = ex if os.path.isabs(ex) else os.path.join(target, ex)
        with open(ex_abs, "a") as f:
            f.write("\n.a0proj/\n")
    except Exception:
        pass

    projects.create_project_meta_folders(key)
    projects.save_project_header(key, projects._normalizeBasicData({"title": f"worktree {key}"}))
    _write_marker(key, repo_path, branch, ctx_id)
    return key


def remove(key: str, delete_branch: bool = False) -> bool:
    """Remove the worktree CHECKOUT for `key`. By default the branch (and its commits) are kept —
    any uncommitted changes are auto-committed to the branch first so no work is lost. Pass
    delete_branch=True to also delete the branch (discard the work). Only acts if we own `key`."""
    marker = _read_marker(key)
    if marker is None:
        return False  # not ours -> leave it alone
    target = projects.get_project_folder(key)
    repo_path = marker.get("repo_path")
    branch = marker.get("branch")

    if not delete_branch:
        # auto-save any uncommitted work onto the branch so nothing is lost
        try:
            if os.path.isdir(target) and _git(["-C", target, "status", "--porcelain"], check=False).stdout.strip():
                _git(["-C", target, "add", "-A"], check=False)
                _git(["-C", target, "-c", "user.email=a0@worktree.local", "-c", "user.name=a0_worktree",
                      "commit", "-m", "a0_worktree: auto-saved on teardown", "-q"], check=False)
        except Exception:
            pass

    try:
        if repo_path and os.path.isdir(repo_path):
            _git(["-C", repo_path, "worktree", "remove", "--force", target], check=False)
            _git(["-C", repo_path, "worktree", "prune"], check=False)
    except Exception:
        pass

    if delete_branch and repo_path and branch:
        try:
            _git(["-C", repo_path, "branch", "-D", branch], check=False)
        except Exception:
            pass

    try:
        projects.delete_project(key)
    except Exception:
        pass
    shutil.rmtree(target, ignore_errors=True)  # only ours — marker was checked above
    return True


def list_owned() -> list[dict]:
    out = []
    parent = projects.get_projects_parent_folder()
    if os.path.isdir(parent):
        for name in sorted(os.listdir(parent)):
            m = _read_marker(name)
            if m:
                out.append({"key": name, "branch": m.get("branch"), "repo": m.get("repo_path")})
    return out


def cleanup_all_owned() -> int:
    """Reclaim every worktree checkout we own (keeping branches). Used on uninstall."""
    count = 0
    parent = projects.get_projects_parent_folder()
    if not os.path.isdir(parent):
        return 0
    for name in list(os.listdir(parent)):
        if _has_marker(name) and remove(name, delete_branch=False):
            count += 1
    return count


# ------------------------------------------------------------------------------------------------
# tool entry point (interactive): resolve a source, make a worktree, activate it on the context
# ------------------------------------------------------------------------------------------------
def tool_create(source: str, branch: str | None = None, ctx_id: str | None = None,
                token_secret: str | None = None) -> dict:
    repo_path = resolve_source(source, token_secret)
    for _ in range(3):  # retry only on (rare) path/key collision — never overwrite
        key = _new_key()
        b = branch or f"wt/{key}"
        try:
            name = create(repo_path, b, key, ctx_id=ctx_id)
        except FileExistsError:
            continue
        if ctx_id:
            try:
                projects.activate_project(ctx_id, name)
            except Exception:
                pass
        return {"project": name, "branch": b, "path": projects.get_project_folder(name), "repo": repo_path}
    raise RuntimeError("could not allocate a unique worktree key")
