from dataclasses import dataclass
from typing import Any, Callable

from app.agent.llm.base import LLMToolSchema
from app.agent.protocol import ToolCall, ToolResult, ToolRouteResult
from app.tools.project_progress import project_progress
from app.tools.risk_analysis import risk_analysis
from app.tools.project_documents import search_project_documents

ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    keywords: tuple[str, ...]
    handler: ToolHandler
    description: str
    parameters: dict[str, Any]

    def matches(self, message: str) -> bool:
        return any(keyword in message for keyword in self.keywords)

    def schema(self) -> LLMToolSchema:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRouter:
    """Register rule-based tools and route messages to their handlers."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register_tool(
            self,
            name: str,
            keywords: tuple[str, ...],
            handler: ToolHandler,
            description: str = "Execute a registered project assistant tool.",
            parameters: dict[str, Any] | None = None,
    ) -> None:
        self._tools[name] = ToolDefinition(
            name,
            keywords,
            handler,
            description,
            parameters or {
                "type": "object",
                "properties": {"project_id": {"type": "string"}},
                "required": ["project_id"],
                "additionalProperties": False,
            },
        )

    def select_tool(self, message: str) -> ToolDefinition | None:
        return next((tool for tool in self._tools.values() if tool.matches(message)), None)

    def execute_tool(self, tool: ToolDefinition, project_id: str) -> ToolRouteResult:
        if tool.name == "search_project_documents":
            result = tool.handler(
                "项目文档",
                project_id,
                5,
            )
        else:
            result = tool.handler(project_id)

        tool_call = ToolCall(
            tool=tool.name,
            arguments={
                "project_id": project_id,
                **(
                    {"query": "项目文档", "top_k": 5}
                    if tool.name == "search_project_documents"
                    else {}
                ),
            },
        )
        tool_result = ToolResult(
            tool=tool.name,
            result=result,
        )
        return ToolRouteResult(tool_call=tool_call, tool_result=tool_result)

    def tool_schemas(self, names: tuple[str, ...] | None = None) -> list[LLMToolSchema]:
        selected = self._tools.values() if names is None else (
            self._tools[name] for name in names if name in self._tools
        )
        return [tool.schema() for tool in selected]

    def execute_tool_call(self, tool_call: ToolCall) -> ToolResult:
        tool = self._tools.get(tool_call.tool)
        if tool is None:
            raise ValueError(f"Unknown tool requested: {tool_call.tool}")

        project_id = tool_call.arguments.get("project_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")

        if tool.name == "search_project_documents":
            query = tool_call.arguments.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ValueError(
                    "search_project_documents requires a non-empty query"
                )

            top_k = tool_call.arguments.get("top_k", 5)
            if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
                raise ValueError(
                    "search_project_documents requires a positive integer top_k"
                )

            file_id = tool_call.arguments.get("file_id")
            if file_id is not None and (
                    not isinstance(file_id, str) or not file_id.strip()
            ):
                raise ValueError("file_id must be a non-empty string when provided")

            original_filename = tool_call.arguments.get("original_filename")
            if original_filename is not None and (
                    not isinstance(original_filename, str) or not original_filename.strip()
            ):
                raise ValueError(
                    "original_filename must be a non-empty string when provided"
                )

            document_version = tool_call.arguments.get("document_version")
            if document_version is not None and (
                not isinstance(document_version, int)
                or isinstance(document_version, bool)
                or document_version <= 0
            ):
                raise ValueError("document_version must be a positive integer when provided")

            page_numbers = tool_call.arguments.get("page_numbers")
            if page_numbers is not None and (
                not isinstance(page_numbers, list)
                or not page_numbers
                or any(
                    not isinstance(page, int) or isinstance(page, bool) or page <= 0
                    for page in page_numbers
                )
            ):
                raise ValueError("page_numbers must be a non-empty list of positive integers when provided")
            handler_args = [
                query.strip(),
                project_id.strip(),
                top_k,
                file_id.strip() if isinstance(file_id, str) else None,
                original_filename.strip() if isinstance(original_filename, str) else None,
            ]
            if "is_current" in tool_call.arguments:
                is_current = tool_call.arguments["is_current"]
                if is_current is not None and not isinstance(is_current, bool):
                    raise ValueError("is_current must be a boolean when provided")
                handler_args.append(is_current)
            elif "document_version" in tool_call.arguments:
                handler_args.append(True)
            if "document_version" in tool_call.arguments:
                handler_args.append(document_version)

            result = (
                tool.handler(*handler_args, page_numbers=page_numbers)
                if page_numbers is not None
                else tool.handler(*handler_args)
            )
        else:
            result = tool.handler(project_id.strip())

        return ToolResult(tool=tool.name, result=result)

    def route(self, message: str, project_id: str) -> ToolRouteResult | None:
        tool = self.select_tool(message)
        return self.execute_tool(tool, project_id) if tool else None


tool_router = ToolRouter()
tool_router.register_tool(
    "project_progress",
    ("项目进度", "进度怎么样", "做到多少", "做到哪", "完成多少"),
    project_progress,
    description="查询指定工程项目的当前进度、阶段、状态和计划交付日期。",
    parameters={
        "type": "object",
        "properties": {"project_id": {"type": "string", "description": "工程项目 ID"}},
        "required": ["project_id"],
        "additionalProperties": False,
    },
)
tool_router.register_tool(
    "risk_analysis",
    ("项目风险", "项目有没有风险", "项目有什么风险", "识别一下项目风险", "分析一下项目风险"),
    risk_analysis,
    description="分析指定工程项目的工期、质量、成本风险，并返回整体风险等级。",
    parameters={
        "type": "object",
        "properties": {"project_id": {"type": "string", "description": "工程项目 ID"}},
        "required": ["project_id"],
        "additionalProperties": False,
    },
)
tool_router.register_tool(
    "search_project_documents",
(
    "项目文档",
    "文档中",
    "文档里",
    "这份文档",
    "根据文档",
    "查文档",
    "检索文档",
    "资料中",
    "文件中",
    "文件里",
    "这份文件",
    "PDF中",
    "PDF里",
    "这份PDF",
    "这个PDF",
    "根据PDF",
    ".pdf",
    ".doc",
    ".docx",
),
    search_project_documents,
    description="在指定工程项目的文档知识库中检索与问题最相关的内容。",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "用户要检索的项目文档问题",
            },
            "project_id": {
                "type": "string",
                "description": "工程项目 ID",
            },
            "top_k": {
                "type": "integer",
                "description": "返回最相关的文档片段数量",
                "default": 5,
                "minimum": 1,
            },
            "file_id": {
                "type": "string",
                "description": "指定文档的内部文件 ID；通常不需要用户提供。",
            },
            "original_filename": {
                "type": "string",
                "description": "用户明确指定的文档文件名，例如工程.pdf；未指定文件时留空。",
            },
            "is_current": {
                "type": "boolean",
                "description": "是否只检索当前文档版本；默认开启。",
                "default": True,
            },
            "document_version": {
                "type": "integer",
                "description": "指定文档版本；通常由 DocumentResolver 注入。",
                "minimum": 1,
            },
            "page_numbers": {
                "type": "array",
                "items": {"type": "integer", "minimum": 1},
                "description": "物理 PDF 页码；通常由系统根据用户原始请求注入。",
            },        },
        "required": ["query", "project_id"],
        "additionalProperties": False,
    },
)


