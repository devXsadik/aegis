"""Vector index of approved, unexpired watchlist faces (one embedding model at a time).

Small in-memory matrix (numpy dot product; FAISS IndexFlatIP when installed), rebuilt when the
watchlist or its embeddings change (checked at most every INDEX_TTL seconds). For a national
deployment with millions of vectors, the same interface maps onto pgvector (HNSW) or Milvus:
`search()` is the only call the matcher makes."""

from __future__ import annotations

import threading
import time
from typing import List, Optional, Tuple

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.models.face_encoding import FaceEncoding
from backend.models.known_person import KnownPerson
from backend.services.watchlist_gov import active_person_ids

INDEX_TTL = 30.0


class FaceIndex:
    def __init__(self):
        self._lock = threading.Lock()
        self._key = None
        self._checked = 0.0
        self._matrix: Optional[np.ndarray] = None
        self._owners: List[str] = []
        self._faiss = None

    def _signature(self, db: Session, model: str, ids) -> tuple:
        n, last = (db.query(func.count(FaceEncoding.id), func.max(FaceEncoding.id))
                   .filter(FaceEncoding.encoding_version == model).one())
        return model, tuple(sorted(ids)), n, last

    def refresh(self, db: Session, model: str, force: bool = False) -> None:
        with self._lock:
            if not force and time.time() - self._checked < INDEX_TTL and self._key and self._key[0] == model:
                return
            ids = active_person_ids(db)
            key = self._signature(db, model, ids)
            self._checked = time.time()
            if key == self._key:
                return
            rows = (db.query(FaceEncoding.encoding, KnownPerson.person_id)
                    .join(KnownPerson, KnownPerson.id == FaceEncoding.person_id)
                    .filter(FaceEncoding.encoding_version == model, KnownPerson.person_id.in_(sorted(ids)))
                    .all()) if ids else []
            vecs = [np.frombuffer(r[0], dtype=np.float32) for r in rows]
            self._owners = [r[1] for r in rows]
            self._matrix = np.vstack(vecs).astype(np.float32) if vecs else None
            self._faiss = None
            if self._matrix is not None and len(self._owners) > 2000:
                try:
                    import faiss
                    idx = faiss.IndexFlatIP(self._matrix.shape[1])
                    idx.add(self._matrix)
                    self._faiss = idx
                except ImportError:
                    pass
            self._key = key

    def search(self, db: Session, vec: np.ndarray, model: str, k: int = 3) -> List[Tuple[str, float]]:
        """Best similarity per person, highest first."""
        self.refresh(db, model)
        if self._matrix is None or vec is None or vec.shape[0] != self._matrix.shape[1]:
            return []
        if self._faiss is not None:
            sims, idx = self._faiss.search(vec[None].astype(np.float32), min(k * 5, len(self._owners)))
            pairs = [(self._owners[i], float(s)) for s, i in zip(sims[0], idx[0]) if i >= 0]
        else:
            sims = self._matrix @ vec.astype(np.float32)
            order = np.argsort(-sims)[: k * 5]
            pairs = [(self._owners[i], float(sims[i])) for i in order]
        best = {}
        for pid, s in pairs:
            best[pid] = max(best.get(pid, -1.0), s)
        return sorted(best.items(), key=lambda x: -x[1])[:k]

    def size(self) -> int:
        return 0 if self._matrix is None else len(self._owners)


INDEX = FaceIndex()
