import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from app.agent.llm import create_llm_provider
from app.agent.llm.base import LLMMessage, LLMProvider
from app.agent.protocol import AgentMessage, ToolCall, ToolRouteResult
from app.services.citation import build_citations
from app.services.document_resolver import (
    CONTEXTUAL_DOCUMENT_REFERENCE_PATTERN,
    DocumentCandidate,
    DocumentResolution,
    DocumentResolver,
)
from app.services.assistant_errors import (
    AssistantServiceError,
    citation_generation_failed,
    internal_error,
    llm_unavailable,
    rag_unavailable,
)
from app.services.page_range import (
    DocumentPageMapping,
    has_page_range_reference,
    mapping_from_metadata,
    pdf_page_mapping,
    resolve_page_numbers,
)
from app.tool_router import tool_router

MAX_TOOL_ITERATIONS = 5
MAX_DOCUMENT_SEARCHES = 3


class AssistantResult(TypedDict, total=False):
    reply: str
    status: str
    tool: str
    citations: list[dict[str, Any]]
    sources: list[dict[str, Any]]


def _no_evidence_result(reply: str) -> AssistantResult:
    """Return a deterministic document-answer boundary with no evidence."""
    return {
        "status": "no_evidence",
        "reply": reply,
        "citations": [],
        "sources": [],
    }


def _generate_with_tools(
        llm_provider: LLMProvider,
        messages: list[LLMMessage],
        tool_schemas: list[Any],
):
    """Keep provider failures out of ordinary Assistant reply payloads."""
    try:
        return llm_provider.generate_with_tools(messages, tool_schemas)
    except AssistantServiceError:
        raise
    except Exception as error:
        raise llm_unavailable() from error


@dataclass
class AgentContext:
    """Lightweight per-conversation state for the last resolved document."""

    last_referenced_document: DocumentCandidate | None = None
    current_project_id: str | None = None


AgentContextKey = tuple[str, str, str]

_AGENT_CONTEXTS: dict[AgentContextKey, AgentContext] = {}
_LEGACY_CONTEXT_ID = "__legacy_direct_call__"
_DOCUMENT_REFERENCE_RE = re.compile(
    rf"(?:\.(?:pdf|docx)\b|第\s*(?:[0-9]+|[一二三四五六七八九十百千万零〇两]+)\s*(?:版|个文件|份(?:\s*PDF)?|个文档)|\b[vV]\s*[0-9]+\b|版本\s*(?:[0-9]+|[一二三四五六七八九十百千万零〇两]+)|最新版|最新版本|最新的|最新那个|当前版本|当前文件|现在这份|现在这个版本|最新文件|刚上传|上一版|上一版本|上一个版本|之前那个版本|带页码|有页码|没有页码|无页码|{CONTEXTUAL_DOCUMENT_REFERENCE_PATTERN})"
)


def _contains_document_reference(message: str) -> bool:
    return bool(_DOCUMENT_REFERENCE_RE.search(message))


def _document_page_mapping(document: DocumentCandidate) -> DocumentPageMapping | None:
    """Load a verified display-to-physical mapping for one resolved document."""
    metadata_mapping = mapping_from_metadata(document.metadata)
    if metadata_mapping is not None:
        return metadata_mapping
    if str(document.metadata.get("file_type", "")).casefold() != "pdf":
        return None
    stored_filename = document.metadata.get("stored_filename")
    if not isinstance(stored_filename, str) or Path(stored_filename).name != stored_filename:
        return None
    try:
        from app.services.file_storage import file_storage

        path = Path(file_storage.storage_root) / document.project_id / stored_filename
        return pdf_page_mapping(path)
    except OSError:
        return None

def _load_default_document_resolver(project_id: str) -> DocumentResolver:
    """Load local metadata only when a document reference needs resolving."""
    try:
        from app.services.file_storage import file_storage

        metadata_path = Path(file_storage.storage_root) / project_id / "metadata.json"
        loaded = json.loads(metadata_path.read_text(encoding="utf-8"))
        records = loaded if isinstance(loaded, list) else []
    except (OSError, json.JSONDecodeError):
        records = []
    return DocumentResolver(record for record in records if isinstance(record, dict))


def _resolution_reply(resolution: DocumentResolution, query: str) -> str:
    if resolution.status == "ambiguous":
        names = sorted({item.original_filename for item in resolution.candidates})
        if names:
            return f"目前有多个文档符合“{query}”，请指定文件名或版本，例如“最新版{names[0]}”。"
        return f"目前有多个文档符合“{query}”，请指定文件名或版本。"
    if resolution.status == "not_found":
        return f"没有找到与“{query}”匹配的文档或版本。"
    if resolution.status == "insufficient_context":
        return "我需要你先指定一下文档，或者告诉我文件名/版本。"
    if resolution.status == "unsupported":
        return "暂不支持解析这种文档引用，请提供文件名或明确版本。"
    return ""


def _progress_reply(result: dict[str, Any]) -> str:
    return (
        f"{result['project_name']}目前处于{result['current_phase']}阶段，"
        f"整体进度为 {result['overall_progress']}，当前状态为{result['current_status']}，"
        f"计划交付日期为 {result['planned_delivery']}。"
    )


def _risk_reply(result: dict[str, Any]) -> str:
    return (
        "目前我的工程项目整体风险等级为"
        f"{result['risk_level']}。主要需要关注施工图设计阶段的工期风险；"
        "当前暂无重大质量和明显成本超支风险。"
    )


TOOL_REPLY_BUILDERS = {
    "project_progress": _progress_reply,
    "risk_analysis": _risk_reply,
}


def _normalize_search_query(query: Any) -> str:
    """Normalize formatting-only query differences for duplicate detection."""
    if not isinstance(query, str):
        return ""
    normalized = unicodedata.normalize("NFKC", query).casefold()
    return re.sub(r"[\W_]+", "", normalized, flags=re.UNICODE)


def _tool_result_for_llm(
        tool_result_data: dict[str, Any],
        page_mapping: DocumentPageMapping | None,
) -> dict[str, Any]:
    """Provide the LLM a public page view without physical retrieval metadata."""
    results = tool_result_data.get("results")
    if not isinstance(results, list):
        return tool_result_data

    display_results: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        metadata = result.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        item: dict[str, Any] = {
            "original_filename": result.get("original_filename") or metadata.get("original_filename"),
            "document_version": metadata.get("document_version"),
            "text": result.get("text", ""),
        }
        physical_page = result.get("page_number")
        if page_mapping is not None:
            display_page = page_mapping.to_display(physical_page) if isinstance(physical_page, int) else None
            if display_page is not None:
                item["display_page_number"] = display_page
        elif isinstance(physical_page, int) and physical_page > 0:
            item["page_number"] = physical_page
        display_results.append(item)

    return {
        "query": tool_result_data.get("query"),
        "page_filter_applied": tool_result_data.get("page_filter_applied", False),
        "message": tool_result_data.get("message"),
        "results": display_results,
    }

def _build_assistant_result(
        reply: str,
        last_tool: str | None,
        collected_citations: list[dict[str, Any]],
) -> AssistantResult:
    result: AssistantResult = {"status": "answered", "reply": reply}
    if last_tool is not None:
        result["tool"] = last_tool
    if collected_citations:
        result["citations"] = collected_citations
        result["sources"] = collected_citations
    return result


def _force_final_answer(
        messages: list[LLMMessage],
        tool_schemas: list[Any],
        llm_provider: LLMProvider,
        last_tool: str | None,
        collected_citations: list[dict[str, Any]],
) -> AssistantResult:
    """Ask for text only after document-search safety limits are reached."""
    messages.append(
        {
            "role": "system",
            "content": (
                "请停止调用工具，仅基于已经获得的检索结果回答用户；"
                "不要编造检索结果中不存在的数据。"
            ),
        }
    )
    response = _generate_with_tools(llm_provider, messages, tool_schemas)
    return _build_assistant_result(
        response.content or "根据已检索内容无法形成完整回答。",
        last_tool,
        collected_citations,
    )


def _process_with_llm(
        user_message: AgentMessage,
        project_id: str,
        llm_provider: LLMProvider,
        resolved_document: DocumentCandidate | None = None,
        page_numbers: list[int] | None = None,
        page_mapping: DocumentPageMapping | None = None,
) -> AssistantResult:
    """Run the provider/router/tool loop until the provider returns text."""
    # The router is the source of truth for both schemas and the allowlist.
    tool_schemas = tool_router.tool_schemas()
    allowed_tools = {
        schema["function"]["name"]
        for schema in tool_schemas
        if schema.get("type") == "function"
    }
    messages: list[LLMMessage] = [
        {
            "role": "system",
            "content": (
                f"当前项目 ID 为 {project_id}。调用项目工具时必须使用该项目 ID；"
                "不要因为用户没有在自然语言中提供项目 ID 而再次询问用户。"

                "如果用户明确提到某个文档文件名，例如“工程.pdf”，"
                "调用 search_project_documents 时必须将该文件名作为 original_filename 传入。"
                "如果用户没有指定具体文件，则不要填写 original_filename。"

                "回答项目文档问题时，必须以实际检索到的文档内容为唯一事实依据。"
                "不得编造、补充或推测检索结果中不存在的事实。"
                "如果文档内容不足以回答用户的问题，应明确说明文档中没有找到足够的信息，"
                "不要使用常识或猜测补全答案。"

                "引用文档内容时，优先使用检索结果提供的来源文件名和 page_number。"
                "引用格式统一为：来源：《文件名》，第 X 页。"
                "如果同一条信息来自多个连续页面，可以写为：来源：《文件名》，第 X-X 页。"
                "如果检索结果没有可靠的 page_number，则只标明来源文件名，绝对不要自行推测或编造页码。"

                "如果检索到了多个文件，必须明确区分不同文件的内容，"
                "不得把不同文件的内容混合后当成同一份文档的内容。"

                "如果用户要求“只根据这份 PDF”或明确指定某个文件，"
                "只能使用该文件的检索结果回答，不得引用其他文件。"

                "如果文档中存在内容混杂、结构异常或看起来不一致的情况，"
                "除非文档明确说明原因，否则不要推测这是文件错误、拼接错误或不同文档混合；"
                "只客观描述检索到的内容。"

                "当检索结果提供 display_page_number 时，它是唯一可向用户展示的正文页码；"
                "不得使用或展示内部物理页号。"
                "页码只能来自检索结果中的 page_number 字段；"
                "不得根据上下文、chunk 顺序、章节顺序、前后页关系或常识推断页码。"
                "如果某项内容的检索结果没有 page_number，则该项只能引用文件名，不能写“第X页”“第X-X页”“X页附近”“大约第X页”等任何推测性页码。"

                "回答用户问题时统一使用 Markdown 格式组织内容。"
                "不要把所有内容写成一整段连续文字。"
                "需要分步骤、分事项说明时，使用 Markdown 标题和列表进行分段。"
                "多个并列事项优先使用无序列表或有序列表。"
                "重要结论、关键数字和关键状态可以使用 Markdown 粗体突出。"
                "当需要比较多项数据时，可以使用 Markdown 表格。"
                "来源信息单独放在回答末尾，不要把来源说明混在正文中。"
                "不要输出 Markdown 原始语法之外的特殊格式标记。"
                "绝对不要向用户展示内部技术字段，包括 file_id、chunk_id、project_id、score 等。"
                "这些内部字段只能用于系统内部处理，不能出现在最终回答中。"

            ),
        },
        {"role": user_message.role, "content": user_message.content},
    ]
    if resolved_document is not None:
        messages.insert(
            1,
            {
                "role": "system",
                "content": (
                    "DocumentResolver 已明确确定本轮文档引用为："
                    f"《{resolved_document.original_filename}》，"
                    f"版本 {resolved_document.document_version or '未知'}。"
                    "请接受这一确定结果，不要自行猜测其他文件或版本。"
                ),
            },
        )

    last_tool: str | None = None
    collected_citations: list[dict[str, Any]] = []
    executed_search_queries: set[str] = set()
    document_search_count = 0
    retrieval_result_count = 0

    for iteration in range(MAX_TOOL_ITERATIONS):
        response = _generate_with_tools(llm_provider, messages, tool_schemas)
        tool_calls = response.tool_calls or []
        if not tool_calls:
            return _build_assistant_result(
                response.content or "",
                last_tool,
                collected_citations,
            )

        # Validate the complete batch before executing anything. This avoids
        # partial execution if one call in a multi-call response is invalid.
        unknown_call = next(
            (call for call in tool_calls if call.tool not in allowed_tools), None
        )
        if unknown_call is not None:
            raise internal_error()

        # Normalize every call against the request context before either
        # serializing it for the next LLM round or executing it in the router.
        normalized_calls: list[ToolCall] = []
        for call in tool_calls:
            arguments = dict(call.arguments)
            requested_project_id = arguments.get("project_id")
            if requested_project_id is None:
                arguments["project_id"] = project_id
            elif requested_project_id != project_id:
                raise internal_error()
            if resolved_document is not None and call.tool == "search_project_documents":
                # Resolver is authoritative; never let the LLM broaden a resolved search.
                arguments["file_id"] = resolved_document.file_id
                arguments["document_version"] = resolved_document.document_version
                arguments["original_filename"] = resolved_document.original_filename
                arguments["is_current"] = resolved_document.is_current
                if page_numbers is not None:
                    arguments["page_numbers"] = page_numbers
            elif call.tool == "search_project_documents":
                # Only DocumentResolver may authorize a historical version.
                arguments["is_current"] = True
            normalized_calls.append(
                call.model_copy(update={"arguments": arguments})
            )

        call_ids: list[str] = []
        assistant_tool_calls: list[dict[str, Any]] = []
        for index, call in enumerate(normalized_calls, start=1):
            call_id = call.call_id or f"tool-call-{iteration + 1}-{index}"
            call_ids.append(call_id)
            assistant_tool_calls.append(
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": call.tool,
                        "arguments": json.dumps(
                            call.arguments, ensure_ascii=False
                        ),
                    },
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
                "tool_calls": assistant_tool_calls,
            }
        )

        force_final_answer = False
        for call, call_id in zip(normalized_calls, call_ids):
            skipped_search = False
            if call.tool == "search_project_documents":
                normalized_query = _normalize_search_query(
                    call.arguments.get("query")
                )
                if normalized_query in executed_search_queries:
                    skipped_search = True
                    force_final_answer = True
                    skip_reason = "duplicate_query"
                elif document_search_count >= MAX_DOCUMENT_SEARCHES:
                    skipped_search = True
                    force_final_answer = True
                    skip_reason = "search_limit"

                if skipped_search:
                    tool_result_data = {
                        "query": call.arguments.get("query"),
                        "skipped": True,
                        "reason": skip_reason,
                        "message": (
                            "该检索 query 已执行过，请基于已有结果回答。"
                            if skip_reason == "duplicate_query"
                            else "已达到文档检索次数上限，请基于已经获得的检索结果回答。"
                        ),
                        "results": [],
                        "citations": [],
                        "sources": [],
                    }
                else:
                    try:
                        tool_result = tool_router.execute_tool_call(call)
                    except AssistantServiceError:
                        raise
                    except ValueError as error:
                        raise internal_error() from error
                    except Exception as error:
                        raise rag_unavailable() from error
                    tool_result_data = tool_result.result
                    document_search_count += 1
                    if normalized_query:
                        executed_search_queries.add(normalized_query)
            else:
                try:
                    tool_result = tool_router.execute_tool_call(call)
                except AssistantServiceError:
                    raise
                except ValueError as error:
                    raise internal_error() from error
                except Exception as error:
                    raise internal_error() from error
                tool_result_data = tool_result.result

            last_tool = call.tool

            if call.tool == "search_project_documents":
                raw_results = tool_result_data.get("results", [])
                if isinstance(raw_results, list):
                    retrieval_result_count += len(raw_results)
                    if not raw_results and not skipped_search and retrieval_result_count == 0:
                        return _no_evidence_result(
                            "当前项目资料中没有找到足够依据回答这个问题。"
                        )
                    try:
                        citations = build_citations(
                            raw_results,
                            expected_document=resolved_document,
                            page_mapping=page_mapping,
                        )
                    except Exception as error:
                        raise citation_generation_failed() from error
                    for citation in citations:
                        value = citation.model_dump()
                        key = (
                            value["original_filename"],
                            value.get("document_version"),
                            value.get("page_number"),
                        )
                        existing_keys = {
                            (
                                item.get("original_filename"),
                                item.get("document_version"),
                                item.get("page_number"),
                            )
                            for item in collected_citations
                        }
                        if key not in existing_keys:
                            collected_citations.append(value)
                    collected_citations.sort(
                        key=lambda item: (
                            item.get("original_filename", ""),
                            item.get("document_version") or 0,
                            item.get("page_number") or 0,
                        )
                    )

            messages.append(
                {
                    "role": "tool",
                    "content": json.dumps(
                        _tool_result_for_llm(tool_result_data, page_mapping),
                        ensure_ascii=False,
                    ),
                    "tool_call_id": call_id,
                }
            )

        if force_final_answer:
            return _force_final_answer(
                messages,
                tool_schemas,
                llm_provider,
                last_tool,
                collected_citations,
            )

    if retrieval_result_count > 0:
        return _force_final_answer(
            messages,
            tool_schemas,
            llm_provider,
            last_tool,
            collected_citations,
        )

    raise internal_error()


def process_message(
        message: str,
        project_id: str,
        llm_provider: LLMProvider | None = None,
        document_resolver: DocumentResolver | None = None,
        agent_context: AgentContext | None = None,
        *,
        user_id: str | None = None,
        conversation_id: str | None = None,
) -> AssistantResult:
    """Resolve document references, then preserve the existing Agent flow."""

    user_message = AgentMessage(role="user", content=message)
    provider_was_injected = llm_provider is not None
    if agent_context is not None:
        context = agent_context
    else:
        if (user_id is None) != (conversation_id is None):
            raise ValueError("user_id and conversation_id must be provided together")
        context_key = (
            str(user_id) if user_id is not None else _LEGACY_CONTEXT_ID,
            project_id,
            str(conversation_id) if conversation_id is not None else _LEGACY_CONTEXT_ID,
        )
        context = _AGENT_CONTEXTS.setdefault(context_key, AgentContext())
    if context.current_project_id != project_id:
        context.current_project_id = project_id
        context.last_referenced_document = None

    # Explicit document references must be resolved before the document tool
    # route, so the legacy route cannot trigger retrieval or guess a version.
    page_reference_requested = has_page_range_reference(user_message.content)
    is_document_reference = _contains_document_reference(user_message.content)
    if page_reference_requested and not is_document_reference:
        return _no_evidence_result(
            "我需要你先指定一下文档，或者告诉我文件名/版本。"
        )
    tool_route = None
    if not is_document_reference:
        selected_tool = tool_router.select_tool(user_message.content)
        if selected_tool is not None and selected_tool.name in {
            "project_progress", "risk_analysis",
        }:
            tool_route = tool_router.execute_tool(selected_tool, project_id)
    if (
        not provider_was_injected
        and tool_route is not None
        and tool_route.tool_call.tool in {"project_progress", "risk_analysis"}
    ):
        builder = TOOL_REPLY_BUILDERS.get(tool_route.tool_call.tool)
        if builder is not None:
            return {
                "status": "answered",
                "tool": tool_route.tool_call.tool,
                "reply": builder(tool_route.tool_result.result),
            }

    resolved_document: DocumentCandidate | None = None
    if is_document_reference:
        resolver = document_resolver or _load_default_document_resolver(project_id)
        resolution = resolver.resolve(
            user_message.content,
            project_id,
            previous_document=context.last_referenced_document,
        )
        if resolution.status != "resolved":
            return _no_evidence_result(
                _resolution_reply(resolution, user_message.content)
            )
        resolved_document = resolution.selected_document
        if resolved_document is not None:
            if resolved_document.project_id != project_id:
                return _no_evidence_result(
                    "文档引用与当前项目不一致，请指定当前项目中的文档。"
                )
            context.last_referenced_document = resolved_document

    page_numbers: list[int] | None = None
    page_mapping: DocumentPageMapping | None = None
    if page_reference_requested and resolved_document is not None:
        page_mapping = _document_page_mapping(resolved_document)
        if page_mapping is None:
            return _no_evidence_result(
                "无法根据该文档的可靠页码信息确定正文页码映射。"
            )
        display_page_numbers = resolve_page_numbers(
            user_message.content,
            page_mapping.max_display_page_number,
        )
        page_numbers = (
            page_mapping.to_physical(display_page_numbers)
            if display_page_numbers is not None
            else None
        )
        if page_numbers is None:
            return _no_evidence_result(
                "指定的正文页码不在该文档的可靠页码映射范围内。"
            )

    if llm_provider is None:
        try:
            llm_provider = create_llm_provider()
        except Exception as error:
            raise llm_unavailable() from error

    if llm_provider is not None:
        return _process_with_llm(
            user_message,
            project_id,
            llm_provider,
            resolved_document,
            page_numbers,
            page_mapping,
        )

    if tool_route is None:
        raise llm_unavailable()

    reply_builder = TOOL_REPLY_BUILDERS[tool_route.tool]
    return {
        "status": "answered",
        "reply": reply_builder(tool_route.tool_result.result),
        "tool": tool_route.tool,
    }







