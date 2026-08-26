# src/core/executor.py

from pathlib import Path
from typing import List

from src.core.models import Plan, ToolResult, Report
from src.core.policy_engine import PolicyEngine
from src.tools.semgrep_runner import run_semgrep
from src.tools.bandit_runner import run_bandit
from src.tools.osv_runner import run_osv_scanner
from src.security.audit import audit_log

# NEW
from src.llm.openai_client import load_llm_config
from src.llm.router import create_advisor


class Executor:
    def __init__(self, reports_dir: Path, config_dir: Path):
        self.reports_dir = reports_dir
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # NEW: LLM advisor (OpenAI or xAI via central router)
        llm_config = load_llm_config(config_dir)
        self.llm_advisor = create_advisor(llm_config)

    def execute_plan(self, plan: Plan) -> Report:
        results: List[ToolResult] = []

        for action in plan.actions:
            if self.policy_engine.requires_human_approval(action.action):
                audit_log("human_approval_required", {"action": action.action})
                # hook for real approval mechanism

            if action.action == "run_semgrep":
                result = run_semgrep(action.params["repository_path"], self.reports_dir)
            elif action.action == "run_bandit":
                result = run_bandit(action.params["repository_path"], self.reports_dir)
            elif action.action == "run_osv_scanner":
                result = run_osv_scanner(
                    action.params["repository_path"], self.reports_dir
                )
            elif action.action == "generate_report":
                # placeholder; LLM advisor runs after loop
                result = ToolResult(
                    action="generate_report",
                    success=True,
                    output_path=str(self.reports_dir / f"{plan.task_id}-summary.txt"),
                )
            else:
                result = ToolResult(
                    action=action.action,
                    success=False,
                    errors="Unknown action.",
                )

            results.append(result)
            audit_log("action_executed", result.model_dump())

        # === NEW: ask LLM for a defensive report ===
        llm_summary = self.llm_advisor.generate_defensive_report(
            plan.task_id, results
        )

        summary_path = self.reports_dir / f"{plan.task_id}-summary.txt"
        summary_path.write_text(llm_summary)

        summary = "Plan executed with {success}/{total} successes.".format(
            success=sum(1 for r in results if r.success),
            total=len(results),
        )
        return Report(task_id=plan.task_id, results=results, summary=summary)
