"""FAISS backed vector store with lightweight hashing embeddings."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

try:  # pragma: no cover - optional dependency
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None

try:  # pragma: no cover - optional dependency
    import faiss  # type: ignore
except Exception:  # pragma: no cover
    faiss = None

if np is None:  # pragma: no cover - ensure consistency
    faiss = None


@dataclass(slots=True)
class VectorItem:
    text: str
    goal: str
    topic: str


class HashEmbedding:
    """Deterministic embedding without external models."""

    def __init__(self, dim: int = 128) -> None:
        self.dim = dim

    def embed(self, text: str) -> np.ndarray:
        tokens = text.lower().split()
        if np is None:
            vector = [0.0] * self.dim
            for token in tokens:
                index = hash(token) % self.dim
                vector[index] += 1.0
            norm = sum(v * v for v in vector) ** 0.5
            if norm > 0:
                vector = [v / norm for v in vector]
            return vector

        vector = np.zeros(self.dim, dtype="float32")
        for token in tokens:
            index = hash(token) % self.dim
            vector[index] += 1.0
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector


class VectorStore:
    def __init__(self, settings) -> None:
        self.settings = settings
        self.embedding = HashEmbedding(dim=settings.embedding_dim)
        self.index = None
        self.metadata: List[VectorItem] = []
        self._load_or_init()

    def _index_path(self) -> Path:
        return self.settings.faiss_index_path

    def _load_or_init(self) -> None:
        path = self._index_path()
        if path.exists() and faiss is not None:
            self.index = faiss.read_index(str(path))
            metadata_path = path.with_suffix(".json")
            if metadata_path.exists():
                with metadata_path.open("r", encoding="utf-8") as handle:
                    meta_json = json.load(handle)
                    self.metadata = [VectorItem(**item) for item in meta_json]
        else:
            if faiss is not None:
                self.index = faiss.IndexFlatIP(self.settings.embedding_dim)
            self.metadata = []

    def save(self) -> None:
        path = self._index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if faiss is not None and self.index is not None:
            faiss.write_index(self.index, str(path))
            metadata_path = path.with_suffix(".json")
            with metadata_path.open("w", encoding="utf-8") as handle:
                json.dump([item.__dict__ for item in self.metadata], handle, ensure_ascii=False, indent=2)

    def add_items(self, items: Iterable[VectorItem]) -> None:
        vectors = []
        for item in items:
            vectors.append(self.embedding.embed(item.text))
            self.metadata.append(item)
        if not vectors:
            return
        if faiss is not None and np is not None:
            matrix = np.stack(vectors)
            if self.index is None:
                self.index = faiss.IndexFlatIP(self.settings.embedding_dim)
            self.index.add(matrix)
            self.save()

    def search(self, query: str, k: int = 3) -> List[Tuple[VectorItem, float]]:
        if faiss is not None and np is not None and self.index is not None and self.index.ntotal > 0:
            vector = self.embedding.embed(query)
            matrix = np.expand_dims(vector, axis=0)
            scores, indices = self.index.search(matrix, k)
            results: List[Tuple[VectorItem, float]] = []
            for idx, score in zip(indices[0], scores[0]):
                if idx == -1:
                    continue
                item = self.metadata[idx]
                results.append((item, float(score)))
            return results

        # fallback cosine similarity in pure python
        if not self.metadata:
            return []
        query_vec = self.embedding.embed(query)
        results: List[Tuple[VectorItem, float]] = []
        for item in self.metadata:
            item_vec = self.embedding.embed(item.text)
            if np is not None:
                score = float(np.dot(query_vec, item_vec))
            else:
                score = sum(q * v for q, v in zip(query_vec, item_vec))
            results.append((item, score))
        results.sort(key=lambda pair: pair[1], reverse=True)
        return results[:k]


__all__ = ["VectorStore", "VectorItem"]
