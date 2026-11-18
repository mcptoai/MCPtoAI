"""Alias canonical shared-core activity module (including private test hooks)."""
import sys
from mcptoai_core import activity_store as _module
sys.modules[__name__] = _module
