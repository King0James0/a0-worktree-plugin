"""Framework runtime hooks (run in /opt/venv-a0), called by the plugin installer/uninstaller."""


def install():
    """Called once after the plugin is placed — FIRST restore config.json from the runtime-dir
    stash if an update wiped it (v1.3.1 config-survives-upgrade; the 2026-07-20 install reverted
    both toggles + tore down the by-name farm), then set things up without waiting for a restart —
    including rebuilding the farm when the restored config says so."""
    from usr.plugins.a0_worktree.helpers import maintenance, setup

    restored = None
    try:
        restored = maintenance.restore_config_stash()
    except Exception:
        pass
    setup.ensure()
    try:
        if isinstance(restored, dict) and restored.get("chat_name_index"):
            maintenance.rebuild_name_index()
    except Exception:
        pass


def uninstall():
    """Called before the plugin dir is deleted — stash config.json into the surviving runtime dir
    (the A0 UPDATE path is uninstall→install and deletes the plugin dir, config included), then
    reverse out-of-tree changes."""
    from usr.plugins.a0_worktree.helpers import maintenance, setup

    try:
        maintenance.stash_config()
    except Exception:
        pass
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
        # keep the runtime-dir stash current on every save (config-survives-upgrade, v1.3.1)
        from usr.plugins.a0_worktree.helpers import maintenance

        if isinstance(cfg, dict):
            maintenance.stash_config(cfg)
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
