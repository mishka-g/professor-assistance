"""Central configuration. Reads from environment / .env, resolves project paths."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/professor_assistant/config.py -> root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Generation backend: mock | local | api
    model_backend: str = "mock"

    # Local (Ollama)
    local_llm: str = "qwen2.5:14b-instruct"
    ollama_host: str = "http://localhost:11434"

    # API path
    api_provider: str = "openai"  # openai | anthropic
    api_model: str = "gpt-4o"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # Retrieval / embeddings
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    retrieval_top_k: int = 5
    chunk_size: int = 1200
    chunk_overlap: int = 200

    # Paths (resolved relative to project root)
    corpus_dir: Path = PROJECT_ROOT / "data" / "corpus"
    drafts_dir: Path = PROJECT_ROOT / "data" / "drafts"
    examples_dir: Path = PROJECT_ROOT / "data" / "examples"
    output_dir: Path = PROJECT_ROOT / "output"
    chroma_dir: Path = PROJECT_ROOT / "storage" / "chroma"
    style_card_path: Path = PROJECT_ROOT / "config" / "style_card.md"
    prompts_dir: Path = PROJECT_ROOT / "prompts"

    collection_name: str = "corpus"

    def prompt(self, name: str) -> str:
        """Load a prompt file from prompts/ by stem name."""
        return (self.prompts_dir / f"{name}.md").read_text(encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()
