import argparse
from pathlib import Path
import uuid

from src.core.models import Task
from src.core.planner import Planner
from src.core.executor import Executor
from src.policies.loader import load_policy_engine
from src.security.audit import audit_log


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Security Assistant GPT (lab) CLI"
    )
    parser.add_argument(
        "repository_path",
        help="Path to repository inside lab scope",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[2]
    config_dir = base_dir / "config"
    reports_dir = base_dir / "data" / "reports"

    planner = Planner()
    policy_engine = load_policy_engine(config_dir)
    executor = Executor(policy_engine=policy_engine, reports_dir=reports_dir)

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        description="CLI-triggered analysis",
        repository_path=args.repository_path,
    )

    if not policy_engine.is_repository_in_scope(task.repository_path):
        audit_log(
            "repo_out_of_scope",
            {"task_id": task_id, "repository_path": task.repository_path},
        )
        raise SystemExit("Repository out of lab scope")

    plan = planner.create_plan(task)
    report = executor.execute_plan(plan)

    print(f"[+] Task {task_id} completed.")
    print(report.summary)


if __name__ == "__main__":
    main()
