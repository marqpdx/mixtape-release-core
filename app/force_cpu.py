"""
Force PyTorch to use CPU only - disable MPS and CUDA detection.

This module MUST be imported before any torch/transformers imports.
It monkey-patches torch to prevent MPS (Apple GPU) usage which causes crashes.

Usage:
    import force_cpu  # Must be first import!
    import torch
"""

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


# Patch torch if it's already imported
if 'torch' in sys.modules:
    patch_torch()
else:
    # Set up import hook to patch torch when it gets imported
    class TorchImportHook:
        def find_module(self, fullname, path=None):
            if fullname == 'torch':
                return self
            return None

        def load_module(self, fullname):
            if fullname in sys.modules:
                return sys.modules[fullname]

            # Remove self from meta_path to avoid recursion
            sys.meta_path.remove(self)

            # Import torch normally
            import torch

            # Patch it
            patch_torch()

            return torch

    # Install import hook
    sys.meta_path.insert(0, TorchImportHook())
    print("🔧 force_cpu: Import hook installed to patch torch on first import")


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
