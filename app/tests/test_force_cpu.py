"""
Tests for force_cpu.py's lazy torch-patching hook (SR-2,
puddlejump/zz/startup-review-sr0-sr1-findings.md).

force_cpu's hook, the environment variables it sets, and
mixtape.worker_init.init_worker_process all mutate process-global state
(sys.modules, sys.meta_path, os.environ) exactly once per process, which is
the real shape of a forked Celery worker -- each fork gets a fresh
interpreter and does this setup exactly once. Most of these tests run in a
fresh subprocess per case instead of importing torch inline, both to match
that real shape and so one test's "torch got imported" can't leak into the
next test in the same process.
"""

import subprocess
import sys
from pathlib import Path

import pytest

APP_DIR = Path(__file__).resolve().parent.parent


def run_snippet(code: str) -> subprocess.CompletedProcess:
    """Run `code` in a fresh interpreter with app/ on sys.path, mirroring
    how a forked worker process starts clean."""
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(APP_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_worker_init_does_not_import_torch_eagerly():
    """init_worker_process must not trigger `import torch` on its own."""
    code = """
import sys
sys.path.insert(0, ".")
from mixtape.worker_init import init_worker_process
init_worker_process()
assert "torch" not in sys.modules, "torch was imported eagerly by init_worker_process"
print("OK: torch not in sys.modules after init_worker_process")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: torch not in sys.modules after init_worker_process" in result.stdout


def test_first_torch_import_after_worker_init_triggers_patch():
    """After init_worker_process, the *first* `import torch` anywhere in the
    process should still end up patched -- that's the whole point of
    deferring to the hook instead of calling patch_torch() eagerly."""
    code = """
import sys
sys.path.insert(0, ".")
from mixtape.worker_init import init_worker_process
init_worker_process()
assert "torch" not in sys.modules

import torch
assert "torch" in sys.modules
assert torch.backends.mps.is_available() is False, "mps.is_available() was not patched"
print("OK: first import torch after init_worker_process was patched")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: first import torch after init_worker_process was patched" in result.stdout


def test_patch_applied_immediately_if_torch_already_imported():
    """If torch was already imported before force_cpu loads (e.g. an
    autoreload re-entry, or some other earlier import), force_cpu must patch
    it right away rather than waiting for a second import that will never
    come."""
    code = """
import sys
sys.path.insert(0, ".")
import torch  # import torch BEFORE force_cpu
assert torch.backends.mps.is_available() is True or torch.backends.mps.is_available() is False
original = torch.backends.mps.is_available

import force_cpu
assert torch.backends.mps.is_available() is False, "patch was not applied immediately"
print("OK: patch applied immediately when torch was pre-imported")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: patch applied immediately when torch was pre-imported" in result.stdout


def test_missing_torch_does_not_crash_patch_torch():
    """If torch isn't importable, patch_torch() must degrade quietly --
    simulated by blocking the real import rather than uninstalling torch
    from this venv (sys.modules[name] = None is the standard "block this
    import" idiom: CPython raises ImportError for it without needing the
    module to be absent from the environment)."""
    code = """
import sys
sys.modules["torch"] = None
sys.path.insert(0, ".")
import force_cpu
force_cpu.patch_torch()
print("OK: patch_torch() did not raise when torch is unavailable")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: patch_torch() did not raise when torch is unavailable" in result.stdout


def test_hook_find_spec_returns_none_when_torch_not_found(monkeypatch):
    """The hook's find_spec must hand back None (defer to the normal
    ModuleNotFoundError) when torch genuinely can't be found, instead of
    raising or wedging sys.meta_path -- exercised directly, without a real
    import statement, so it doesn't depend on torch being absent from this
    venv."""
    import importlib.util

    import force_cpu

    hook = force_cpu.TorchImportHook()
    sys.meta_path.insert(0, hook)
    try:
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        spec = hook.find_spec("torch", None)
        assert spec is None
        # find_spec must put itself back after a failed lookup -- a later,
        # real import of torch still needs the hook in place.
        assert hook in sys.meta_path
    finally:
        if hook in sys.meta_path:
            sys.meta_path.remove(hook)


def test_hook_ignores_unrelated_module_names():
    """find_spec must only ever act on 'torch' -- never swallow or redirect
    an unrelated import."""
    import force_cpu

    hook = force_cpu.TorchImportHook()
    assert hook.find_spec("json", None) is None
    assert hook.find_spec("sentence_transformers", None) is None


def test_hook_fires_once_and_does_not_recurse():
    """The hook must remove itself from sys.meta_path after it fires, and
    must not re-enter find_spec while resolving torch's real spec (the
    legacy version avoided this with an explicit `remove(self)`; the
    find_spec rewrite keeps that same guard)."""
    code = """
import sys
sys.path.insert(0, ".")
import force_cpu

hooks_before = [f for f in sys.meta_path if isinstance(f, force_cpu.TorchImportHook)]
assert len(hooks_before) == 1, f"expected exactly one hook installed, found {len(hooks_before)}"

import torch  # triggers the hook

hooks_after = [f for f in sys.meta_path if isinstance(f, force_cpu.TorchImportHook)]
assert len(hooks_after) == 0, "hook did not remove itself after firing"

# A second, unrelated import of torch-dependent code must not reinstall or
# re-trigger anything -- torch is already in sys.modules, so ensure_hook_installed()
# is correctly a no-op here.
force_cpu.ensure_hook_installed()
hooks_final = [f for f in sys.meta_path if isinstance(f, force_cpu.TorchImportHook)]
assert len(hooks_final) == 0, "ensure_hook_installed() reinstalled the hook after torch was already loaded"

print("OK: hook fired exactly once and did not recurse")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: hook fired exactly once and did not recurse" in result.stdout


def test_ensure_hook_installed_is_idempotent():
    """Calling ensure_hook_installed() twice before torch is imported must
    not install two hooks."""
    code = """
import sys
sys.path.insert(0, ".")
import force_cpu

force_cpu.ensure_hook_installed()
force_cpu.ensure_hook_installed()

hooks = [f for f in sys.meta_path if isinstance(f, force_cpu.TorchImportHook)]
assert len(hooks) == 1, f"expected exactly one hook, found {len(hooks)}"
print("OK: ensure_hook_installed() is idempotent")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: ensure_hook_installed() is idempotent" in result.stdout


def test_patch_tqdm_noop_applies():
    """patch_tqdm() must still replace tqdm.tqdm with the no-op class --
    unrelated to the torch-timing change, but must keep working."""
    code = """
import sys
sys.path.insert(0, ".")
import force_cpu

force_cpu.patch_tqdm()
import tqdm
bar = tqdm.tqdm([1, 2, 3])
assert list(bar) == [1, 2, 3]
assert bar.__class__.__name__ == "NoOpTqdm"
print("OK: tqdm no-op patch applied")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: tqdm no-op patch applied" in result.stdout


def test_worker_init_skips_patch_tqdm_when_fake_tqdm_already_injected():
    """init_worker_process's existing 'fake tqdm already injected' branch
    (unchanged by this patch) must still be honored -- it must not call
    patch_tqdm() again if a FakeTqdm is already sitting in sys.modules."""
    code = """
import sys
sys.path.insert(0, ".")

# worker_init's existing branch checks sys.modules["tqdm"].__class__.__name__
# == "FakeTqdm" -- so sys.modules["tqdm"] itself must be an instance of a
# class literally named that, same as whatever injects it in practice.
class FakeTqdm:
    pass

fake_instance = FakeTqdm()
sys.modules["tqdm"] = fake_instance

from mixtape.worker_init import init_worker_process
init_worker_process()

# patch_tqdm() would reassign sys.modules["tqdm"].tqdm to NoOpTqdm; since it
# must be skipped here, sys.modules["tqdm"] should be the exact same,
# untouched instance.
assert sys.modules["tqdm"] is fake_instance, "patch_tqdm() ran despite fake tqdm already injected"
print("OK: patch_tqdm() skipped when fake tqdm already injected")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: patch_tqdm() skipped when fake tqdm already injected" in result.stdout


@pytest.mark.parametrize("pool", ["solo", "prefork"])
def test_worker_init_safe_under_solo_and_forked_pools(pool):
    """Celery's solo pool runs init_worker_process in the same process that
    started it; prefork runs it after an os.fork(). Exercise both shapes
    locally: solo directly, prefork by forking this subprocess once and
    running init_worker_process only in the child, matching how prefork
    workers actually get this signal (worker_process_init fires post-fork,
    never in the pre-fork parent)."""
    if pool == "solo":
        code = """
import sys
sys.path.insert(0, ".")
from mixtape.worker_init import init_worker_process
init_worker_process()
assert "torch" not in sys.modules
print("OK: solo pool startup did not import torch")
"""
    else:
        code = """
import os
import sys
sys.path.insert(0, ".")

pid = os.fork()
if pid == 0:
    # child: this is where a prefork worker's worker_process_init fires
    from mixtape.worker_init import init_worker_process
    init_worker_process()
    ok = "torch" not in sys.modules
    os._exit(0 if ok else 1)
else:
    _, status = os.waitpid(pid, 0)
    assert os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0, "child process import check failed"
    print("OK: forked (prefork-style) child did not import torch on init")
"""
    result = run_snippet(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK:" in result.stdout
