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
folder = projects.get_project_folder(syn)
check("synthetic -> chat workdir path", folder.replace("\\","/").endswith("usr/chats/ABCxyz99/workdir"))
check("chat workdir created", os.path.isdir(folder))
check("real project name still passes through", projects.get_project_folder("realproj").replace("\\","/").endswith("usr/projects/realproj"))

isolation.uninstall_wrap()
check("uninstall restores original resolver", projects.get_context_project_name is orig)
check("after uninstall: flagged chat -> no synthetic (original)", projects.get_context_project_name(Ctx("ABCxyz99")) is None)

import shutil; shutil.rmtree("/a0/usr/chats/ABCxyz99", ignore_errors=True)
print("\nSUMMARY:", "ALL PASS" if PASS else "FAILURES ABOVE")
sys.exit(0 if PASS else 1)
