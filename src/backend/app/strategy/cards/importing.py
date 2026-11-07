"""In-memory import preparation only (plan 2.5.14 A/G).

No filesystem discovery, config generation, DB writes, evaluator or lifecycle action.
Formal semantic preflight is separate; persistence remains blocked on card errors.
An inspection result is never authority to persist, enable or run a strategy.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.tokens import AliasToken, AnchorToken

from app.strategy.cards.models import CardIdentity, PendingImport

_FENCE = re.compile(
    r"^```yaml(?: (strategy-card|strategy-spec|validation))?[^\S\n]*\n(.*?)^```[^\S\n]*$",
    re.MULTILINE | re.DOTALL,
)
_MAX_DOCUMENT = 100_000
# Formal cards include bounded 26-case synthetic series blocks, larger than sketches.
_MAX_TOKENS = 100_000


class _UniqueLoader(yaml.SafeLoader):
    """No duplicate keys/merge shadowing in machine inputs."""


def _mapping(loader: _UniqueLoader, node: yaml.MappingNode) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ValueError("machine blocks require unique string keys")
        result[key] = loader.construct_object(value_node)
    return result


_UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _block(source: str) -> dict[str, Any]:
    try:
        for count, token in enumerate(yaml.scan(source), 1):
            if count > _MAX_TOKENS or isinstance(token, AliasToken | AnchorToken):
                raise ValueError("YAML aliases/anchors or oversized blocks are not supported")
        value = yaml.load(source, Loader=_UniqueLoader)  # noqa: S506 (SafeLoader subclass)
        # JSON-only staging prevents Python objects, non-finite values and YAML dates
        # silently acquiring runtime semantics. Full card-specific coercion is pending.
        if not isinstance(value, dict):
            raise ValueError("machine block must be an object")
        json.dumps(value, allow_nan=False)
        return value
    except (yaml.YAMLError, RecursionError, TypeError):
        raise ValueError("invalid strategy machine block") from None


def prepare_document(document: str) -> PendingImport | None:
    """Plain template YAML is ignored, labelled duplicates rejected, no partial success.

    Blocks/narrative are retained for later full semantic validation. This does NOT
    assert G1/G3/G4, formal approval, import idempotence or any promotion gate.
    """
    if len(document) > _MAX_DOCUMENT:
        raise ValueError("strategy document exceeds staging limit")
    blocks: dict[str, dict[str, Any]] = {}
    for match in _FENCE.finditer(document):
        label = match.group(1)
        if label is None:
            continue
        if label in blocks:
            raise ValueError("duplicate strategy machine block")
        blocks[label] = _block(match.group(2))
    if "strategy-card" not in blocks:
        return None
    card = blocks["strategy-card"]
    try:
        identity = CardIdentity.model_validate(
            {
                key: card.get(key)
                for key in (
                    "key",
                    "version_no",
                    "name",
                )
            }
        )
    except ValidationError:
        raise ValueError("invalid strategy-card identity") from None
    for label in ("strategy-spec",):
        if label in blocks and any(
            blocks[label].get(key) != card[key] for key in ("key", "version_no")
        ):
            raise ValueError("card and spec identity mismatch")
    try:
        return PendingImport(
            identity=identity,
            source_hash=hashlib.sha256(document.encode()).hexdigest(),
            narrative=_FENCE.sub("", document).strip(),
            blocks=blocks,
        )
    except (ValidationError, RecursionError):
        raise ValueError("machine blocks must contain finite JSON values") from None


def prepare_documents(documents: list[str]) -> list[PendingImport]:
    """All-or-nothing preparation. Repeated identical versions coalesce in memory.

    Existing DB version conflicts and transactional persistence are deliberately not
    implemented here. A changed same-key/version source is rejected, not overwritten.
    """
    if len(documents) > 100:
        raise ValueError("too many staged documents")
    prepared: dict[tuple[str, int], PendingImport] = {}
    for document in documents:
        item = prepare_document(document)
        if item is None:
            continue
        key = (item.identity.key, item.identity.version_no)
        if key in prepared and prepared[key].source_hash != item.source_hash:
            raise ValueError("immutable staged version conflict")
        prepared[key] = item
    return list(prepared.values())
