from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from coding_orchestrator.config import OpenCodeSettings
from coding_orchestrator.models.local_model import LocalModelPlaceholder
from coding_orchestrator.schemas import BuilderResult, TaskSpec
from coding_orchestrator.tools.shell import run_limited_command


class OpenCodeExecutionError(RuntimeError):
    pass


@dataclass
class OpenCodeRunner:
    repo_path: Path
    model_name: str = "opencode-local"
    settings: OpenCodeSettings | None = None

    def run_bounded_step(self, task: TaskSpec, context: str) -> BuilderResult:
        settings = self.settings or OpenCodeSettings()
        if settings.dry_run or not settings.enabled:
            response = LocalModelPlaceholder(self.model_name).complete(
                context + f"\nTask id: {task.id}"
            )
            return BuilderResult(
                text=response.text,
                confidence=response.confidence,
                estimated_output_tokens=response.estimated_output_tokens,
                dry_run=True,
            )

        executable = shutil.which(settings.executable)
        if executable is None:
            raise OpenCodeExecutionError(settings.missing_install_note)

        prompt = self._build_prompt(task, context, settings.output_mode)
        command = [executable, "run"]
        if settings.default_model:
            command.extend(["--model", settings.default_model])
        command.extend(settings.extra_args)
        command.append(prompt)

        env = self._filtered_env(settings.allowed_env_vars)
        result = run_limited_command(
            command,
            self.repo_path,
            settings.max_runtime_seconds,
            [executable],
            env=env,
        )
        if result.returncode != 0 or result.timed_out:
            message = result.stderr or result.stdout or "OpenCode execution failed"
            raise OpenCodeExecutionError(message)
        return BuilderResult(
            text=result.stdout,
            confidence=0.0,
            estimated_output_tokens=max(1, len(result.stdout) // 4),
            command=self._redacted_command(command),
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            timed_out=result.timed_out,
            runtime_seconds=result.runtime_seconds,
            dry_run=False,
        )

    def _build_prompt(self, task: TaskSpec, context: str, output_mode: str) -> str:
        contract = (
            "Return only a unified diff. Do not include prose, shell commands, markdown, "
            "or instructions outside the patch."
            if output_mode == "unified_diff"
            else (
                "Return only JSON with keys patch, touched_files, summary, confidence. "
                "The patch value must be a unified diff."
            )
        )
        return f"{context}\n\nOutput contract:\n{contract}\nTask id: {task.id}"

    def _filtered_env(self, allowed_names: list[str]) -> dict[str, str]:
        base_names = ["PATH", "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "TMPDIR"]
        names = [*base_names, *allowed_names]
        return {name: value for name in names if (value := os.environ.get(name)) is not None}

    def _redacted_command(self, command: list[str]) -> list[str]:
        return ["<opencode>" if index == 0 else part for index, part in enumerate(command)]
