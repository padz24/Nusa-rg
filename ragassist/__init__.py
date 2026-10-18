"""Termux RAG Assistant - a coding assistant with local-project retrieval.

Public surface:
    ``from ragassist import CoreEngine, Config, ProjectIndex``
"""

__version__ = "1.1.0"

__all__ = ["CoreEngine", "Config", "ProjectIndex", "__version__"]


def __getattr__(name: str):
    # Lazy re-exports keep `import ragassist` cheap for `rag-assist --version`.
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