from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str
    database_path: Path
    visitor_hash_key: str
    api_keys: dict[str, dict[str, str]]
    storage_backend: str = "sqlite"
    dynamodb_table: str = "heritageflow"
    aws_region: str = "eu-west-1"
    dynamodb_endpoint_url: str | None = None
    seed_demo: bool = False
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_database: str = "heritageflow"
    mysql_user: str = "heritageflow"
    mysql_password: str = ""


def load_settings() -> Settings:
    environment = os.getenv("HERITAGEFLOW_ENV", "development")
    raw_api_keys = os.getenv("HERITAGEFLOW_API_KEYS_JSON", "{}")
    try:
        api_keys = json.loads(raw_api_keys)
    except json.JSONDecodeError as exc:
        raise RuntimeError("HERITAGEFLOW_API_KEYS_JSON must be valid JSON") from exc

    visitor_hash_key = os.getenv("HERITAGEFLOW_VISITOR_HASH_KEY", "")
    if environment != "development" and not visitor_hash_key:
        raise RuntimeError("HERITAGEFLOW_VISITOR_HASH_KEY is required outside development")
    if environment != "development" and not api_keys:
        raise RuntimeError("HERITAGEFLOW_API_KEYS_JSON is required outside development")

    storage_backend = os.getenv("HERITAGEFLOW_STORAGE", "sqlite")
    if storage_backend not in {"sqlite", "mysql", "dynamodb"}:
        raise RuntimeError("HERITAGEFLOW_STORAGE must be sqlite, mysql, or dynamodb")

    try:
        mysql_port = int(os.getenv("HERITAGEFLOW_MYSQL_PORT", "3306"))
    except ValueError as exc:
        raise RuntimeError("HERITAGEFLOW_MYSQL_PORT must be an integer") from exc

    return Settings(
        environment=environment,
        database_path=Path(os.getenv("HERITAGEFLOW_DB_PATH", "heritageflow.db")),
        visitor_hash_key=visitor_hash_key or "development-only-not-a-secret",
        api_keys=api_keys,
        storage_backend=storage_backend,
        dynamodb_table=os.getenv("HERITAGEFLOW_DYNAMODB_TABLE", "heritageflow"),
        aws_region=os.getenv("HERITAGEFLOW_AWS_REGION", os.getenv("AWS_REGION", "eu-west-1")),
        dynamodb_endpoint_url=os.getenv("HERITAGEFLOW_DYNAMODB_ENDPOINT_URL") or None,
        seed_demo=os.getenv("HERITAGEFLOW_SEED_DEMO", "false").lower() == "true",
        mysql_host=os.getenv("HERITAGEFLOW_MYSQL_HOST", "127.0.0.1"),
        mysql_port=mysql_port,
        mysql_database=os.getenv("HERITAGEFLOW_MYSQL_DATABASE", "heritageflow"),
        mysql_user=os.getenv("HERITAGEFLOW_MYSQL_USER", "heritageflow"),
        mysql_password=os.getenv("HERITAGEFLOW_MYSQL_PASSWORD", ""),
    )
