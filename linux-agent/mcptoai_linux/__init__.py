"""MCPtoAI Linux agent."""
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcptoai")
except PackageNotFoundError:
    # Source checkout without installed distribution: no misleading hardcoded version.
    __version__ = "0+uninstalled"
