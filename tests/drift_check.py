"""Lightweight drift check for a0_worktree — config parity (stdlib only).

Asserts the config UI and the defaults (default_config.yaml) cover the SAME set of keys, so a key
can never be added to one without the other. The config screen is schema-driven: the field schema
(and thus the bound keys) lives in webui/config-store.js as `k: "<key>"` entries, rendered by
webui/config.html via Alpine `x-model="config[f.k]"`. The defaults are top-level YAML keys.

Run:  python tests/drift_check.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_YAML = os.path.join(ROOT, "default_config.yaml")
CONFIG_HTML = os.path.join(ROOT, "webui", "config.html")
CONFIG_STORE = os.path.join(ROOT, "webui", "config-store.js")
AGENTS_MD = os.path.join(ROOT, "AGENTS.md")

PASS = True

# Skeleton/placeholder markers that a REAL AGENTS.md must never contain.
_SKELETON_MARKERS = ("<plugin_id>", "This is a SKELETON")
# An unresolved angle-bracket placeholder: "<" + capital letter + text + ">", e.g. "<One sentence" / "<3-6 lines".
_PLACEHOLDER_RE = re.compile(r"<[A-Z][^>\n]*>")


def _agents_md_skeleton_markers(path: str) -> list[str]:
    """Return any skeleton/placeholder markers present in AGENTS.md (empty list = clean)."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    found = [m for m in _SKELETON_MARKERS if m in text]
    found += sorted(set(_PLACEHOLDER_RE.findall(text)))
    return found


def check(label, cond):
    global PASS
    print(("PASS " if cond else "FAIL ") + label)
    PASS = PASS and cond


def _yaml_top_keys(path: str) -> set[str]:
    """Top-level `key: value` keys from a flat YAML file (no nesting here), comments/blank-lines
    skipped. Avoids a PyYAML dependency since the file is intentionally flat."""
    keys = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line[0] in " \t":  # nested line — none expected, but ignore defensively
                continue
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", line)
            if m:
                keys.add(m.group(1))
    return keys


def _ui_config_keys(html_path: str, store_path: str) -> set[str]:
    """Keys the config UI binds. The schema lives in config-store.js as `k: "<key>"` entries
    (rendered via x-model="config[f.k]"); also catch any direct config['<key>'] bracket-bindings
    in either file for forward-compat. (The loose config.<word> dotted form is NOT scanned — it
    matches filenames like config.html in prose; bind via config['<key>'] or the schema instead.)"""
    keys: set[str] = set()
    for path in (html_path, store_path):
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        keys |= set(re.findall(r"config\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]", text))
    # Schema field keys: `k: "<key>"` (or single-quoted) in the store.
    if os.path.isfile(store_path):
        with open(store_path, encoding="utf-8") as f:
            store = f.read()
        keys |= set(re.findall(r"\bk\s*:\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]", store))
    return keys


def main():
    agents_ok = os.path.isfile(AGENTS_MD)
    check("AGENTS.md exists at repo root", agents_ok)
    if agents_ok:
        markers = _agents_md_skeleton_markers(AGENTS_MD)
        check(f"AGENTS.md is filled in, not a skeleton (placeholders: {markers})", not markers)

    check("default_config.yaml exists", os.path.isfile(CONFIG_YAML))
    check("webui/config.html exists", os.path.isfile(CONFIG_HTML))
    check("webui/config-store.js exists", os.path.isfile(CONFIG_STORE))
    if not (os.path.isfile(CONFIG_YAML) and os.path.isfile(CONFIG_HTML) and os.path.isfile(CONFIG_STORE)):
        print("\nSUMMARY: FAILURES ABOVE")
        return 1

    yaml_keys = _yaml_top_keys(CONFIG_YAML)
    ui_keys = _ui_config_keys(CONFIG_HTML, CONFIG_STORE)

    check(f"default_config.yaml has keys ({sorted(yaml_keys)})", len(yaml_keys) > 0)
    check(f"config UI binds keys ({sorted(ui_keys)})", len(ui_keys) > 0)

    missing_in_html = yaml_keys - ui_keys
    missing_in_yaml = ui_keys - yaml_keys
    check(f"every default key is bound in the config UI (missing: {sorted(missing_in_html)})",
          not missing_in_html)
    check(f"every config-UI key has a default (missing: {sorted(missing_in_yaml)})",
          not missing_in_yaml)

    print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
