"""Lightweight drift check for a0_worktree — config parity (stdlib only).

Asserts the config UI (webui/config.html) and the defaults (default_config.yaml) cover the SAME
set of keys, so a key can never be added to one without the other. The UI binds each setting via
Alpine `x-model="config.<key>"`; the defaults are top-level YAML keys.

Run:  python tests/drift_check.py
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONFIG_YAML = os.path.join(ROOT, "default_config.yaml")
CONFIG_HTML = os.path.join(ROOT, "webui", "config.html")

PASS = True


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


def _html_config_keys(path: str) -> set[str]:
    """Keys the config UI binds via x-model="config.<key>" (or config['<key>'])."""
    with open(path, encoding="utf-8") as f:
        html = f.read()
    keys = set(re.findall(r"config\.([A-Za-z_][A-Za-z0-9_]*)", html))
    keys |= set(re.findall(r"config\[['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\]", html))
    return keys


def main():
    check("default_config.yaml exists", os.path.isfile(CONFIG_YAML))
    check("webui/config.html exists", os.path.isfile(CONFIG_HTML))
    if not (os.path.isfile(CONFIG_YAML) and os.path.isfile(CONFIG_HTML)):
        print("\nSUMMARY: FAILURES ABOVE")
        return 1

    yaml_keys = _yaml_top_keys(CONFIG_YAML)
    html_keys = _html_config_keys(CONFIG_HTML)

    check(f"default_config.yaml has keys ({sorted(yaml_keys)})", len(yaml_keys) > 0)
    check(f"config.html binds keys ({sorted(html_keys)})", len(html_keys) > 0)

    missing_in_html = yaml_keys - html_keys
    missing_in_yaml = html_keys - yaml_keys
    check(f"every default key is bound in the config UI (missing: {sorted(missing_in_html)})",
          not missing_in_html)
    check(f"every config-UI key has a default (missing: {sorted(missing_in_yaml)})",
          not missing_in_yaml)

    print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
    return 0 if PASS else 1


if __name__ == "__main__":
    sys.exit(main())
