"""
Utility module for testing notebooks to handle imports and common setup.
"""

import sys
import os
from pathlib import Path


def setup_imports():
    """Add the backend root directory to Python path for imports."""
    backend_root = Path(__file__).parent.parent
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))
    return backend_root


def get_backend_root():
    """Get the path to the backend root directory."""
    return Path(__file__).parent.parent


# Automatically setup imports when this module is imported
setup_imports()
