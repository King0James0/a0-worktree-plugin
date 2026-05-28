"""Framework runtime hooks (run in /opt/venv-a0), called by the plugin installer/uninstaller."""


def install():
    """Called once after the plugin is placed — set things up without waiting for a restart."""
    from usr.plugins.a0_worktree.helpers import setup

    setup.ensure()


def uninstall():
    """Called before the plugin dir is deleted — reverse out-of-tree changes."""
    from usr.plugins.a0_worktree.helpers import setup

    setup.cleanup()
