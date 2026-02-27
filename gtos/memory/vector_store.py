# gtos/memory/vector_store.py
"""技能向量存储：Chroma 语义检索，未安装则回退到关键词检索。"""

import json
import os
from pathlib import Path
from typing import Any
from urllib import request

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _CHROMA_AVAILABLE = True
except ImportError:
    _CHROMA_AVAILABLE = False


class VectorStore:
    """统一接口：add(text, metadata)、search(query, top_k)。"""

    def add(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        """写入一条技能（任务描述或任务+代码摘要），用于后续检索。"""
        raise NotImplementedError

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """按语义或关键词检索，返回 [{text, metadata, score?}, ...]。"""
        raise NotImplementedError


class KeywordVectorStore(VectorStore):
    """关键词回退：持久化到 JSON，按子串/词重叠检索。无额外依赖。"""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = Path(__file__).resolve().parents[1] / "data" / "skill_vectors.json"
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._items: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save(self) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._items, f, ensure_ascii=False, indent=2)

    def add(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        self._items.append({"text": text[:2000], "metadata": metadata or {}})
        self._save()

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        if not self._items:
            return []
        q = query.lower().split()
        scored = []
        for item in self._items:
            t = (item.get("text") or "").lower()
            score = sum(1 for w in q if w in t)
            if score > 0:
                scored.append({**item, "score": score})
        scored.sort(key=lambda x: -x["score"])
        return [{"text": x["text"], "metadata": x.get("metadata", {})} for x in scored[:top_k]]


class ChromaVectorStore(VectorStore):
    """Chroma 向量存储：需 pip install chromadb。"""

    def __init__(
        self,
        persist_directory: str | Path | None = None,
        collection_name: str = "gtos_skills",
        embedding_function: Any | None = None,
    ) -> None:
        if not _CHROMA_AVAILABLE:
            raise RuntimeError("chromadb 未安装，请 pip install chromadb 或使用 keyword 回退")
        if persist_directory is None:
            persist_directory = Path(__file__).resolve().parents[1] / "data" / "chroma"
        self._client = chromadb.PersistentClient(path=str(persist_directory), settings=ChromaSettings(anonymized_telemetry=False))
        self._coll = self._client.get_or_create_collection(
            collection_name,
            metadata={"description": "gtos skills"},
            embedding_function=embedding_function,
        )
        self._id = 0

    def add(self, text: str, metadata: dict[str, Any] | None = None) -> None:
        meta = metadata or {}
        # Chroma 仅支持 str/int/float
        safe = {k: (v if isinstance(v, (str, int, float)) else str(v)[:500]) for k, v in meta.items()}
        self._coll.add(ids=[str(self._id)], documents=[text[:2000]], metadatas=[safe])
        self._id += 1

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        r = self._coll.query(query_texts=[query], n_results=min(top_k, 20))
        if not r or not r.get("documents") or not r["documents"][0]:
            return []
        docs = r["documents"][0]
        metas = (r.get("metadatas") or [[]])[0] if r.get("metadatas") else []
        out = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            out.append({"text": doc, "metadata": meta or {}})
        return out


class OpenAICompatibleEmbeddingFunction:
    """用于 Chroma 的 OpenAI 兼容 embeddings 函数。"""

    def __init__(self, *, base_url: str, api_key: str, model: str, timeout_seconds: int = 60) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def __call__(self, input: list[str]) -> list[list[float]]:
        endpoint = self._base_url
        if not endpoint.endswith("/v1"):
            endpoint = endpoint + "/v1"
        endpoint = endpoint + "/embeddings"
        body = {"model": self._model, "input": input}
        req = request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        )
        try:
            with request.urlopen(req, timeout=self._timeout_seconds) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Embedding request failed: {e}") from e
        data = payload.get("data") or []
        if not data:
            raise RuntimeError(f"Unexpected embedding response: {payload}")
        return [item["embedding"] for item in data]


def _build_embedding_function(embedding_config: dict[str, Any] | None, llm_config: dict[str, Any] | None) -> Any | None:
    cfg = embedding_config or {}
    llm_cfg = llm_config or {}
    enabled = cfg.get("enabled")
    if enabled is False:
        return None
    provider = cfg.get("provider", "openai_compatible")
    if provider != "openai_compatible":
        return None

    api_key_env = str(cfg.get("api_key_env") or llm_cfg.get("api_key_env", "OPENAI_API_KEY")).strip()
    if api_key_env.startswith("sk-"):
        api_key = api_key_env
    else:
        api_key = (cfg.get("api_key") or os.environ.get(api_key_env, "") or llm_cfg.get("api_key", "")).strip()
    model = (cfg.get("model") or "").strip()
    if not model or not api_key:
        return None

    base_url = (cfg.get("base_url") or llm_cfg.get("base_url") or "https://api.openai.com/v1").strip()
    timeout_seconds = int(cfg.get("timeout_seconds", llm_cfg.get("timeout_seconds", 60)))
    return OpenAICompatibleEmbeddingFunction(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=timeout_seconds,
    )


def get_vector_store(
    backend: str = "keyword",
    persist_path: str | Path | None = None,
    embedding_config: dict[str, Any] | None = None,
    llm_config: dict[str, Any] | None = None,
) -> VectorStore:
    """根据配置返回 VectorStore：chroma 需安装 chromadb，否则回退 keyword。"""
    if backend == "chroma" and _CHROMA_AVAILABLE:
        embedding_fn = _build_embedding_function(embedding_config=embedding_config, llm_config=llm_config)
        return ChromaVectorStore(persist_directory=persist_path, embedding_function=embedding_fn)
    return KeywordVectorStore(path=persist_path)
