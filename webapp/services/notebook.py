from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import RLock

from webapp.core.errors import AppError, ErrorCode


class NotebookService:
    def __init__(self, data_dir: Path | str) -> None:
        self._path = Path(data_dir) / "notice.txt"
        self._lock = RLock()

    def read(self) -> dict[str, object]:
        with self._lock:
            if not self._path.exists():
                return _result("")
            if not self._path.is_file():
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Notebook path is not a file.",
                    {"path": str(self._path)},
                )
            try:
                return _result(self._path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError) as exc:
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Notebook could not be loaded.",
                    {"path": str(self._path), "error": str(exc)},
                ) from exc

    def save(self, content: str) -> dict[str, object]:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path: Path | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    dir=self._path.parent,
                    prefix=".notice-",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary.write(content)
                    temporary.flush()
                    os.fsync(temporary.fileno())
                    temporary_path = Path(temporary.name)
                os.replace(temporary_path, self._path)
            except OSError as exc:
                raise AppError(
                    ErrorCode.DATA_FILE_INVALID,
                    "Notebook could not be saved.",
                    {"path": str(self._path), "error": str(exc)},
                ) from exc
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink(missing_ok=True)
            return _result(content)


def _result(content: str) -> dict[str, object]:
    return {"content": content, "bytes": len(content.encode("utf-8"))}
