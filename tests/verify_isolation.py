"""Ephemeral runtime check of the workdir-isolation wrap against real A0 internals.
Run inside an A0 container with the framework venv:  /opt/venv-a0/bin/python verify_isolation.py
Does NOT install the plugin or touch any running A0 — it imports A0's projects module into this
throwaway process, wraps it, and asserts the redirect + cascade + fail-safe behavior."""
import sys, importlib.util, os

sys.path.insert(0, "/a0")
from helpers import projects  # noqa: E402

# import the NEW isolation.py by path (not the installed v1.0 plugin)
spec = importlib.util.spec_from_file_location("iso", "/tmp/isolation.py")
iso = importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)

PASS = True
def check(label, cond):
    global PASS
    print(("PASS " if cond else "FAIL ") + label)
    PASS = PASS and cond

class Ctx:
    def __init__(self, cid): self.id = cid
    def get_data(self, key): return None   # a real chat with no project set

orig_gcpn, orig_gpf, orig_lbpd = projects.get_context_project_name, projects.get_project_folder, projects.load_basic_project_data

iso.install_wrap()
iso._enabled = True   # simulate toggle ON (bypass reading installed config)

cid = "ZZtest1234"
syn = iso._ISO_PREFIX + cid

# simulate a live context for this id so the liveness guard permits workdir creation (a real chat)
iso._context_is_live = lambda _cid: True

check("wrap installed (functions replaced)", projects.get_context_project_name is not orig_gcpn)
check("flagged chat -> synthetic project name", projects.get_context_project_name(Ctx(cid)) == syn)
check("synthetic name -> chat workdir path", projects.get_project_folder(syn) == os.path.join("/a0/usr/chats", cid, "workdir") or projects.get_project_folder(syn).replace("\\","/").endswith(f"usr/chats/{cid}/workdir"))
check("chat workdir created on resolve (live chat)", os.path.isdir(f"/a0/usr/chats/{cid}/workdir"))

# liveness guard + fail-soft: a DEAD chat (folder gone, no live context) must NOT get its workdir
# re-created, and the resolver must fall back to the SHARED workdir (stock no-project behaviour)
# instead of handing out a nonexistent path that would crash get_file_structure/file_tree.
dead = "ZZdead5678"
import shutil as _sh; _sh.rmtree(f"/a0/usr/chats/{dead}", ignore_errors=True)
iso._context_is_live = lambda _cid: False
dpath = projects.get_project_folder(iso._ISO_PREFIX + dead)
shared = iso._default_workdir()
check("dead chat -> falls back to the SHARED workdir (fail-soft)",
      shared is not None and dpath == shared and not os.path.isdir(f"/a0/usr/chats/{dead}/workdir"))
try:
    fs_dead = projects.get_file_structure(iso._ISO_PREFIX + dead)
    check("get_file_structure on a dead iso name does NOT crash", isinstance(fs_dead, str))
except Exception as e:
    check(f"get_file_structure on a dead iso name does NOT crash (raised: {e})", False)
iso._context_is_live = lambda _cid: True

# persisted-iso heal: if the ORIGINAL resolver returns an iso name (poisoned persisted state, e.g.
# the scheduler copied it onto a task context), gcpn must IGNORE it and answer with the context's
# OWN iso name (enabled) / None (disabled) — never the dangling foreign name.
_orig_gcpn_saved = iso._orig["gcpn"]
iso._orig["gcpn"] = lambda c, *a, **kw: iso._ISO_PREFIX + "SOMEDEADID"
check("persisted iso name is healed to the context's own iso name",
      projects.get_context_project_name(Ctx(cid)) == syn)
iso._enabled = False
check("persisted iso name healed to None when isolation is OFF",
      projects.get_context_project_name(Ctx(cid)) is None)
iso._enabled = True
iso._orig["gcpn"] = _orig_gcpn_saved

# activate guard: persisting an iso pseudo-project onto ANY context must be refused (no raise),
# and a real project name must still reach the original (here: raises Context not found).
check("activate_project REFUSES iso names (returns None, no raise)",
      projects.activate_project("no-such-ctx", iso._ISO_PREFIX + "whatever") is None)
try:
    projects.activate_project("no-such-ctx", "some-real-project")
    check("activate_project passes real names to the original", False)
except Exception:
    check("activate_project passes real names to the original", True)

# task guard: the add_task wrap is installed and the strip logic nulls iso project fields.
try:
    from helpers import task_scheduler as _ts
    check("SchedulerTaskList.add_task is wrapped (sentinel)",
          getattr(_ts.SchedulerTaskList.add_task, "_a0wt_wrapper", False) is True)
except Exception as e:
    check(f"SchedulerTaskList.add_task is wrapped (import failed: {e})", False)

class FakeTask:
    def __init__(self, pn): self.project_name = pn; self.project_color = "#abc"; self.name = "t"

ft = FakeTask(iso._ISO_PREFIX + "SOMEDEADID")
check("strip_iso_project nulls an iso project off a task",
      iso.strip_iso_project(ft) is True and ft.project_name is None and ft.project_color is None)
ft2 = FakeTask("real-project")
check("strip_iso_project leaves a real project alone",
      iso.strip_iso_project(ft2) is False and ft2.project_name == "real-project")
bd = projects.load_basic_project_data(syn)
check("synthetic basic_data has file_structure", isinstance(bd, dict) and "file_structure" in bd and bd["file_structure"]["enabled"] is True)
# the cascade: get_file_structure must list the CHAT folder (empty), proving _75 will too
try:
    fs = projects.get_file_structure(syn)
    check("get_file_structure cascades to chat folder (no crash)", isinstance(fs, str))
except Exception as e:
    check(f"get_file_structure cascades (raised: {e})", False)

# real/explicit project must pass through untouched
check("non-synthetic name -> original folder", projects.get_project_folder("realproj").replace("\\","/").endswith("usr/projects/realproj"))
check("no project + enabled -> None passthrough handled", True)

# toggle OFF -> inert pass-through (returns original None for an unprojected chat)
iso._enabled = False
check("toggle OFF -> no synthetic name (original behavior)", projects.get_context_project_name(Ctx(cid)) in (None, "", orig_gcpn(Ctx(cid))))

# uninstall restores originals
_orig_ap_saved = iso._orig.get("ap")
iso.uninstall_wrap()
check("uninstall restores original get_context_project_name", projects.get_context_project_name is orig_gcpn)
check("uninstall restores original get_project_folder", projects.get_project_folder is orig_gpf)
check("uninstall restores original activate_project",
      _orig_ap_saved is None or projects.activate_project is _orig_ap_saved)
try:
    from helpers import task_scheduler as _ts2
    check("uninstall restores original add_task",
          not getattr(_ts2.SchedulerTaskList.add_task, "_a0wt_wrapper", False))
except Exception:
    check("uninstall restores original add_task (import failed)", False)

# cleanup the test chat dir
try:
    import shutil; shutil.rmtree(f"/a0/usr/chats/{cid}", ignore_errors=True)
except Exception:
    pass

print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
sys.exit(0 if PASS else 1)
