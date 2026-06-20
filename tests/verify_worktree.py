"""Deterministic test of the a0_worktree TOOL/engine core (helpers/worktree.py) against a real
throwaway git repo — stdlib only, no A0 install, no running container.

The v1.0 engine (create / remove / list_owned / cleanup_all_owned / ownership-marker gating /
auto-commit-on-teardown / branch preserve-vs-delete) had no automated test; only the isolation
wrap is covered (tests/verify_isolation.py). This fills that gap.

How it works: A0's `helpers.projects` and `helpers.files` surfaces are MOCKED with tiny in-memory
shims backed by a real temp directory tree (so worktree paths, the .a0proj meta dir, and the
ownership marker all live on a real filesystem). The REAL helpers/worktree.py is then imported by
file path and exercised. `git` must be on PATH (it is on the host).

Run:  python tests/verify_worktree.py
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import types
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN_ROOT = os.path.dirname(HERE)
WORKTREE_PY = os.path.join(PLUGIN_ROOT, "helpers", "worktree.py")

PASS = True


def check(label, cond):
    global PASS
    print(("PASS " if cond else "FAIL ") + label)
    PASS = PASS and cond


def _git(args, cwd=None, check=True):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


# ------------------------------------------------------------------------------------------------
# mock helpers.projects + helpers.files backed by a real temp tree
# ------------------------------------------------------------------------------------------------
def _install_mocks(root: str):
    """Create fake `helpers`, `helpers.projects`, `helpers.files` modules in sys.modules.

    Layout mirrors A0: projects live under <root>/usr/projects/<name>, the meta dir is
    <project>/.a0proj. activate_project records the last activation so the test can assert it.
    """
    projects_parent = os.path.join(root, "usr", "projects")
    os.makedirs(projects_parent, exist_ok=True)

    state = {"activated": [], "headers": {}, "deleted": []}

    # --- helpers.files ---
    files_mod = types.ModuleType("helpers.files")

    def create_dir(path):
        os.makedirs(path, exist_ok=True)
        return path

    files_mod.create_dir = create_dir

    # --- helpers.projects ---
    projects_mod = types.ModuleType("helpers.projects")

    def get_projects_parent_folder():
        return projects_parent

    def get_project_folder(name):
        return os.path.join(projects_parent, name)

    def get_project_meta(name, *sub):
        return os.path.join(get_project_folder(name), ".a0proj", *sub)

    def create_project_meta_folders(name):
        os.makedirs(get_project_meta(name), exist_ok=True)

    def _normalizeBasicData(data):
        return {
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "instructions": data.get("instructions", ""),
            "color": data.get("color", ""),
            "git_url": data.get("git_url", ""),
            "file_structure": data.get("file_structure", {"enabled": True}),
        }

    def save_project_header(name, data):
        state["headers"][name] = data

    def delete_project(name):
        # A0 deletes the project DIR; the engine then rmtrees the target too (idempotent).
        state["deleted"].append(name)
        shutil.rmtree(get_project_folder(name), ignore_errors=True)
        return name

    def activate_project(ctx_id, name):
        state["activated"].append((ctx_id, name))

    def clone_git_project(name, url, token, data):
        # Not exercised by the core tests (no remote); present so resolve_source imports cleanly.
        raise RuntimeError("clone not used in this test")

    projects_mod.get_projects_parent_folder = get_projects_parent_folder
    projects_mod.get_project_folder = get_project_folder
    projects_mod.get_project_meta = get_project_meta
    projects_mod.create_project_meta_folders = create_project_meta_folders
    projects_mod._normalizeBasicData = _normalizeBasicData
    projects_mod.save_project_header = save_project_header
    projects_mod.delete_project = delete_project
    projects_mod.activate_project = activate_project
    projects_mod.clone_git_project = clone_git_project

    # --- helpers package ---
    helpers_pkg = types.ModuleType("helpers")
    helpers_pkg.__path__ = []  # mark as a package
    helpers_pkg.projects = projects_mod
    helpers_pkg.files = files_mod

    sys.modules["helpers"] = helpers_pkg
    sys.modules["helpers.projects"] = projects_mod
    sys.modules["helpers.files"] = files_mod
    return state


def _load_worktree():
    spec = importlib.util.spec_from_file_location("a0wt_worktree_under_test", WORKTREE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_source_repo(root: str) -> str:
    """A real git repo with one commit to branch from."""
    repo = os.path.join(root, "src_repo")
    os.makedirs(repo)
    _git(["init", "-q", "-b", "main"], cwd=repo)
    _git(["config", "user.email", "t@t.local"], cwd=repo)
    _git(["config", "user.name", "tester"], cwd=repo)
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("hello\n")
    _git(["add", "-A"], cwd=repo)
    _git(["commit", "-q", "-m", "init"], cwd=repo)
    return repo


# ------------------------------------------------------------------------------------------------
# the tests
# ------------------------------------------------------------------------------------------------
def main():
    if shutil.which("git") is None:
        print("FAIL git not found on PATH — cannot run worktree engine test")
        return 1

    root = tempfile.mkdtemp(prefix="a0wt_test_")
    try:
        state = _install_mocks(root)
        wt = _load_worktree()
        repo = _make_source_repo(root)

        # --- create: new branch ---
        key1 = "wt_aaaa1111"
        name = wt.create(repo, "wt/feature-x", key1, ctx_id="ctx1")
        check("create returns the key as project name", name == key1)
        target1 = os.path.join(root, "usr", "projects", key1)
        check("create: worktree checkout dir exists", os.path.isdir(target1))
        check("create: checked-out README present", os.path.isfile(os.path.join(target1, "README.md")))
        br = _git(["-C", repo, "branch", "--list", "wt/feature-x"]).stdout
        check("create: new branch created in source repo", "wt/feature-x" in br)
        check("create: ownership marker written", wt._has_marker(key1))
        m = wt._read_marker(key1)
        check("marker carries OWNER + repo_path + branch", m is not None and m["owner"] == wt.OWNER
              and m["repo_path"] == repo and m["branch"] == "wt/feature-x")

        # --- create on an EXISTING branch (branch_exists path) ---
        _git(["-C", repo, "branch", "preexisting"], cwd=None)
        key2 = "wt_bbbb2222"
        wt.create(repo, "preexisting", key2, ctx_id="ctx1")
        check("create: existing-branch path produces a checkout", os.path.isdir(os.path.join(root, "usr", "projects", key2)))

        # --- create: path-collision fails safe (never overwrites) ---
        collided = False
        try:
            wt.create(repo, "wt/another", key1)  # key1 dir already exists
        except FileExistsError:
            collided = True
        check("create: existing path -> FileExistsError (no overwrite)", collided)

        # --- list_owned ---
        owned = wt.list_owned()
        keys = {o["key"] for o in owned}
        check("list_owned lists both managed worktrees", key1 in keys and key2 in keys)

        # --- gating: a NON-owned dir under projects/ is ignored ---
        foreign = os.path.join(root, "usr", "projects", "not_ours")
        os.makedirs(foreign)
        check("list_owned ignores a dir without our marker",
              "not_ours" not in {o["key"] for o in wt.list_owned()})
        check("remove() refuses a key we don't own (no marker)", wt.remove("not_ours") is False)
        check("remove() of a nonexistent key returns False", wt.remove("wt_doesnotexist") is False)
        check("foreign dir left untouched", os.path.isdir(foreign))

        # --- auto-commit-on-teardown: uncommitted work is saved to the branch, branch kept ---
        with open(os.path.join(target1, "newfile.txt"), "w") as f:
            f.write("uncommitted work\n")
        head_before = _git(["-C", repo, "rev-parse", "wt/feature-x"]).stdout.strip()
        ok = wt.remove(key1, delete_branch=False)
        check("remove(delete_branch=False) returns True", ok)
        check("remove: checkout dir gone", not os.path.isdir(target1))
        # branch survives
        still = _git(["-C", repo, "branch", "--list", "wt/feature-x"]).stdout
        check("remove: branch preserved by default", "wt/feature-x" in still)
        head_after = _git(["-C", repo, "rev-parse", "wt/feature-x"]).stdout.strip()
        check("remove: uncommitted work auto-committed (HEAD advanced)", head_after != head_before)
        # the auto-commit message + file are on the branch
        show = _git(["-C", repo, "log", "-1", "--name-only", "--format=%s", "wt/feature-x"]).stdout
        check("remove: auto-commit message + newfile on the branch",
              "auto-saved on teardown" in show and "newfile.txt" in show)
        check("remove: marker gone after teardown", not wt._has_marker(key1))

        # --- branch DELETE path: delete_branch=True discards the branch ---
        ok2 = wt.remove(key2, delete_branch=True)
        check("remove(delete_branch=True) returns True", ok2)
        gone = _git(["-C", repo, "branch", "--list", "preexisting"]).stdout.strip()
        check("remove: branch deleted when delete_branch=True", gone == "")

        # --- tool_create: resolve local path + activate on the context ---
        info = wt.tool_create(repo, branch=None, ctx_id="ctxZ")
        check("tool_create returns project/branch/path/repo", all(k in info for k in ("project", "branch", "path", "repo")))
        check("tool_create: default branch is wt/<key>", info["branch"] == "wt/" + info["project"])
        check("tool_create: checkout exists", os.path.isdir(info["path"]))
        check("tool_create: activated the project on the context", ("ctxZ", info["project"]) in state["activated"])

        # --- cleanup_all_owned: reclaims remaining owned checkouts, foreign untouched ---
        before = len(wt.list_owned())
        check("one owned worktree remains before cleanup", before == 1)
        n = wt.cleanup_all_owned()
        check("cleanup_all_owned reclaimed the remaining owned checkout(s)", n == before)
        check("cleanup_all_owned: no owned worktrees remain", wt.list_owned() == [])
        check("cleanup_all_owned: foreign dir still untouched", os.path.isdir(foreign))

        # --- resolve_source rejects a non-repo path ---
        bad = False
        try:
            wt.resolve_source(os.path.join(root, "usr"))  # has a separator, not a git repo
        except ValueError:
            bad = True
        check("resolve_source: non-git path -> ValueError", bad)

        print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
        return 0 if PASS else 1
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
