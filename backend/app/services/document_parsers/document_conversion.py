"""Safe LibreOffice headless conversion for legacy Office documents."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .base import normalize_extension


class DocumentConversionError(RuntimeError):
    """Base error for legacy Office conversion failures."""


class ConversionUnavailableError(DocumentConversionError):
    """Raised when LibreOffice cannot be found."""


class ConversionTimeoutError(DocumentConversionError):
    """Raised when LibreOffice exceeds the configured timeout."""


class UnsupportedLegacyFormatError(DocumentConversionError):
    """Raised for a format without a conversion mapping."""


class LibreOfficeConversionService:
    """Convert legacy Office files into temporary modern Office files."""

    TARGET_EXTENSIONS = {".doc": ".docx", ".ppt": ".pptx", ".xls": ".xlsx"}

    def __init__(self, executable: str | Path | None = None, timeout_seconds: float = 60.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.executable = str(executable) if executable is not None else None
        self.timeout_seconds = timeout_seconds

    @classmethod
    def find_executable(cls) -> str | None:
        for name in ("soffice", "libreoffice"):
            found = shutil.which(name)
            if found:
                return found
        candidates = []
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            root = os.environ.get(variable)
            if root:
                candidates.extend(
                    [
                        Path(root) / "LibreOffice" / "program" / "soffice.exe",
                        Path(root) / "libreoffice" / "program" / "soffice.exe",
                    ]
                )
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
        return None

    @classmethod
    def is_available(cls) -> bool:
        return cls.find_executable() is not None

    @classmethod
    def target_extension(cls, source: str | Path) -> str:
        extension = normalize_extension(source)
        try:
            return cls.TARGET_EXTENSIONS[extension]
        except KeyError as error:
            raise UnsupportedLegacyFormatError(
                f"No legacy conversion mapping for {extension or '<unknown>'}"
            ) from error

    @contextmanager
    def convert(self, source: str | Path) -> Iterator[Path]:
        source_path = Path(source)
        target_extension = self.target_extension(source_path)
        executable = self.executable or self.find_executable()
        if executable is None:
            raise ConversionUnavailableError(
                "文档转换组件未安装，当前环境无法转换老式 Office 文件"
            )
        if not source_path.is_file():
            raise DocumentConversionError("源文档不存在或不是文件")

        with tempfile.TemporaryDirectory(prefix="northstar-office-convert-") as temporary:
            output_dir = Path(temporary)
            command = [
                executable,
                "--headless",
                "--convert-to",
                target_extension.lstrip("."),
                "--outdir",
                str(output_dir),
                str(source_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as error:
                raise ConversionTimeoutError("文档转换超出时间限制") from error
            except OSError as error:
                raise DocumentConversionError("无法启动文档转换组件") from error
            if completed.returncode != 0:
                raise DocumentConversionError("文档转换失败")

            expected = output_dir / f"{source_path.stem}{target_extension}"
            if not expected.is_file():
                candidates = list(output_dir.glob(f"*{target_extension}"))
                if len(candidates) != 1:
                    raise DocumentConversionError("文档转换未生成预期输出文件")
                expected = candidates[0]
            yield expected