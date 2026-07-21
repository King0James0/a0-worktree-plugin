# A0 Worktree

Give the agent an **isolated git worktree + branch** of a repo — its own checkout that never
touches your main working copy — as a normal A0 **project**, so the agent's working directory just
"moves into" it. Install nothing else: it uses `git` (already present) and A0's project system.

It's useful two ways: directly (the agent works a repo in isolation for you) and as the **worktree
backend that A0 Swarm's `isolated` mode delegates to** (see *Using with A0 Swarm* below).

## Support

If this plugin is useful to you, you can support the developer.

[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/king0james0) [![Solana](https://img.shields.io/badge/Solana-9945FF?style=for-the-badge&logo=solana&logoColor=white)](https://solscan.io/account/2ZJ2yA6NhM5usgdFRGWw89Z32fzw7Xgga3Eo56jQQiN6) [![Ethereum](https://img.shields.io/badge/Ethereum-3C3C3D?style=for-the-badge&logo=ethereum&logoColor=white)](https://etherscan.io/address/0xfF61681F907fA8DB39C1d23cbdbE89D24A94De17) [![Bitcoin](https://img.shields.io/badge/Bitcoin-F7931A?style=for-the-badge&logo=bitcoin&logoColor=white)](https://mempool.space/address/bc1qyr6x7kmxpy6ke0xutkxg90f30658fnr39h0d7r)

## What it adds

- A **`worktree` tool** the agent calls — `create` / `remove` / `list`.
- A **skill** (`worktree-isolation`) that triggers the agent to use it when a task calls for an
  isolated/branch checkout, and to ask you what to do with the branch when the work is done.

Nothing happens automatically — the agent uses it when you ask for isolated work.

## How it works

`create` makes a `git worktree` of a repo on its own branch, at `usr/projects/<key>`, and registers
it as an A0 project so the agent's `code_execution` cwd follows into it. Worktrees share the repo's
one `.git` (no full re-clone). Your edits/commits land on that worktree's branch; your main checkout
is untouched. `remove` tears down the **checkout** but, by default, **keeps the branch** (and
auto-commits any uncommitted changes to it first) so work is never lost — pass `delete_branch=true`
only to discard. The plugin only ever touches worktrees it created (each carries an ownership
marker), so it coexists safely with other worktree tools or manual `git worktree` use.

## Using it (you just ask)

You never run git yourself — you ask in chat and the agent drives the tool:

- *"In my `app` project, fix the login bug on a new branch `fix-auth` without touching my main
  checkout — leave the branch for me to review."*
- *"Try the risky dependency upgrade in an isolated copy and run the tests; if it breaks, throw it away."*
- *"Work on two approaches to this refactor side by side."*

When the task is done the agent asks whether to **keep** the branch (for merge/review), **delete** it,
or follow another instruction you give (merge it, push it, rename it…).

### What `create` accepts as the repo

- an existing A0 **git-project name** → branches off that project,
- a local **git-repo path**,
- a **git URL** → cloned as a normal A0 git project first (reusable for more worktrees), then branched.

Private remotes need a git token: set it in A0 Secrets under the key `GITHUB_TOKEN`. Public remotes
and local repos/projects need no token (so there's no setting for it).

## Using with A0 Swarm

If the [A0 Swarm](https://github.com/a0-community-plugins/a0_swarm) plugin is also installed, its
`subagent_workspace=isolated` mode hands each parallel subagent its own worktree so they can edit the
same repo without colliding — and it **delegates that to this plugin** when present (this plugin is
the authoritative owner of worktree lifecycle; swarm falls back to an inline worktree only when it's
absent). The integration uses a small versioned contract (`helpers/contract.py`:
`create_worktree(repo_path, branch, key)` / `remove_worktree(key)`).

The two paths differ in cleanup, by design:

- **Direct (this plugin, one worktree, human in the loop):** the agent **asks you** at the end —
  keep / delete / your-instruction.
- **Via swarm (many subs, no human watching each):** each sub's worktree checkout is torn down
  automatically when that sub finishes, but its **branch is always kept** (the work survives). Swarm
  surfaces each branch, and the orchestrator prompts you **once** about the whole batch (merge / keep
  / delete). `remove_worktree` never deletes a branch.

So installing this plugin **upgrades swarm's `isolated` engine**; it does not change swarm's `none`
or `inherit` modes, and `isolated` is never applied automatically — you opt in via swarm's setting.

## Per-chat workdir isolation (opt-in)

Separately from the worktree tool, this plugin can give **every chat its own working directory** so
chats stop sharing — and polluting — the one global `usr/workdir`. Turn on **Isolate each chat's
working directory** in the plugin settings (default **off**). While it's on, any chat that has no
explicit project gets its own folder at `usr/chats/<chat_id>/workdir`, and the chat's **code
execution**, the **file list shown to the agent**, and **saved office documents** all resolve there.
So one chat never sees another's scratch files, and a chat's files live with it — when the chat is
removed, its workdir goes too (no buildup of stale files).

It's a clean, reversible runtime behavior: it does **not** create real projects (nothing appears in
the project list/selector or in project-grouped sidebars), it leaves real projects and worktrees
completely untouched, and toggling it takes effect immediately with no restart. Turning it off — or
uninstalling the plugin — returns A0 to the shared workdir with nothing left behind.

> Technical note: this works by wrapping A0's project-path resolver at runtime, a deliberate
> dependency on framework internals. Every path is fail-safe — on any error (or a future A0 change),
> it falls straight through to A0's normal shared-workdir behavior, so nothing breaks.

> Note on timing: enabling isolation takes effect for a chat's terminal on its next session start,
> reset, or container restart; a chat with a live terminal at enable-time keeps the shared workdir
> until then. New chats isolate immediately.

### Self-cleanup of stranded folders

A0 reaps chats by their in-memory context — deleting a chat removes its whole `usr/chats/<id>/`
folder — but nothing in A0 scans the chats *directory*. So in a rare race a code-execution shell
that's still alive can re-create an isolated `workdir/` **after** its chat was deleted, leaving an
empty folder with no `chat.json` that no reaper ever sees. This plugin closes that gap: a throttled
background pass sweeps such folders (only ones that carry our footprint — a `workdir/` with no
`chat.json`, not a live chat, older than a 30-minute grace window) and, at the source, the isolation
resolver no longer re-creates a workdir for a chat whose folder is already gone.

### Isolation names can never leak onto tasks (v1.3.0)

The isolation "project" is an internal, computed-at-read-time name (`_a0wt_iso_<chat_id>`) that is
never meant to be stored anywhere. It turned out A0's **scheduler** could still capture it: creating
a scheduled task *from inside an isolated chat* copied that name onto the task record (the webui's
create dialog defaults its project to the chat's active project), and the scheduler then re-applied
it to the task's context on every run. Once the original chat was deleted, the task crashed at
launch on the dangling path (`FileNotFoundError` during prompt preparation). v1.3.0 closes this
three ways:

- **Prevention** — the plugin refuses any attempt to persist an `_a0wt_iso_*` name: task creation
  strips it from the new task record, and project activation onto any context is declined.
- **Fail-soft** — if a stale reference exists anyway (state written before v1.3.0), the resolvers
  heal it at read time: the name is ignored, and a dead chat's path falls back to the shared
  workdir, so nothing ever crashes.
- **Self-cleanup** — the same background pass that sweeps stranded folders also clears stale
  `_a0wt_iso_*` references from saved chats and scheduler task records (live chats are fixed
  through A0's own project deactivation; files are only edited for chats not currently in memory).

Every maintenance pass records what it did in a durable marker at
`usr/a0_worktree-runtime/maintenance.json` (run counts, folders swept, references cleared), so you
can verify it's working at a glance.

## Browse chats by name (opt-in)

Chat folders are named by a random id (`usr/chats/aB3dEf9k/`), which is awkward to search. Turn on
**Index chats by name** (default **off**) and the plugin maintains a read-only symlink farm at
`usr/chats/by-name/<title>__<chat_id> -> ../<chat_id>`, rebuilt periodically. You can then `ls`,
`grep`, and `cd` through it by title:

```
ls usr/chats/by-name/ | grep -i fragrance      # find a chat by its name
ls usr/chats/by-name/fragrance-pricing__aB3dEf9k/   # browse straight into the real folder
```

The real id-keyed folders are **never** renamed, moved, or written to — the index is a pure,
disposable projection (the `__<chat_id>` suffix keeps same-named chats distinct and reversible).
Turning the option off or uninstalling removes the `by-name/` folder.

## Configuration

`default_config.yaml`:

| Key | Default | Meaning |
|---|---|---|
| `isolate_chat_workdir` | `false` | Opt-in. When on, each chat with no explicit project gets its own `usr/chats/<chat_id>/workdir`. Effective immediately; real projects/worktrees unaffected. |
| `chat_name_index` | `false` | Opt-in. When on, maintains a read-only `usr/chats/by-name/<title>__<chat_id>` symlink farm so chats are browsable by name. Real id-keyed folders untouched; removed when off or on uninstall. |

## Settings survive updates

A0's plugin **update** is an uninstall→install cycle that deletes the plugin folder — config
included. Since v1.3.1 your settings are mirrored to a small stash at
`usr/a0_worktree-runtime/config-stash.json` (kept current on every save) and restored
automatically on install, so an update no longer resets the toggles or tears down the by-name
farm (it is rebuilt on install when the restored config has it on). Each restore is stamped in
the maintenance marker (`config_restored_at`).

## Uninstalling

Uninstall through the **Plugins UI**. The uninstall hook reclaims the worktree **checkouts** the
plugin created (so nothing is left dangling) but **preserves their branches** — your committed work
is never deleted by an uninstall. The small `usr/a0_worktree-runtime/` folder (maintenance marker +
config stash) is deliberately left behind so a reinstall restores your settings — delete it
manually if you want a fully clean removal.

## License

MIT — see [LICENSE](LICENSE).

## Citing

```bibtex
@software{a0_worktree,
  title  = {a0_worktree: isolated git worktrees as Agent Zero projects},
  author = {{King0James0}},
  year   = {2026},
  url    = {https://github.com/King0James0/a0-worktree-plugin}
}
```
