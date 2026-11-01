"""LLM 网关（plan §3.3「LLM 网关」、§2.7；契约 v0.2.1 /admin/llm/*）。

- ``api_key_source``（契约 v0.2.1）：``env`` 来源（DeepSeek：``DEEPSEEK_API_KEY``）库里不存 key；
  ``db`` 来源才写 ``api_key_ciphertext``（APP_MASTER_KEY 加密）。
- plan 的 ``api_key_last4`` 不建：契约规定任何接口都不返回 key 或其片段。
"""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Column, Table, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import BYTEA

from app.db.base import (
    APP,
    boolean,
    created_at,
    integer,
    jsonb,
    metadata,
    money,
    num,
    one_of,
    pk_uuid,
    ts,
    txt,
    uuid_array,
    uuid_col,
)
from app.schemas.enums import LlmTask

llm_providers = Table(
    "llm_providers",
    metadata,
    pk_uuid(),
    txt("name", nullable=False, unique=True),
    txt("kind", nullable=False),
    txt("base_url"),
    txt("api_key_source", nullable=False, server_default=text("'db'")),
    Column("api_key_ciphertext", BYTEA),
    integer("key_version"),
    boolean("enabled", nullable=False, server_default=text("true")),
    uuid_col("created_by", fk="app.users.id"),
    ts("updated_at", nullable=False, default_now=True),
    one_of("kind", ["openai_compatible", "anthropic"]),
    one_of("api_key_source", ["env", "db"]),
    CheckConstraint(
        "api_key_source = 'db' OR api_key_ciphertext IS NULL", name="env_key_not_stored"
    ),
    schema=APP,
)

llm_models = Table(
    "llm_models",
    metadata,
    pk_uuid(),
    uuid_col("provider_id", nullable=False, fk="app.llm_providers.id"),
    txt("model_name", nullable=False),
    integer("context_window"),
    num("price_input_per_1k"),
    num("price_output_per_1k"),
    txt("currency"),
    boolean("enabled", nullable=False, server_default=text("true")),
    UniqueConstraint("provider_id", "model_name"),
    schema=APP,
)

prompt_templates = Table(
    "prompt_templates",
    metadata,
    pk_uuid(),
    txt("task", nullable=False),
    integer("version_no", nullable=False),
    txt("system_text", nullable=False),
    txt("user_template", nullable=False),
    jsonb("output_schema"),
    txt("status", nullable=False, server_default=text("'draft'")),
    uuid_col("created_by", fk="app.users.id"),
    created_at(),
    one_of("task", LlmTask),
    one_of("status", ["draft", "active", "retired"]),
    UniqueConstraint("task", "version_no"),
    schema=APP,
    comment="激活后正文不可变，只允许 status active→retired（触发器）",
)

llm_task_routes = Table(
    "llm_task_routes",
    metadata,
    txt("task", nullable=False, primary_key=True),
    uuid_col("primary_model_id", fk="app.llm_models.id"),
    uuid_array("fallback_model_ids"),
    integer("timeout_s"),
    integer("max_retries"),
    num("temperature"),
    integer("max_output_tokens"),
    money("daily_budget"),
    boolean("enabled", nullable=False, server_default=text("true")),
    uuid_col("prompt_template_id", fk="app.prompt_templates.id"),
    one_of("task", LlmTask),
    schema=APP,
)

llm_calls = Table(
    "llm_calls",
    metadata,
    pk_uuid(),
    txt("task", nullable=False),
    uuid_col("provider_id", fk="app.llm_providers.id"),
    uuid_col("model_id", fk="app.llm_models.id"),
    uuid_col("prompt_template_id", fk="app.prompt_templates.id"),
    integer("input_tokens"),
    integer("output_tokens"),
    integer("latency_ms"),
    txt("status", nullable=False),
    jsonb("validation_errors"),
    money("cost_estimate"),
    txt("target_type"),
    txt("target_id"),
    txt("request_hash"),
    Column("request_body", BYTEA, comment="加密；保留 90 天"),
    Column("response_body", BYTEA, comment="加密；保留 90 天"),
    created_at(),
    one_of("task", LlmTask),
    one_of("status", ["ok", "timeout", "error", "validation_failed", "fallback_template"]),
    schema=APP,
)
