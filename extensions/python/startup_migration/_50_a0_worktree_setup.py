from helpers.extension import Extension
from usr.plugins.a0_worktree.helpers import setup


class A0WorktreeSetup(Extension):
    """Runs once at framework startup. Re-ensures plugin setup on every boot."""

    def execute(self, **kwargs):
        setup.ensure()
