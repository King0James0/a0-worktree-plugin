"""Framework runtime hooks (run in /opt/venv-a0), called by the plugin installer/uninstaller."""


def install():
    """Called once after the plugin is placed — set things up without waiting for a restart."""
    from usr.plugins.a0_worktree.helpers import setup

    setup.ensure()


def uninstall():
    """Called before the plugin dir is deleted — reverse out-of-tree changes."""
    from usr.plugins.a0_worktree.helpers import setup

    setup.cleanup()


def save_plugin_config(settings=None, default=None, **kwargs):
    """Apply the isolation toggle the moment it is saved in the UI (no restart). Called BEFORE the
    new config is written, so reconcile straight from the incoming settings. Must return settings."""
    cfg = settings if isinstance(settings, dict) else default
    try:
        from usr.plugins.a0_worktree.helpers import isolation

        isolation.install_wrap()          # ensure the wrap is in place (idempotent)
        isolation.refresh_enabled(cfg)    # flip on/off instantly from the incoming value
    except Exception:
        pass
    try:
        # Build or tear down the name-index farm the moment the toggle is saved — same instant
        # behaviour as the isolation toggle (don't wait for the next job-loop maintenance tick).
        from usr.plugins.a0_worktree.helpers import maintenance

        if isinstance(cfg, dict) and cfg.get("chat_name_index"):
            maintenance.rebuild_name_index()
        else:
            maintenance.remove_name_index()
    except Exception:
        pass
    return settings
