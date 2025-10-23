"""Configuration helpers for the Kid English MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class Settings:
    """Runtime settings with environment overrides."""

    database_path: Path = Path("data/english_kids_mcp.sqlite")
    faiss_index_path: Path = Path("data/faiss.index")
    embedding_dim: int = 128
    min_similarity: float = 0.35

    @classmethod
    def load(cls) -> "Settings":
        """Construct settings from environment variables when available."""

        return cls(
            database_path=Path(
                os.environ.get("MCP_DATABASE_PATH", cls.database_path.as_posix())
            ),
            faiss_index_path=Path(
                os.environ.get("MCP_FAISS_INDEX_PATH", cls.faiss_index_path.as_posix())
            ),
            embedding_dim=int(
                os.environ.get("MCP_EMBEDDING_DIM", str(cls.embedding_dim))
            ),
            min_similarity=float(
                os.environ.get("MCP_MIN_SIMILARITY", str(cls.min_similarity))
            ),
        )


__all__ = ["Settings"]
