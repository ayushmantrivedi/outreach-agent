"""
models/embedding_model.py
=========================
Project knowledge embedding and retrieval using sentence-transformers + ChromaDB.
Fetches README from GitHub, chunks it, embeds it, and exposes a retrieve() method
so the email generation agent can pull relevant context per company.
"""

import os
import re
from typing import List, Optional

import requests
from chromadb import PersistentClient
from chromadb.config import Settings
from dotenv import load_dotenv
from loguru import logger
from sentence_transformers import SentenceTransformer

load_dotenv()

_CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_store")
_GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


class EmbeddingModel:
    """
    Manages project knowledge as a ChromaDB vector collection.

    Parameters
    ----------
    collection_name : str
        Name of the Chroma collection (use project slug).
    model_name : str
        sentence-transformers model to use.
    chunk_size : int
        Approximate character count per chunk.
    chunk_overlap : int
        Overlap characters between consecutive chunks.
    """

    def __init__(
        self,
        collection_name: str = "project_knowledge",
        model_name: str = "all-MiniLM-L6-v2",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ):
        self.collection_name = collection_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        logger.info(f"Loading embedding model: {model_name}")
        self.model = SentenceTransformer(model_name)

        self.client = PersistentClient(path=_CHROMA_PERSIST_DIR)
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB collection '{collection_name}' ready ({self.collection.count()} docs).")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into overlapping chunks."""
        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunks.append(text[start:end])
            start += self.chunk_size - self.chunk_overlap
        return [c.strip() for c in chunks if c.strip()]

    def _fetch_github_readme(self, repo_url: str) -> Optional[str]:
        """
        Fetch the raw README markdown from a GitHub repository URL.
        Supports both https://github.com/user/repo and user/repo formats.
        """
        # Normalise URL to owner/repo
        match = re.search(r"github\.com/([^/]+/[^/]+)", repo_url)
        if match:
            slug = match.group(1).rstrip("/")
        elif "/" in repo_url and "." not in repo_url.split("/")[0]:
            slug = repo_url.strip("/")
        else:
            logger.error(f"Cannot parse GitHub URL: {repo_url}")
            return None

        headers = {"Accept": "application/vnd.github.v3.raw"}
        if _GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {_GITHUB_TOKEN}"

        for filename in ["README.md", "readme.md", "README.rst", "README"]:
            api_url = f"https://api.github.com/repos/{slug}/contents/{filename}"
            resp = requests.get(api_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                logger.info(f"Fetched {filename} from {slug}")
                return resp.text
        logger.warning(f"No README found for {slug}")
        return None

    def ingest_text(self, text: str, source_label: str = "manual") -> int:
        """
        Embed and store arbitrary text. Returns number of chunks added.
        """
        chunks = self._chunk_text(text)
        if not chunks:
            logger.warning("ingest_text called with empty content.")
            return 0

        embeddings = self.model.encode(chunks, show_progress_bar=False).tolist()
        ids = [f"{source_label}_{i}" for i in range(len(chunks))]
        metadatas = [{"source": source_label, "chunk_index": i} for i in range(len(chunks))]

        # Upsert (overwrite if same id already exists)
        self.collection.upsert(
            documents=chunks,
            embeddings=embeddings,
            ids=ids,
            metadatas=metadatas,
        )
        logger.info(f"Ingested {len(chunks)} chunks from '{source_label}'.")
        return len(chunks)

    def ingest_github_repo(self, repo_url: str) -> int:
        """Fetch the GitHub README and ingest it as project knowledge."""
        readme = self._fetch_github_readme(repo_url)
        if readme:
            return self.ingest_text(readme, source_label="github_readme")
        return 0

    def ingest_project_description(self, description: str) -> int:
        """Ingest the plain-text project description from settings."""
        return self.ingest_text(description, source_label="project_description")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 3) -> List[str]:
        """
        Embed a query and return the top-k most relevant text chunks.

        Parameters
        ----------
        query : str
            The query to match against stored knowledge.
        top_k : int
            Number of chunks to return.

        Returns
        -------
        List[str]
            Most relevant text chunks, best first.
        """
        if self.collection.count() == 0:
            logger.warning("Knowledge base is empty. Run ingest first.")
            return []

        query_embedding = self.model.encode([query], show_progress_bar=False).tolist()
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=min(top_k, self.collection.count()),
        )
        return results["documents"][0] if results["documents"] else []

    def clear(self) -> None:
        """Delete and recreate the collection (fresh ingest)."""
        self.client.delete_collection(self.collection_name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Collection '{self.collection_name}' cleared.")
