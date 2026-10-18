"""Local execution path via a llama.cpp binary and a GGUF model (FR-07, AC-09).

Everything crossing the process boundary is built as an argument list and run
with ``shell=False``; user text is additionally filtered by
:mod:`ragassist.sanitize` so a pasted snippet can never become a command
(SEC-02, AC-23).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .. import sanitize
from .base import LLMClient, LLMResponse, LocalModelError, Usage


class LocalLLMRunner(LLMClient):
    """Runs a GGUF model locally through ``llama-cli`` / ``llama-completion``."""

    name = "local-llama.cpp"

    def __init__(
        self,
        model_path: str,
        *,
        binary: str = "llama-cli",
        ctx_size: int = 4096,
        threads: int | None = None,
        temperature: float = 0.2,
        timeout: int = 600,
        extra_args: list[str] | None = None,
    ):
        self.model_path = model_path or ""
        self.binary = binary or "llama-cli"
        self.ctx_size = ctx_size
        # llama.cpp defaults to all cores; on a phone that invites the
        # low-memory killer, so leave it unset unless the caller decides.
        self.threads = threads
        self.temperature = temperature
        self.timeout = timeout
        self.extra_args = list(extra_args or [])

    # ------------------------------------------------------------ discovery
    def resolve_binary(self) -> str | None:
        """Locate the llama.cpp executable (PATH first, then common paths)."""
        import shutil

        found = shutil.which(self.binary)
        if found:
            return found
        for candidate in (
            "~/llama.cpp/build/bin/llama-cli",
            "/data/data/com.termux/files/usr/bin/llama-cli",
            "/data/data/com.termux/files/usr/bin/llama-completion",
        ):
            path = Path(candidate).expanduser()
            if path.exists() and os.access(path, os.X_OK):
                return str(path)
        return None

    def model_exists(self) -> bool:
        if not self.model_path:
            return False
        return Path(self.model_path).expanduser().is_file()

    # -------------------------------------------------------------- command
    def build_command(
        self, binary: str, system: str, prompt: str
    ) -> list[str]:
        """Assemble the argument vector (never a shell string)."""
        command = [
            sanitize.sanitize_shell_arg(binary),
            "-m", sanitize.sanitize_shell_arg(self.model_path),
            "-c", str(int(self.ctx_size)),
            "-t", str(int(self.threads or os.cpu_count() or 4)),
            "--temp", str(self.temperature),
            "-n", "1024",
            "--no-display-prompt",
        ]
        if system:
            command += ["--system-prompt", sanitize.sanitize_shell_arg(system)]
        command += list(self.extra_args)
        command.append(sanitize.sanitize_shell_arg(prompt))
        return command

    # -------------------------------------------------------------- public
    def generate(
        self,
        prompt: str,
        *,
        context: str = "",
        system: str = "",
        stream: bool = False,
    ) -> LLMResponse:
        """Run one completion.

        Streaming is intentionally not implemented for the local path: the
        binary is invoked once per turn and its stdout is collected, which is
        simpler and more predictable than emulating incremental output.
        """
        binary = self.resolve_binary()
        if not binary:
            raise LocalModelError(
                f"llama.cpp binary '{self.binary}' not found. Build llama.cpp for "
                "ARM64 or set local_llama_bin in config.yaml."
            )
        if not self.model_exists():
            raise LocalModelError(
                f"local model not found: {self.model_path}. Set local_model_path "
                "in config.yaml."
            )

        user = f"{context}\n\n{prompt}" if context else prompt
        command = self.build_command(binary, system, user)

        try:
            completed = subprocess.run(  # noqa: S603 - shell=False, argv list
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LocalModelError(
                f"local model timed out after {self.timeout}s. Try a smaller "
                "ctx_size or a quantised GGUF."
            ) from exc
        except OSError as exc:
            raise LocalModelError(f"cannot execute llama.cpp: {exc}") from exc

        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip().splitlines()
            detail = stderr[-1] if stderr else f"exit code {completed.returncode}"
            raise LocalModelError(f"llama.cpp failed: {detail}")

        return LLMResponse(
            text=(completed.stdout or "").strip(),
            # llama-cli does not report token usage on stdout.
            usage=Usage(),
            provider=self.name,
        )

    def health_check(self) -> tuple[bool, str]:
        """Verify the binary and model are usable before a chat starts (AC-09)."""
        binary = self.resolve_binary()
        if not binary:
            return False, (
                f"llama.cpp binary '{self.binary}' not found on PATH"
            )
        if not self.model_path:
            return False, "local_model_path is not set"
        if not self.model_exists():
            return False, f"local model not found: {self.model_path}"
        size_mb = Path(self.model_path).expanduser().stat().st_size / (1024 * 1024)
        return True, f"llama.cpp ready, model={Path(self.model_path).name} ({size_mb:.0f} MB)"


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for budget checks on mobile."""
    return max(1, len(text) // 4)


__all__ = ["LocalLLMRunner", "estimate_tokens"]