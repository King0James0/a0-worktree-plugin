# AGENTS.md — operating contract for `a0_worktree`

You are working on an Agent Zero plugin that hands the agent an isolated **git worktree + branch**
of a repo (as a real A0 project) and, optionally, gives every chat its own working directory by
**wrapping A0's project-path resolvers at runtime**. A mistake here destroys the user's committed
work, blows away a worktree the plugin doesn't own, leaks a git token, or silently breaks every
chat's code execution. Follow these rules exactly. They are not suggestions.

## What this plugin is
A self-contained A0 plugin (`a0_worktree`). It installs NOTHING — it uses `git` (already present)
and A0's project system. Two surfaces: (1) the **`worktree` tool** (`tools/worktree.py` → engine in
`helpers/worktree.py`) that does `create`/`remove`/`list` of git worktrees registered as A0
projects, and is the **authoritative backend A0 Swarm's `isolated` mode delegates to** via the
versioned `helpers/contract.py`; (2) opt-in **per-chat workdir isolation** (`helpers/isolation.py`)
that resolves a flagged chat's workdir to `usr/chats/<chat_id>/workdir`. Publishable, MIT, uninstall-clean.

## HARD INVARIANTS — never violate
1. **ONLY ever touch a worktree the plugin OWNS.** Every worktree we create writes an ownership
   marker `.a0_worktree_owner.json` (`helpers/worktree.py` `_write_marker`). `remove()` and
   `cleanup_all_owned()` MUST check `_read_marker(key)` first and return `False`/skip if it is not
   ours. NEVER enumerate-and-remove "all worktrees"; NEVER `shutil.rmtree` a path before the marker
   check passes. The plugin must coexist with manual `git worktree` use and other tools.
2. **Branches (and their commits) are sacred — preserve by default.** `remove(delete_branch=False)`
   FIRST auto-commits any uncommitted changes onto the branch, then tears down only the CHECKOUT.
   The branch is deleted ONLY on an explicit `delete_branch=True`. The contract entry point
   `remove_worktree(key)` NEVER deletes a branch (swarm subs run unwatched — their work must survive).
   `cleanup()` on uninstall reclaims checkouts but preserves branches. Losing committed work is unrecoverable.
3. **NEVER overwrite an existing directory.** `create()` raises `FileExistsError` if the target
   `usr/projects/<key>` already exists; `tool_create` retries with a fresh `_new_key()` (bounded 3).
   Never `git worktree add` over, or write into, a path that exists — that clobbers another worktree/project.
4. **The isolation wrap is FAIL-SAFE to A0's default in every path.** `helpers/isolation.py` wraps
   three `helpers.projects` functions; EVERY wrapper falls straight through to the stashed original
   (`_orig`) on any exception. An explicit project/worktree ALWAYS wins — isolation only fills the
   empty case. On any error, a future A0 rename, or the toggle OFF, behaviour reverts to the shared
   `usr/workdir`. Nothing this plugin does may break code execution for a non-isolated chat.
5. **Constrain `chat_id` before it becomes a filesystem path.** `_chat_workdir` / the synthetic
   `_ISO_PREFIX` path MUST match `_SAFE_ID = ^[A-Za-z0-9_-]{1,128}$` before building
   `usr/chats/<id>/workdir`. Never interpolate an unvalidated context id into a path (traversal).
   The synthetic project name is in-memory only — it must NEVER be persisted (no project list/sidebar leak).
6. **The git token is read at call time, never stored.** `_secret()` loads from A0 Secrets by the
   `git_token_secret` config name (default `GITHUB_TOKEN`), used ONLY to clone a PRIVATE remote URL.
   Never log it, never write it to the marker/header/meta, never embed it in a shipped file.
7. **The contract surface (`helpers/contract.py`) is a frozen API.** `create_worktree` /
   `remove_worktree` / `CONTRACT_VERSION` are what other plugins pin to. Keep it small and
   backward-compatible; bump `CONTRACT_VERSION` ONLY for a breaking change. Don't rename or
   re-signature these without a version bump.

## Build discipline
- **Framework-agnostic where it can be; one A0 seam per surface.** `helpers/worktree.py` and
  `helpers/isolation.py` touch A0 (`helpers.projects`, `helpers.files`, `helpers.settings`,
  `helpers.secrets`) by necessity, but isolate those imports and keep every framework call inside a
  try/except. Pure helpers stay stdlib-only.
- **Per change:** `py_compile` every `.py` via `/opt/venv-a0/bin/python -m py_compile` → run the
  `tests/` (`drift_check.py` config-parity + `verify_worktree.py` / `verify_isolation.py` /
  `verify_installed.py`) → keep `default_config.yaml` ↔ `webui/config.html` keys in sync (drift 0/0).
  Bump `plugin.yaml` `version` on an increment.
- **Keep THIS file current.** Update this AGENTS.md in the SAME change whenever you alter a HARD INVARIANT, a cited path/seam/A0 mechanic, or what this plugin is — a stale contract MISLEADS (worse than none). Routine fixes/features that don't change the contract don't touch it.
- **Validate in a THROWAWAY, never live-install.** Snapshot/commit the instance into an isolated
  container; never wrap resolvers on or create worktrees against the live store. Verify the config
  screen renders in a real browser. The maintainer installs the built artifact via the UX.
- **Opsec (public repo):** no secrets, IPs, internal hostnames, personal email, or local paths in
  shipped files. `CLAUDE.md` + `.claude/` are dev-only and gitignored. Commits: single human author,
  GitHub no-reply email (`King0James0@users.noreply.github.com`), NO AI / `Co-Authored-By` trailers.

## Knowledge map (one source of truth each — never duplicate)
- **What it does + how to drive it:** `README.md` (worktree tool, swarm integration, per-chat isolation).
- **Defaults + config keys:** `default_config.yaml` (kept in lockstep with `webui/config.html`).
- **Agent-facing process:** `prompts/agent.system.tool.worktree.md` + `skills/worktree-isolation/SKILL.md`
  (when to use it, and the ask-the-user-about-the-branch workflow).
- **The delegation API:** `helpers/contract.py` (the docstring is the spec swarm pins to).
- (No `ARCHITECTURE.md`/`BUILD_SPEC.md` in this repo — the source docstrings carry the rationale.)

## Verified A0 mechanics (don't re-derive — confirm against the LIVE instance; versions move constantly)
- Lifecycle: `hooks.py` `install`/`uninstall`/`save_plugin_config` + the `startup_migration/_50_…`
  extension both call `setup.ensure()`, which (re)installs the isolation wrap every boot.
  `save_plugin_config` runs BEFORE the new config is written — reconcile straight from the incoming
  `settings` dict so the toggle takes effect with no restart.
- `plugins.get_plugin_config(name)` returns the saved `config.json` **OR** defaults — NEVER merged.
- Isolation hooks A0 internals: `helpers.projects.get_context_project_name` / `get_project_folder` /
  `load_basic_project_data` are monkey-wrapped (stashed in `_orig`). Re-verify these names exist on
  every A0 upgrade; the wrappers already fail safe if they don't.
- Worktree registration uses `helpers.projects` (`get_project_folder`, `create_project_meta_folders`,
  `save_project_header`, `activate_project`, `clone_git_project`, `delete_project`) — confirm these
  signatures against the live instance before relying on them.
