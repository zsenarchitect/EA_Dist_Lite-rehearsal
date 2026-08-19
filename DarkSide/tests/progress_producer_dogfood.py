"""DOGFOOD: real UI.progress_bar against the REAL daemon currently running.

That daemon is the OLD build (no capability file), i.e. exactly the
stale-running-daemon skew case: a live host holding the single-instance mutex
that does not understand progress jobs.
"""
import os, sys, time

_HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.normpath(
    os.path.join(_HERE, os.pardir, os.pardir, "Apps", "lib", "EnneadTab"))
sys.path.insert(0, LIB)
import ENVIRONMENT, UI

print("dump folder :", ENVIRONMENT.DUMP_FOLDER)
print("capability advertises progress?", UI.host_can_render_progress())
print("(False is CORRECT here: the running host is the pre-change build)\n")

jobs_dir = os.path.join(ENVIRONMENT.DUMP_FOLDER, UI.JOBS_SUBDIR)
before = set(os.listdir(jobs_dir)) if os.path.isdir(jobs_dir) else set()

t0 = time.time()
items = ["Door_Single", "Window_Fixed", "Curtain_Panel", "Column_Round"]
seen = []
UI.progress_bar(items, lambda x: seen.append(x),
                label_func=lambda x: "Working [{}]".format(x),
                title="Dogfood run")
elapsed = time.time() - t0

after = set(os.listdir(jobs_dir)) if os.path.isdir(jobs_dir) else set()

fails = []
def check(n, c, d=""):
    print(("  PASS  " if c else "  FAIL  ") + n + ("" if c else " :: " + d))
    if not c: fails.append(n)

print()
check("caller's work actually ran", seen == items, str(seen))
check("did NOT block on a squatting old daemon", elapsed < 5.0,
      "%.2fs" % elapsed)
check("no job file leaked into the real Dump", after == before,
      "new: %s" % (after - before))
check("nesting stack unwound cleanly", UI._ACTIVE_JOBS == [], str(UI._ACTIVE_JOBS))

# Nested case: inner must not kill outer, sound only once at the very end.
print("\n-- nested progress_bar (the block2family shape) --")
depth_seen = []
def outer_work(x):
    UI.progress_bar(["a", "b"], lambda y: depth_seen.append((x, y)),
                    title="inner")
UI.progress_bar(["P", "Q"], outer_work, title="outer")
check("nested inner+outer both ran", len(depth_seen) == 4, str(depth_seen))
check("stack empty after nesting", UI._ACTIVE_JOBS == [], str(UI._ACTIVE_JOBS))

# Empty collection: today's silent no-op must stay a no-op, not raise.
print("\n-- empty collection (block2family can produce this) --")
try:
    UI.progress_bar([], lambda x: None, title="empty")
    check("empty list does not raise (no ZeroDivisionError)", True)
except Exception as e:
    check("empty list does not raise (no ZeroDivisionError)", False, repr(e))

# Caller exceptions must propagate untouched.
print("\n-- caller exception must propagate --")
class Boom(Exception): pass
def explode(x): raise Boom("caller failure")
try:
    UI.progress_bar(["x"], explode, title="boom")
    check("caller exception propagates", False, "it was swallowed")
except Boom:
    check("caller exception propagates", True)
except Exception as e:
    check("caller exception propagates", False, "wrong type: %r" % e)
check("stack unwound even after caller raised", UI._ACTIVE_JOBS == [],
      str(UI._ACTIVE_JOBS))

print("\n" + ("DOGFOOD ALL PASS" if not fails else "FAILURES: " + ", ".join(fails)))
sys.exit(1 if fails else 0)
