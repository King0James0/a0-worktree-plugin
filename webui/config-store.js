// A0 Worktree config-screen schema + logic, as an Alpine store. Loaded by webui/config.html via
// <script type="module">. Logic lives here (a real .js file) so there are NO HTML-attribute quoting
// limits — a stray double-quote inside a double-quoted x-data attribute silently terminates it and
// renders a BLANK panel. The drift-check reads the `k:` keys from THIS file.
//
// Each section: { title, desc, fields: [...] }. Each field: { k, t, lbl, h, opts?, when?, safety? }.
//   t: bool | int | float | text | enum (enum needs opts: []).
//   lbl: friendly title shown to the user. h: plain-language explanation/tip.
//   when: [{key, val?}] — show only when every condition holds (config[key] truthy, or === val).
//   safety: true flags a footgun.
// Small plugin (1 section / 2 fields) → no tab bar, sections render stacked.

import { createStore } from "/js/AlpineStore.js";

export const store = createStore("a0wtCfg", {
  sections: [
    { title: "A0 Worktree — per-chat workspace",
      desc: "Worktree isolation gives a chat (or a swarm subagent) its own checkout of a repo as a project. The option below is a separate, lightweight isolation for everyday chats.",
      fields: [
        { k: "isolate_chat_workdir", t: "bool", lbl: "Isolate each chat's working directory",
          h: "When on, every chat that has no explicit project gets its own working directory at usr/chats/<chat_id>/workdir instead of the shared usr/workdir. The chat's code execution, the file list shown to the agent, and saved office documents all resolve there, so chats no longer see each other's scratch files. Files live with the chat and are removed when the chat is. Real projects and worktrees are never affected. Takes effect immediately. Default off." },
        { k: "chat_name_index", t: "bool", lbl: "Index chats by name (browsable folders)",
          h: "When on, a throttled background pass maintains a read-only usr/chats/by-name/<name>__<chat_id> symlink farm so you can browse or search chat folders by their title instead of the random id. The real id-keyed folders are never renamed or touched; the index rebuilds periodically and is removed when you turn this off. Independent of workdir isolation. Default off." },
      ] },
  ],

  shown(f, config) {
    return !f.when || f.when.every((c) => (c.val !== undefined ? config[c.key] === c.val : !!config[c.key]));
  },

  init() {},
});
