from src.core.planner import Planner
from src.core.models import Task


def test_planner_creates_actions():
    planner = Planner()
    task = Task(
        id="test",
        description="Test task",
        repository_path="/lab/repos/demo",
    )
    plan = planner.create_plan(task)
    assert len(plan.actions) > 0
