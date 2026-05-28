---
name: worktree-isolation
description: Use when the user wants to work on a git repo in isolation — make changes safely without touching their main checkout, try a throwaway experiment, fix something on a dedicated branch, or work several branches of one repo in parallel. Triggers on phrases like "without messing up my repo", "on a separate branch", "try this safely", "in an isolated copy", "scratch/experiment branch". Drives the `worktree` tool.
---

# Isolated worktree workflow

Give the work its own git worktree + branch so the user's main checkout is never disturbed, then
clean up by asking the user what to do with the branch.

1. **Create** the worktree: call the `worktree` tool with `action=create`, `repo=<the repo>` (an A0
   git-project name, a local git-repo path, or a git URL), and optionally `branch=<name>` if the
   user named one (otherwise omit and let it auto-name). The worktree becomes your **active
   project**, so your shell / `code_execution_tool` now runs inside it automatically. Note the
   `project` (key) it returns — you need it to remove later.
2. **Do the work** in that worktree: edit, run, commit as needed. Everything stays on the worktree's
   branch; the user's main checkout is untouched.
3. **When the task is done, ASK the user what to do with the branch** — keep it (so they can merge /
   review the work) or delete it (discard). Honor any other instruction they give (e.g. "merge it
   into main", "push it", "rename the branch") before removing.
4. **Remove** the worktree: call `worktree` with `action=remove`, `key=<the project from step 1>`,
   and `delete_branch=true` ONLY if the user chose to discard. Default (`false`) keeps the branch and
   auto-saves any uncommitted changes to it.

Rules:
- Don't pick worktree paths yourself — the tool owns placement. Just pass `repo` (+ optional `branch`).
- Never `delete_branch=true` without the user explicitly choosing to discard the work.
- One repo can have many worktrees at once (each on its own branch) — fine for parallel branches.

Failure handling:
- "not a known A0 git project, a git-repo path, or a git URL" -> the `repo` value was wrong; ask the
  user for the project name / path / URL, or clone the remote first.
- A git URL clone fails for a private repo -> the git token isn't set; tell the user to add their git
  token to A0 Secrets (the key named by the plugin's `git_token_secret` setting, default `GITHUB_TOKEN`).
