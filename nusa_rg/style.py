"""Response styles: the default persona, and a telegraphic "caveman" mode.

The caveman mode is a native take on the Caveman skill for coding agents
(https://github.com/JuliusBrussee/caveman): cut the preamble, pleasantries,
and hedging that dominate output tokens, keep every technical fact. It is a
prompt-level style, so it works with every provider -- including the local
llama.cpp path -- and needs no plugin runtime.
"""

from __future__ import annotations

STYLES = ("default", "caveman")

CAVEMAN_RULES = (
    "Response style: telegraphic, like a terse senior engineer. "
    "Drop articles, filler, pleasantries, and hedging; fragments are fine; "
    "lead with the answer and stop once it is said. "
    "Keep code, commands, paths, identifiers, numbers, and error text exactly "
    "as they are -- never trade accuracy for brevity. "
    "Do not mention the style; just answer."
)


def apply(system_prompt: str, style: str = "default") -> str:
    """Append the style rules to the configured persona."""
    if style != "caveman":
        return system_prompt
    base = system_prompt.strip()
    return f"{base}\n\n{CAVEMAN_RULES}" if base else CAVEMAN_RULES


def describe(style: str) -> str:
    if style == "caveman":
        return "caveman (terse answers, code and facts untouched)"
    return "default"


__all__ = ["STYLES", "CAVEMAN_RULES", "apply", "describe"]
