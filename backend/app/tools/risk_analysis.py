from typing import TypedDict


class Risk(TypedDict):
    type: str
    level: str
    description: str


class RiskAnalysis(TypedDict):
    project_id: str
    risk_level: str
    risks: list[Risk]


def risk_analysis(project_id: str) -> RiskAnalysis:
    """Return a fixed mock risk snapshot for a project."""
    return {
        "project_id": project_id,
        "risk_level": "中",
        "risks": [
            {
                "type": "工期",
                "level": "中",
                "description": "施工图设计阶段存在节点延期风险。",
            },
            {
                "type": "质量",
                "level": "低",
                "description": "当前暂无重大质量风险。",
            },
            {
                "type": "成本",
                "level": "低",
                "description": "当前暂无明显成本超支风险。",
            },
        ],
    }
