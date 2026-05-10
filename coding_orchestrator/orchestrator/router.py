from __future__ import annotations

from coding_orchestrator.schemas import Complexity, RiskLevel, TaskSpec, WorkflowName


class TaskClassifier:
    def classify_task_type(self, task: TaskSpec) -> str:
        text = f"{task.title} {task.description}".lower()
        if "test" in text:
            return "write_tests"
        if any(word in text for word in ("bug", "fix", "error", "failure")):
            return "fix_bug"
        if "explain" in text or "document" in text:
            return "explain_code"
        if "security" in text:
            return "security_review"
        if "dependency" in text:
            return "dependency_update"
        if "refactor" in text:
            return "large_refactor" if task.complexity in {"hard", "critical"} else "small_refactor"
        return "fix_bug"

    def classify_complexity(self, task: TaskSpec) -> Complexity:
        if task.complexity:
            return task.complexity
        return "medium" if len(task.allowed_files) > 3 else "simple"

    def classify_risk(self, task: TaskSpec) -> RiskLevel:
        if task.risk:
            return task.risk
        return "high" if task.complexity in {"hard", "critical"} else "low"

    def select_workflow(self, task: TaskSpec) -> WorkflowName:
        task_type = self.classify_task_type(task)
        supported: set[str] = {
            "explain_code",
            "fix_bug",
            "write_tests",
            "small_refactor",
            "large_refactor",
            "architecture_review",
            "dependency_update",
            "security_review",
        }
        return task_type if task_type in supported else "fix_bug"  # type: ignore[return-value]

