"""Resolve natural-language document references against project metadata."""

from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ResolutionStatus = Literal["resolved", "ambiguous", "not_found", "unsupported", "insufficient_context"]


class DocumentCandidate(BaseModel):
    """A document version exposed to the resolver internally."""

    model_config = ConfigDict(extra="allow")

    file_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    original_filename: str = Field(min_length=1)
    document_version: int | None = Field(default=None, ge=1)
    is_current: bool | None = None
    is_duplicate: bool = False
    duplicate_of_file_id: str | None = None
    uploaded_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_metadata(cls, value: Mapping[str, Any]) -> "DocumentCandidate":
        if not isinstance(value, Mapping):
            raise ValueError("document metadata must be a mapping")
        filename = value.get("original_filename", value.get("filename"))
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("document metadata requires original_filename")
        file_id = value.get("file_id")
        project_id = value.get("project_id")
        if not isinstance(file_id, str) or not file_id.strip():
            raise ValueError("document metadata requires file_id")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("document metadata requires project_id")
        version = value.get("document_version")
        if isinstance(version, bool) or (version is not None and not isinstance(version, int)):
            version = None
        current = value.get("is_current")
        if not isinstance(current, bool):
            current = None
        duplicate = value.get("is_duplicate")
        if not isinstance(duplicate, bool):
            duplicate = False
        duplicate_of = value.get("duplicate_of_file_id")
        if not isinstance(duplicate_of, str) or not duplicate_of.strip():
            duplicate_of = None
        uploaded = value.get("uploaded_at")
        if uploaded is not None and not isinstance(uploaded, str):
            uploaded = None
        return cls(
            file_id=file_id.strip(),
            project_id=project_id.strip(),
            original_filename=filename.strip(),
            document_version=version,
            is_current=current,
            is_duplicate=duplicate,
            duplicate_of_file_id=duplicate_of.strip() if duplicate_of else None,
            uploaded_at=uploaded,
            metadata=dict(value),
        )


class DocumentResolution(BaseModel):
    """The result of resolving a document reference."""

    status: ResolutionStatus
    selected_document: DocumentCandidate | None = None
    candidates: list[DocumentCandidate] = Field(default_factory=list)
    matched_by: str | None = None
    explanation: str


_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_TOKEN = r"(?:[0-9]+|[一二三四五六七八九十百千万零〇两]+)"
_VERSION_RE = re.compile(
    rf"(?:第\s*(?P<ordinal>{_TOKEN})\s*版|版本\s*(?P<label>{_TOKEN})|(?<![A-Za-z0-9_])v\s*(?P<v>[0-9]+)(?![A-Za-z0-9_]))",
    re.IGNORECASE,
)
_ORDINAL_RE = re.compile(
    rf"第\s*(?P<number>{_TOKEN})\s*(?:个|份)\s*(?P<kind>pdf|文档|文件)?",
    re.IGNORECASE,
)
CONTEXTUAL_DOCUMENT_REFERENCE_PATTERN = (
    r"(?:刚才那个|刚才的文件|刚才那份文件|刚才那份报告|上一个|之前那个|"
    r"前一个文件|这份文件|这个文件|它|当前文件|现在这份|现在这个版本)"
)
_CONTEXTUAL_DOCUMENT_REFERENCE_RE = re.compile(
    CONTEXTUAL_DOCUMENT_REFERENCE_PATTERN,
    re.IGNORECASE,
)


def chinese_number(value: str) -> int | None:
    """Convert Arabic or common Chinese numerals used in references."""
    token = value.strip()
    if token.isdigit():
        number = int(token)
        return number if number > 0 else None
    if not token or any(char not in _CN_DIGITS and char not in _CN_UNITS for char in token):
        return None
    total = 0
    section = 0
    number = 0
    for char in token:
        if char in _CN_DIGITS:
            number = _CN_DIGITS[char]
            continue
        unit = _CN_UNITS[char]
        if unit == 10000:
            section += number
            total += (section or 1) * unit
            section = 0
            number = 0
        elif number:
            section += number * unit
            number = 0
        else:
            section += unit
    result = total + section + number
    return result if result > 0 else None


class DocumentResolver:
    """Resolve references without making external calls or changing storage."""

    def __init__(self, documents: Iterable[DocumentCandidate | Mapping[str, Any]]) -> None:
        all_documents = [
            item if isinstance(item, DocumentCandidate) else DocumentCandidate.from_metadata(item)
            for item in documents
        ]
        by_id = {item.file_id: item for item in all_documents}
        for item in all_documents:
            if not item.is_duplicate:
                continue
            target_id = item.duplicate_of_file_id
            target = by_id.get(target_id) if target_id else None
            if target is None or target.project_id != item.project_id or target.file_id == item.file_id or target.is_duplicate:
                raise ValueError(
                    "duplicate_of_file_id must reference a different file in the same project"
                )
        # Duplicate uploads remain in local metadata, but are not business
        # document candidates for version, ordinal, latest, or filename lookup.
        self.documents = [item for item in all_documents if not item.is_duplicate]

    @staticmethod
    def _timestamp(candidate: DocumentCandidate) -> float | None:
        if not candidate.uploaded_at:
            return None
        try:
            return datetime.fromisoformat(candidate.uploaded_at.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError, OverflowError):
            return None

    @classmethod
    def _sort_key(cls, candidate: DocumentCandidate) -> tuple[float, str, str, int]:
        timestamp = cls._timestamp(candidate)
        return (
            timestamp if timestamp is not None else float("-inf"),
            candidate.original_filename.casefold(),
            candidate.file_id,
            candidate.document_version or 0,
        )

    @staticmethod
    def _resolution(status: ResolutionStatus, *, selected: DocumentCandidate | None = None, candidates: list[DocumentCandidate] | None = None, matched_by: str | None = None, explanation: str) -> DocumentResolution:
        return DocumentResolution(
            status=status,
            selected_document=selected,
            candidates=candidates or ([] if selected is None else [selected]),
            matched_by=matched_by,
            explanation=explanation,
        )

    @staticmethod
    def _filename_candidates(query: str, candidates: list[DocumentCandidate]) -> tuple[str | None, list[DocumentCandidate]]:
        ordered = sorted({candidate.original_filename for candidate in candidates}, key=len, reverse=True)
        query_folded = query.casefold()
        for filename in ordered:
            if filename.casefold() in query_folded:
                return filename, [candidate for candidate in candidates if candidate.original_filename == filename]
        return None, candidates

    @staticmethod
    def _filename_matches(query: str, candidates: list[DocumentCandidate]) -> list[str]:
        query_folded = query.casefold()
        return [
            filename
            for filename in sorted({candidate.original_filename for candidate in candidates}, key=len, reverse=True)
            if filename.casefold() in query_folded
        ]

    @staticmethod
    def _explicit_filename_requested(query: str) -> bool:
        """Detect an explicit PDF/DOCX filename without guessing its value.

        A missing match must not fall through to the unique-document fallback.
        Queries without a concrete filename (for example, project-level RAG or
        ordinal/contextual references) continue through the existing resolver
        rules unchanged.
        """
        return bool(re.search(r"\.(?:pdf|docx)\b", query, re.IGNORECASE))

    @classmethod
    def _visible_documents(cls, candidates: list[DocumentCandidate]) -> list[DocumentCandidate]:
        by_filename: dict[str, list[DocumentCandidate]] = {}
        for candidate in candidates:
            by_filename.setdefault(candidate.original_filename, []).append(candidate)
        visible: list[DocumentCandidate] = []
        for versions in by_filename.values():
            current = [item for item in versions if item.is_current is True]
            if len(current) == 1:
                visible.append(current[0])
                continue
            known = [item for item in versions if item.document_version is not None]
            if known:
                highest = max(item.document_version for item in known)
                latest = [item for item in known if item.document_version == highest]
                visible.append(sorted(latest, key=cls._sort_key)[-1])
            elif len(versions) == 1:
                visible.append(versions[0])
        return sorted(visible, key=cls._sort_key)

    @classmethod
    def _extract_version(cls, query: str) -> int | None:
        match = _VERSION_RE.search(query)
        if not match:
            return None
        token = match.group("ordinal") or match.group("label") or match.group("v")
        return chinese_number(token) if token else None

    @classmethod
    def _extract_ordinal(cls, query: str) -> tuple[int, bool] | None:
        match = _ORDINAL_RE.search(query)
        if not match:
            return None
        number = chinese_number(match.group("number"))
        if number is None:
            return None
        return number, bool(match.group("kind") and match.group("kind").casefold() == "pdf")

    @staticmethod
    def _is_latest(query: str) -> bool:
        return bool(re.search(r"最新版|最新版本|最新的|最新那个|当前版本|当前文件|现在这份|现在这个版本|最新文件", query, re.IGNORECASE))

    @staticmethod
    def _is_previous_version(query: str) -> bool:
        return bool(re.search(r"上一个版本|上一版|上一版本|前一个版本|之前的版本|之前那个版本", query))

    @staticmethod
    def _is_contextual(query: str) -> bool:
        return bool(_CONTEXTUAL_DOCUMENT_REFERENCE_RE.search(query))

    @staticmethod
    def _feature_requested(query: str) -> bool:
        return bool(re.search(r"带页码|有页码|没有页码|无页码", query))

    def _coerce_documents(self, project_id: str) -> list[DocumentCandidate]:
        return [candidate for candidate in self.documents if candidate.project_id == project_id]

    def resolve(
        self,
        query: str,
        project_id: str,
        *,
        previous_document: DocumentCandidate | Mapping[str, Any] | None = None,
        last_referenced_document: DocumentCandidate | Mapping[str, Any] | None = None,
    ) -> DocumentResolution:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        query = query.strip()
        project_id = project_id.strip()
        candidates = self._coerce_documents(project_id)
        if not candidates:
            return self._resolution("not_found", explanation="当前项目没有匹配的文档。")

        context_value = previous_document or last_referenced_document
        context: DocumentCandidate | None = None
        if context_value is not None:
            context = context_value if isinstance(context_value, DocumentCandidate) else DocumentCandidate.from_metadata(context_value)
            if context.project_id != project_id or context.is_duplicate:
                context = None

        filename_matches = self._filename_matches(query, candidates)
        if len(filename_matches) > 1:
            matched_documents = [
                item for item in candidates if item.original_filename in filename_matches
            ]
            return self._resolution(
                "ambiguous",
                candidates=matched_documents,
                matched_by="multiple_filenames",
                explanation="查询中明确提到多个文件，无法安全确定当前文档。",
            )

        filename, scoped = self._filename_candidates(query, candidates)
        if self._explicit_filename_requested(query) and filename is None:
            return self._resolution(
                "not_found",
                explanation="用户指定的文件不存在于当前项目。",
            )
        version = self._extract_version(query)
        if version is not None:
            matches = [item for item in scoped if item.document_version == version]
            if len(matches) == 1:
                return self._resolution("resolved", selected=matches[0], matched_by="filename+version" if filename else "version", explanation=f"已按版本 {version} 唯一定位文档。")
            if len(matches) > 1:
                return self._resolution("ambiguous", candidates=matches, matched_by="filename+version" if filename else "version", explanation="该版本存在多个候选文档，无法安全判断。")
            return self._resolution("not_found", candidates=scoped, matched_by="filename+version" if filename else "version", explanation=f"未找到版本 {version}。")

        if self._is_previous_version(query):
            if context is None:
                return self._resolution("insufficient_context", explanation="解析上一个版本需要当前文档上下文。")
            if context.document_version is None:
                return self._resolution("insufficient_context", explanation="当前文档缺少可靠的版本号。")
            target = context.document_version - 1
            if target < 1:
                return self._resolution("not_found", explanation="当前文档已经是第一版，没有上一个版本。")
            matches = [item for item in candidates if item.original_filename == context.original_filename and item.document_version == target]
            if len(matches) == 1:
                return self._resolution("resolved", selected=matches[0], matched_by="previous_version", explanation=f"已定位到 {context.original_filename} 的上一个版本。")
            if len(matches) > 1:
                return self._resolution("ambiguous", candidates=matches, matched_by="previous_version", explanation="上一个版本存在多个候选。")
            return self._resolution("not_found", matched_by="previous_version", explanation="未找到上一个版本。")

        if self._is_latest(query):
            if context is None and self._is_contextual(query):
                return self._resolution(
                    "insufficient_context",
                    explanation="该当前版本引用需要上一轮已选文档作为上下文。",
                )
            if context is not None and not filename:
                scoped = [
                    item for item in candidates
                    if item.original_filename == context.original_filename
                ]
            current = [item for item in scoped if item.is_current is True]
            if len(current) == 1:
                return self._resolution("resolved", selected=current[0], matched_by="filename+current" if filename else "current", explanation="已定位到当前版本。")
            if len(current) > 1:
                return self._resolution("ambiguous", candidates=sorted(current, key=self._sort_key), matched_by="filename+current" if filename else "current", explanation="存在多个当前文档版本，无法安全选择。")
            return self._resolution("insufficient_context", candidates=scoped, matched_by="current", explanation="文档 metadata 没有可靠的当前版本标记。")

        ordinal = self._extract_ordinal(query)
        if ordinal is not None:
            number, pdf_only = ordinal
            visible = self._visible_documents(candidates)
            if pdf_only:
                visible = [item for item in visible if item.original_filename.casefold().endswith(".pdf") or str(item.metadata.get("file_type", "")).casefold() == "pdf"]
            if any(self._timestamp(item) is None for item in visible):
                return self._resolution("insufficient_context", candidates=visible, matched_by="ordinal", explanation="部分文档缺少可靠的 uploaded_at，无法确定文件顺序。")
            if number > len(visible):
                return self._resolution("not_found", candidates=visible, matched_by="ordinal", explanation="文档序号超出当前项目范围。")
            selected = visible[number - 1]
            return self._resolution("resolved", selected=selected, matched_by="ordinal", explanation=f"已按上传顺序定位第 {number} 个文件。")

        if self._is_contextual(query) and not filename:
            if context is None:
                return self._resolution("insufficient_context", explanation="该引用需要上一轮已选文档作为上下文。")
            if self._is_previous_version(query):
                return self._resolution("insufficient_context", explanation="上一个版本需要明确的版本上下文。")
            return self._resolution("resolved", selected=context, matched_by="context", explanation="已根据上一轮文档上下文定位。")

        if self._feature_requested(query):
            feature_match = (
                re.search(r"没有页码|无页码", query) is None
                and re.search(r"带页码|有页码", query) is not None
            )
            known: list[DocumentCandidate] = []
            unknown = False
            for item in scoped:
                value = item.metadata.get("has_page_numbers")
                if not isinstance(value, bool):
                    value = item.metadata.get("page_number") is not None if "page_number" in item.metadata else None
                if value is None:
                    unknown = True
                elif value == feature_match:
                    known.append(item)
            if unknown and not known:
                return self._resolution("insufficient_context", candidates=scoped, matched_by="page_feature", explanation="现有 metadata 没有可靠的页码特征。")
            if len(known) == 1 and not unknown:
                return self._resolution("resolved", selected=known[0], matched_by="page_feature", explanation="已按明确的页码特征定位。")
            if len(known) > 1 or unknown:
                return self._resolution("ambiguous", candidates=known or scoped, matched_by="page_feature", explanation="页码特征对应多个候选或部分文档缺少该信息。")
            return self._resolution("not_found", candidates=scoped, matched_by="page_feature", explanation="没有匹配该页码特征的文档。")

        if re.search(r"刚上传|刚才上传|我刚上传", query):
            timestamps = [(self._timestamp(item), item) for item in scoped]
            if any(timestamp is None for timestamp, _ in timestamps):
                return self._resolution("insufficient_context", candidates=scoped, matched_by="uploaded_at", explanation="文档缺少可靠的 uploaded_at。")
            latest_time = max(timestamp for timestamp, _ in timestamps if timestamp is not None)
            latest = [item for timestamp, item in timestamps if timestamp == latest_time]
            if len(latest) == 1:
                return self._resolution("resolved", selected=latest[0], matched_by="uploaded_at", explanation="已按最近上传时间定位。")
            return self._resolution("ambiguous", candidates=latest, matched_by="uploaded_at", explanation="多个文档的 uploaded_at 相同，无法安全选择。")

        if filename:
            current = [item for item in scoped if item.is_current is True]
            if len(current) == 1:
                return self._resolution("resolved", selected=current[0], matched_by="filename+current", explanation="仅指定文件名时，按约定优先选择当前版本。")
            if len(scoped) == 1:
                return self._resolution("resolved", selected=scoped[0], matched_by="filename", explanation="文件名唯一对应一个文档。")
            if len(current) > 1:
                return self._resolution("ambiguous", candidates=current, matched_by="filename+current", explanation="同名文件存在多个当前版本候选。")
            return self._resolution("ambiguous", candidates=scoped, matched_by="filename", explanation="同名文件存在多个版本，未能可靠确定当前版本。")

        visible = self._visible_documents(candidates)
        if len(visible) == 1:
            return self._resolution("resolved", selected=visible[0], matched_by="唯一文档", explanation="当前项目只有一个可见文档。")
        return self._resolution("ambiguous", candidates=visible or candidates, explanation="引用没有明确指定唯一文档。")

    def resolve_reference(self, *args: Any, **kwargs: Any) -> DocumentResolution:
        """Alias with a concise name for callers integrating later."""
        return self.resolve(*args, **kwargs)
