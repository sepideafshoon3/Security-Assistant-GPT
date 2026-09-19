from __future__ import annotations

from src.core.models import Plan, PlannedAction, Task


class Planner:
    """
    Turns a high-level Task into a sequence of safe PlannedActions.
    """

    def create_plan(self, task: Task) -> Plan:
        actions: list[PlannedAction] = []

        # Very simple, deterministic planning
        actions.append(
            PlannedAction(
                action="run_semgrep",
                params={"repository_path": task.repository_path},
            )
        )
        actions.append(
            PlannedAction(
                action="run_bandit",
                params={"repository_path": task.repository_path},
            )
        )
        actions.append(
            PlannedAction(
                action="run_osv_scanner",
                params={"repository_path": task.repository_path},
            )
        )
        actions.append(
            PlannedAction(
                action="generate_report",
                params={"task_id": task.id},
            )
        )

        return Plan(task_id=task.id, actions=actions)
