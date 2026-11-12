"""
Force PyTorch to use CPU only - disable MPS and CUDA detection.

This module MUST be imported before any torch/transformers imports.
It monkey-patches torch to prevent MPS (Apple GPU) usage which causes crashes.

Usage:
    import force_cpu  # Must be first import!
    import torch
"""

import importlib.abc
import importlib.util
import os
import sys

# Set environment variables BEFORE any torch imports
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '0'
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['OMP_NUM_THREADS'] = '4'
os.environ['TQDM_DISABLE'] = '1'  # Disable tqdm to prevent threading crashes

print("🔧 force_cpu: Environment variables set for CPU-only mode")


def patch_torch():
    """
    Monkey-patch torch to disable MPS device detection.

    This prevents sentence-transformers from auto-detecting MPS
    and forcing CPU usage instead.
    """
    try:
        import torch
        print(f"🔧 force_cpu: torch {torch.__version__} imported successfully")
    except ImportError as e:
        print(f"🔧 force_cpu: torch not available, skipping patch: {e}")
        return

    try:
        import torch.backends.mps as mps

        # Save original function
        original_is_available = mps.is_available

        # Replace with function that always returns False
        def fake_is_available():
            return False

        mps.is_available = fake_is_available

        print("🔧 force_cpu: Patched torch.backends.mps.is_available() to return False")

    except (ImportError, AttributeError) as e:
        # torch.backends.mps doesn't exist (older torch version or non-Mac platform)
        print(f"🔧 force_cpu: torch.backends.mps not available: {e}")
    except Exception as e:
        print(f"⚠️  force_cpu: Unexpected error patching torch: {e}")


class _PatchingLoader(importlib.abc.Loader):
    """
    Wraps torch's real loader so patch_torch() runs once, right after
    torch's module body finishes executing -- not before, and not by
    importing torch ourselves to find out it exists.
    """

    def __init__(self, wrapped_loader, hook):
        self._wrapped = wrapped_loader
        self._hook = hook

    def create_module(self, spec):
        return self._wrapped.create_module(spec)

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        # The hook has done its job; remove it so it never runs twice and
        # never intercepts a later, unrelated "torch" lookup.
        if self._hook in sys.meta_path:
            sys.meta_path.remove(self._hook)
        patch_torch()


class TorchImportHook(importlib.abc.MetaPathFinder):
    """
    Patches torch the first time something actually imports it, without
    importing torch ourselves to set that up.

    Replaces the pre-3.12 find_module/load_module finder protocol (PEP 302),
    which Python 3.12 removed from importlib -- on 3.12+ that protocol is
    never invoked, so the old version of this hook never fired (confirmed by
    a stand-in test on 3.14; see SR-0,
    zz/startup-review-sr0-sr1-findings.md in puddlejump). find_spec is the
    protocol importlib has called since 3.4 and still calls on every later
    version, including 3.12+.
    """

    def find_spec(self, fullname, path, target=None):
        if fullname != 'torch':
            return None

        # Ask the rest of sys.meta_path for the real spec. Remove self first
        # so this lookup can't recurse back into this method.
        sys.meta_path.remove(self)
        try:
            spec = importlib.util.find_spec(fullname)
        finally:
            if self not in sys.meta_path:
                sys.meta_path.insert(0, self)

        if spec is None or spec.loader is None:
            return spec

        spec.loader = _PatchingLoader(spec.loader, self)
        return spec


def ensure_hook_installed():
    """
    Idempotent: installs TorchImportHook unless torch is already loaded or
    an instance of this hook is already on sys.meta_path. Safe to call from
    anywhere that wants "torch will be patched on first import" without
    importing torch to find out whether that's already arranged.
    """
    if 'torch' in sys.modules:
        return
    if any(isinstance(finder, TorchImportHook) for finder in sys.meta_path):
        return
    sys.meta_path.insert(0, TorchImportHook())
    print("🔧 force_cpu: Import hook installed to patch torch on first import")


# Patch torch if it's already imported; otherwise install the lazy hook.
if 'torch' in sys.modules:
    patch_torch()
else:
    ensure_hook_installed()


def patch_tqdm():
    """
    Completely disable tqdm to prevent threading crashes.

    tqdm's monitor threads cause segfaults with PyTorch on Apple Silicon.
    """
    try:
        import tqdm as tqdm_module

        # Create a no-op tqdm class
        class NoOpTqdm:
            def __init__(self, iterable=None, *args, **kwargs):
                self.iterable = iterable

            def __call__(self, iterable=None, *args, **kwargs):
                """Make it callable like tqdm(iterable)"""
                return NoOpTqdm(iterable, *args, **kwargs)

            def __iter__(self):
                return iter(self.iterable) if self.iterable else iter([])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def update(self, n=1):
                pass

            def close(self):
                pass

            def set_description(self, desc):
                pass

            def set_postfix(self, **kwargs):
                pass

        # Replace tqdm with no-op version
        tqdm_module.tqdm = NoOpTqdm
        if hasattr(tqdm_module, 'auto'):
            tqdm_module.auto.tqdm = NoOpTqdm

        print("🔧 force_cpu: Patched tqdm to no-op (disabled progress bars)")

    except ImportError:
        print("🔧 force_cpu: tqdm not installed, skipping patch")


# Patch tqdm if it's already imported
if 'tqdm' in sys.modules:
    patch_tqdm()


print("✅ force_cpu module loaded - MPS disabled, CPU-only mode enforced")
