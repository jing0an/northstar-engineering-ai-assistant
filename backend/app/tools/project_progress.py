from typing import TypedDict


class ProjectProgress(TypedDict):
    project_name: str
    current_phase: str
    overall_progress: str
    planned_delivery: str
    current_status: str


def project_progress(project_id: str) -> ProjectProgress:
    """Return the current mock progress snapshot for a project."""
    return {
        "project_name": "我的工程项目",
        "current_phase": "施工图设计",
        "overall_progress": "68%",
        "planned_delivery": "2024 年 12 月 30 日",
        "current_status": "进行中",
    }
