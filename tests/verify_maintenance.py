"""Stdlib-only test of helpers/maintenance.py — orphan sweep, name index, slugify.

No A0 needed. Builds a fake usr/chats tree in a temp dir, monkeypatches the two seams
(`_chats_dir`, `_live_ids`), and asserts the sweep predicate + symlink farm behave exactly as the
HARD INVARIANTS require (only our footprint is swept; real chats and live chats are never touched;
the by-name farm never harms the real folders).

Run:  python tests/verify_maintenance.py
"""

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

spec = importlib.util.spec_from_file_location("maint", os.path.join(ROOT, "helpers", "maintenance.py"))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

PASS = True


def check(label, cond):
    global PASS
    print(("PASS " if cond else "FAIL ") + label)
    PASS = PASS and cond


def _mk_chat(chats, cid, *, with_json=True, name=None, with_workdir=True, age_secs=0):
    d = os.path.join(chats, cid)
    os.makedirs(d, exist_ok=True)
    if with_workdir:
        os.makedirs(os.path.join(d, "workdir"), exist_ok=True)
    if with_json:
        with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
            json.dump({"id": cid, "name": name or cid}, f)
    if age_secs:
        old = time.time() - age_secs
        os.utime(d, (old, old))
    return d


# ---- slugify ----
check("slugify basic", m.slugify("Fragrance Pricing Model") == "fragrance-pricing-model")
check("slugify collapses + trims punctuation", m.slugify("  Vivy:: curation!!  ") == "vivy-curation")
check("slugify empty -> 'chat'", m.slugify("") == "chat" and m.slugify(None) == "chat")
check("slugify truncates to <=40", len(m.slugify("x" * 100)) <= 40)

# ---- sweep + index against a fake tree ----
tmp = tempfile.mkdtemp()
try:
    chats = os.path.join(tmp, "usr", "chats")
    os.makedirs(chats, exist_ok=True)

    # the cases
    _mk_chat(chats, "RealChat01", with_json=True, name="Solana price", age_secs=3600)      # real → keep
    _mk_chat(chats, "Orphan0001", with_json=False, with_workdir=True, age_secs=3600)        # stranded → sweep
    _mk_chat(chats, "LiveChat01", with_json=False, with_workdir=True, age_secs=3600)        # no json but LIVE → keep
    _mk_chat(chats, "FreshOrph1", with_json=False, with_workdir=True, age_secs=0)           # stranded but young → keep
    _mk_chat(chats, "NoWorkdir1", with_json=False, with_workdir=False, age_secs=3600)       # not our footprint → keep

    m._chats_dir = lambda: chats
    m._live_ids = lambda: {"LiveChat01"}

    removed = m.sweep_orphans()

    check("sweep removes the stranded orphan", "Orphan0001" in removed and not os.path.isdir(os.path.join(chats, "Orphan0001")))
    check("sweep keeps a real chat (has chat.json)", os.path.isdir(os.path.join(chats, "RealChat01")))
    check("sweep keeps a live context (no json but live)", os.path.isdir(os.path.join(chats, "LiveChat01")))
    check("sweep keeps a young orphan (grace window)", os.path.isdir(os.path.join(chats, "FreshOrph1")))
    check("sweep ignores a folder without our workdir footprint", os.path.isdir(os.path.join(chats, "NoWorkdir1")))

    # unknown liveness -> conservative, sweep nothing
    m._live_ids = lambda: None
    _mk_chat(chats, "Orphan0002", with_json=False, with_workdir=True, age_secs=3600)
    removed2 = m.sweep_orphans()
    check("sweep stands its hand when liveness is unknown", removed2 == [] and os.path.isdir(os.path.join(chats, "Orphan0002")))
    m._live_ids = lambda: {"LiveChat01"}

    # ---- name index ----
    _mk_chat(chats, "AbCdEf12", with_json=True, name="My Cool Chat", age_secs=10)
    n = m.rebuild_name_index()
    by_name = os.path.join(chats, "by-name")
    links = sorted(os.listdir(by_name))
    real_link = next((l for l in links if l.endswith("__AbCdEf12")), None)
    check("name index builds symlinks for real chats", n >= 1 and real_link is not None)
    check("name index slug uses the chat title", real_link == "my-cool-chat__AbCdEf12")
    target = os.path.realpath(os.path.join(by_name, real_link))
    check("symlink resolves to the real id-keyed folder", target == os.path.realpath(os.path.join(chats, "AbCdEf12")))
    check("name index does NOT index a folder without chat.json", not any(l.endswith("__FreshOrph1") for l in links))

    # rebuild after a rename clears the stale link; real folder survives the wipe
    with open(os.path.join(chats, "AbCdEf12", "chat.json"), "w", encoding="utf-8") as f:
        json.dump({"id": "AbCdEf12", "name": "Renamed Chat"}, f)
    m.rebuild_name_index()
    links2 = os.listdir(by_name)
    check("rebuild reflects a rename (old slug gone, new present)",
          any(l == "renamed-chat__AbCdEf12" for l in links2) and not any(l == "my-cool-chat__AbCdEf12" for l in links2))
    check("real chat folder survives index wipe-and-rebuild", os.path.isdir(os.path.join(chats, "AbCdEf12")))

    # remove_name_index tears down the farm only
    m.remove_name_index()
    check("remove_name_index deletes by-name only", not os.path.isdir(by_name) and os.path.isdir(os.path.join(chats, "AbCdEf12")))

    # ---- stale iso-ref sweep (v1.3.0) ----
    def _mk_chat_with_project(cid, project_data, project_output=None):
        d = _mk_chat(chats, cid, with_json=True, name=cid)
        with open(os.path.join(d, "chat.json"), "w", encoding="utf-8") as f:
            json.dump({"id": cid, "name": cid,
                       "data": {"project": project_data},
                       "output_data": {"project": project_output}}, f)
        return os.path.join(d, "chat.json")

    iso = m._ISO_PREFIX + "DeadChat99"
    cj_stale = _mk_chat_with_project("StaleRef01", iso, {"name": iso, "color": "x"})   # both shapes
    cj_live = _mk_chat_with_project("LiveRef001", iso)                                  # live → framework path
    cj_real = _mk_chat_with_project("RealRef001", "myproj", {"name": "myproj"})        # real project → keep

    tasks_path = os.path.join(tmp, "usr", "scheduler", "tasks.json")
    os.makedirs(os.path.dirname(tasks_path), exist_ok=True)
    with open(tasks_path, "w", encoding="utf-8") as f:
        json.dump({"tasks": [
            {"uuid": "t1", "name": "Poisoned Task", "project_name": iso, "project_color": "#abc"},
            {"uuid": "t2", "name": "Clean Task", "project_name": "myproj", "project_color": "#def"},
        ]}, f)

    m._live_ids = lambda: {"LiveRef001"}
    m._tasks_json_path = lambda: tasks_path

    out = m.sweep_stale_iso_refs()

    d_stale = json.load(open(cj_stale, encoding="utf-8"))
    check("iso sweep clears a dead context's persisted iso ref (both shapes)",
          "StaleRef01" in out["contexts"] and d_stale["data"]["project"] is None and d_stale["output_data"]["project"] is None)
    check("iso sweep preserves the rest of the chat.json it edits", d_stale.get("name") == "StaleRef01")
    d_live = json.load(open(cj_live, encoding="utf-8"))
    check("iso sweep never edits a LIVE context's file directly (framework absent -> untouched)",
          "LiveRef001" not in out["contexts"] and d_live["data"]["project"] == iso)
    d_real = json.load(open(cj_real, encoding="utf-8"))
    check("iso sweep never touches a real project ref", d_real["data"]["project"] == "myproj")

    d_tasks = json.load(open(tasks_path, encoding="utf-8"))
    t1, t2 = d_tasks["tasks"]
    check("iso sweep clears a poisoned task record (name + color)",
          out["tasks"] == ["Poisoned Task"] and t1["project_name"] is None and t1["project_color"] is None)
    check("iso sweep leaves a clean task record alone", t2["project_name"] == "myproj" and t2["project_color"] == "#def")

    # unknown liveness -> the chats leg stands its hand entirely
    cj_stale2 = _mk_chat_with_project("StaleRef02", iso)
    m._live_ids = lambda: None
    out2 = m.sweep_stale_iso_refs()
    d_stale2 = json.load(open(cj_stale2, encoding="utf-8"))
    check("iso sweep stands its hand on unknown liveness", out2["contexts"] == [] and d_stale2["data"]["project"] == iso)
    m._live_ids = lambda: {"LiveRef001"}

    # idempotent: a second pass finds nothing left to clear
    out3 = m.sweep_stale_iso_refs()
    check("iso sweep is idempotent (second pass clears nothing new)",
          "StaleRef01" not in out3["contexts"] and out3["tasks"] == [])

    # ---- durable marker ----
    rt = os.path.join(tmp, "usr", "a0_worktree-runtime")
    os.makedirs(rt, exist_ok=True)
    m._runtime_dir = lambda: rt
    m.write_marker(sets={"last_run_at": "T0"}, increments={"runs_total": 1, "orphans_removed_total": 2})
    m.write_marker(sets={"last_run_at": "T1"}, increments={"runs_total": 1, "orphans_removed_total": 0})
    marker = json.load(open(os.path.join(rt, "maintenance.json"), encoding="utf-8"))
    check("marker sets overwrite and increments accumulate",
          marker["last_run_at"] == "T1" and marker["runs_total"] == 2 and marker["orphans_removed_total"] == 2)
    m.remove_runtime_dir()
    check("remove_runtime_dir deletes the marker dir", not os.path.isdir(rt))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
sys.exit(0 if PASS else 1)
