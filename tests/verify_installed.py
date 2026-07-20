"""Throwaway live check: the INSTALLED plugin module + the REAL saved config (toggle on) actually
redirect via A0's real projects resolvers, and uninstall restores. Run in the throwaway container."""
import sys, os
sys.path.insert(0, "/a0")
from helpers import projects
from usr.plugins.a0_worktree.helpers import isolation  # the INSTALLED module

PASS = True
def check(label, cond):
    global PASS; print(("PASS " if cond else "FAIL ") + label); PASS = PASS and cond

class Ctx:
    def __init__(self, cid): self.id = cid
    def get_data(self, key): return None

orig = projects.get_context_project_name
isolation.install_wrap()  # reads the REAL saved config (isolate_chat_workdir: true)

check("installed wrap reads real config -> enabled", isolation._enabled is True)
syn = projects.get_context_project_name(Ctx("ABCxyz99"))
check("enabled: flagged chat -> synthetic name", syn == isolation._ISO_PREFIX + "ABCxyz99")
_real_liveness = isolation._context_is_live
isolation._context_is_live = lambda _cid: True  # simulate a live chat so the workdir may be created
folder = projects.get_project_folder(syn)
check("synthetic -> chat workdir path", folder.replace("\\","/").endswith("usr/chats/ABCxyz99/workdir"))
check("chat workdir created", os.path.isdir(folder))
isolation._context_is_live = lambda _cid: False  # dead chat -> fail-soft to the SHARED workdir
import shutil as _sh; _sh.rmtree("/a0/usr/chats/ABCxyz99", ignore_errors=True)
dead_folder = projects.get_project_folder(syn)
check("dead chat -> shared workdir fallback (fail-soft)",
      dead_folder == isolation._default_workdir() and not os.path.isdir("/a0/usr/chats/ABCxyz99"))
isolation._context_is_live = _real_liveness  # restore the module's real liveness check
check("real project name still passes through", projects.get_project_folder("realproj").replace("\\","/").endswith("usr/projects/realproj"))

isolation.uninstall_wrap()
check("uninstall restores original resolver", projects.get_context_project_name is orig)
check("after uninstall: flagged chat -> no synthetic (original)", projects.get_context_project_name(Ctx("ABCxyz99")) is None)

import shutil; shutil.rmtree("/a0/usr/chats/ABCxyz99", ignore_errors=True)
print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
sys.exit(0 if PASS else 1)
