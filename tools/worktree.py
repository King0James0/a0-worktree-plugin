from __future__ import annotations

import logging

from helpers import plugins
from helpers.tool import Tool, Response
from usr.plugins.a0_worktree.helpers import worktree

logger = logging.getLogger(__name__)


def _load_cfg(agent) -> dict:
    try:
        return plugins.get_plugin_config("a0_worktree", agent=agent) or {}
    except Exception:
        return {}


def _as_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("1", "true", "yes", "y")


class Worktree(Tool):
    async def execute(self, action: str | None = None, repo: str | None = None,
                      branch: str | None = None, key: str | None = None,
                      delete_branch=False, **kwargs):
        action = (action or "").strip().lower()
        cfg = _load_cfg(self.agent)
        # Token secret name is a code constant (no config field) — honour a legacy saved key if present.
        token_secret = cfg.get("git_token_secret") or worktree.DEFAULT_TOKEN_SECRET
        ctx_id = self.agent.context.id

        if action == "create":
            if not repo:
                return Response(
                    message="worktree create needs `repo` — an A0 git-project name, a local git-repo path, or a git URL.",
                    break_loop=False,
                )
            try:
                info = worktree.tool_create(repo, branch=branch, ctx_id=ctx_id, token_secret=token_secret)
            except Exception as e:
                return Response(message=f"Could not create worktree from `{repo}`: {e}", break_loop=False)
            return Response(
                message=(
                    f"Created an isolated worktree and made it your active project:\n"
                    f"- project: `{info['project']}`\n"
                    f"- branch: `{info['branch']}`\n"
                    f"- path: `{info['path']}`\n"
                    f"Your shell / code_execution now runs inside it. Do your work there. When the "
                    f"task is done, ASK the user whether to keep the branch (preserve the work) or "
                    f"delete it, then call this tool with action=remove key=`{info['project']}` "
                    f"(delete_branch=true only if the user chose to discard)."
                ),
                break_loop=False,
            )

        if action == "remove":
            if not key:
                return Response(
                    message="worktree remove needs `key` (the project name returned by create).",
                    break_loop=False,
                )
            db = _as_bool(delete_branch)
            ok = worktree.remove(key, delete_branch=db)
            if not ok:
                return Response(
                    message=f"No a0_worktree-managed worktree named `{key}` (already gone, or not one I created).",
                    break_loop=False,
                )
            fate = "deleted (work discarded)" if db else "kept (work preserved for merge/review)"
            return Response(message=f"Removed worktree `{key}`. Branch {fate}.", break_loop=False)

        if action == "list":
            items = worktree.list_owned()
            if not items:
                return Response(message="No active a0_worktree worktrees.", break_loop=False)
            lines = [f"- `{i['key']}` — branch `{i['branch']}` (from `{i['repo']}`)" for i in items]
            return Response(message="Active worktrees:\n" + "\n".join(lines), break_loop=False)

        return Response(
            message="worktree: `action` must be one of create | remove | list.",
            break_loop=False,
        )

    def get_log_object(self):
        return self.agent.context.log.log(
            type="tool",
            heading=f"icon://account_tree {self.agent.agent_name}: Worktree",
            content="",
            kvps=self.args,
        )
