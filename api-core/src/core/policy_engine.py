from pathlib import Path
from typing import Dict, Any

import yaml


class PolicyEngine:
    def __init__(self, policy_dir: Path):
        self.policy_dir = policy_dir
        self.policies = self._load_policies()

    def _load_policies(self) -> Dict[str, Any]:
        policies: Dict[str, Any] = {}
        for file in self.policy_dir.glob("*.yaml"):
            with file.open() as f:
                policies[file.stem] = yaml.safe_load(f) or {}
        return policies

    def is_action_allowed(self, action: str) -> bool:
        allowed_actions = self.policies.get("actions-allowed", {}).get("actions", [])
        return action in allowed_actions

    def requires_human_approval(self, action: str) -> bool:
        cfg = self.policies.get("actions-allowed", {})
        needs = cfg.get("requirements", {}).get("human_approval_for", [])
        return action in needs

    def is_repository_in_scope(self, repo_path: str) -> bool:
        scopes = self.policies.get("lab-scopes", {}).get("lab_scopes", {})
        allowed_repos = scopes.get("repositories", [])
        return any(repo_path.startswith(prefix) for prefix in allowed_repos)
