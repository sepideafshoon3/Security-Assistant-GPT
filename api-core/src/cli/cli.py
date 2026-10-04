import argparse
import uuid
from pathlib import Path

from src.core.executor import Executor
from src.core.models import Task
from src.core.planner import Planner
from src.policies.loader import load_policy_engine
from src.security.audit import audit_log


def main() -> None:
    parser = argparse.ArgumentParser(description="Security Assistant GPT (lab) CLI")
    parser.add_argument(
        "repository_path",
        help="Path to repository inside lab scope",
    )
    args = parser.parse_args()

    base_dir = Path(__file__).resolve().parents[2]
    config_dir = base_dir / "config"
    reports_dir = base_dir / "data" / "reports"

    policy_engine = load_policy_engine(config_dir)

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        description="CLI-triggered analysis",
        repository_path=args.repository_path,
    )

    # Scope check first: it needs only the policy files, so an out-of-scope
    # path is rejected before anything heavier (e.g. the LLM client, which
    # requires OPENAI_API_KEY) is constructed.
    if not policy_engine.is_repository_in_scope(task.repository_path):
        audit_log(
            "repo_out_of_scope",
            {"task_id": task_id, "repository_path": task.repository_path},
        )
        raise SystemExit("Repository out of lab scope")

    planner = Planner()
    executor = Executor(
        reports_dir=reports_dir,
        config_dir=config_dir,
        policy_engine=policy_engine,
    )

    plan = planner.create_plan(task)
    report = executor.execute_plan(plan)

    print(f"[+] Task {task_id} completed.")
    print(report.summary)


if __name__ == "__main__":
    main()
