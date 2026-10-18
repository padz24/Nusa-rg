"""NUSA-RG - a coding assistant with local-project retrieval.

Public surface:
    ``from nusa_rg import CoreEngine, Config, ProjectIndex``
"""

__version__ = "1.3.0"

__all__ = ["CoreEngine", "Config", "ProjectIndex", "__version__"]


def __getattr__(name: str):
    # Lazy re-exports keep `import nusa_rg` cheap for `nusa-rg --version`.
    if name == "CoreEngine":
        from .engine import CoreEngine

        return CoreEngine
    if name == "Config":
        from .config import Config

        return Config
    if name == "ProjectIndex":
        from .rag import ProjectIndex

        return ProjectIndex
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")