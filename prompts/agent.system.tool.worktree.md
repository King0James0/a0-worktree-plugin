### worktree
Work on a repository in an **isolated git worktree + branch** — a separate checkout that does not
touch the user's main working copy. The worktree is registered as an A0 project and **activated**,
so your shell / `code_execution_tool` immediately runs inside it. Use this when the user wants to
make changes safely, try an experiment they can throw away, fix something on a dedicated branch, or
work several branches of one repo without them colliding.

Args:
- `action` (string, required): `create` | `remove` | `list`.
- `repo` (string, for `create`): what to branch from — an existing A0 git **project name**, a local
  **git-repo path**, or a **git URL** (a URL is cloned as a project first, then reused).
- `branch` (string, optional for `create`): branch name to use/create. Omit to auto-name one.
- `key` (string, for `remove`): the `project` name returned by `create`.
- `delete_branch` (bool, optional for `remove`): `true` deletes the branch (discards the work);
  default `false` keeps the branch (and auto-saves any uncommitted changes to it).

Workflow: `create` → do the work in the activated worktree → when the task is done, **ask the user**
whether to keep the branch (for merge/review) or delete it, honoring any other instruction they give
(e.g. merge, push) → then `remove` with `delete_branch` set accordingly. Removing keeps the branch by
default so work is never lost.

Example:
~~~json
{
  "thoughts": ["I'll fix the bug on an isolated branch so the user's checkout is untouched."],
  "tool_name": "worktree",
  "tool_args": { "action": "create", "repo": "my-app", "branch": "fix-login" }
}
~~~
