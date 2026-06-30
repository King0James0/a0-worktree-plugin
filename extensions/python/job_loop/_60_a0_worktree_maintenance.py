"""Throttled background maintenance for a0_worktree (orphan sweep + optional name index).

Runs on the framework job loop (~every 60s) but self-throttles to once per INTERVAL. Best-effort —
never raises into the loop. See helpers/maintenance.py for the actual jobs and why they're needed.
"""

from datetime import datetime, timedelta, timezone

from helpers.extension import Extension


class A0WorktreeMaintenance(Extension):
    _last_run: datetime | None = None
    INTERVAL = timedelta(minutes=10)

    async def execute(self, **kwargs):
        try:
            now = datetime.now(timezone.utc)
            cls = type(self)
            if cls._last_run and now - cls._last_run < cls.INTERVAL:
                return
            cls._last_run = now

            enable_name_index = False
            try:
                from helpers import plugins

                cfg = plugins.get_plugin_config("a0_worktree") or {}
                enable_name_index = bool(cfg.get("chat_name_index", False))
            except Exception:
                enable_name_index = False

            from usr.plugins.a0_worktree.helpers import maintenance

            maintenance.run(enable_name_index)
        except Exception:
            pass
