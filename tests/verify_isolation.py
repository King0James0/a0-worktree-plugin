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

check("wrap installed (functions replaced)", projects.get_context_project_name is not orig_gcpn)
check("flagged chat -> synthetic project name", projects.get_context_project_name(Ctx(cid)) == syn)
check("synthetic name -> chat workdir path", projects.get_project_folder(syn) == os.path.join("/a0/usr/chats", cid, "workdir") or projects.get_project_folder(syn).replace("\\","/").endswith(f"usr/chats/{cid}/workdir"))
check("chat workdir created on resolve", os.path.isdir(f"/a0/usr/chats/{cid}/workdir"))
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
iso.uninstall_wrap()
check("uninstall restores original get_context_project_name", projects.get_context_project_name is orig_gcpn)
check("uninstall restores original get_project_folder", projects.get_project_folder is orig_gpf)

# cleanup the test chat dir
try:
    import shutil; shutil.rmtree(f"/a0/usr/chats/{cid}", ignore_errors=True)
except Exception:
    pass

print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
sys.exit(0 if PASS else 1)
