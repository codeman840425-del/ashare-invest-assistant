"""Redis delivery hints for the existing DB daily outbox; no budget/authorization state."""

from __future__ import annotations

import uuid
from typing import Any

PUBLISH_ONCE = """
-- daily_publish_once: recover a missing/trimmed stream entry from the DB outbox.
local old = redis.call('GET', KEYS[2])
if old then
    local rows = redis.call('XRANGE', KEYS[1], old, old)
    if #rows > 0 then
        local fields = rows[1][2]
        local kind, batch = nil, nil
        for i = 1, #fields, 2 do
            if fields[i] == 'kind' then kind = fields[i+1] end
            if fields[i] == 'batch_id' then batch = fields[i+1] end
        end
        if kind == ARGV[1] and batch == ARGV[2] then return 0 end
    end
end
local id = redis.call('XADD', KEYS[1], '*', 'kind', ARGV[1], 'batch_id', ARGV[2])
redis.call('SET', KEYS[2], id)
return 1
"""
ACK = """
-- daily_ack: never delete a hint for a newer message when acknowledging an old PEL entry.
local count = redis.call('XACK', KEYS[1], ARGV[1], ARGV[2])
if redis.call('GET', KEYS[2]) == ARGV[2] then redis.call('DEL', KEYS[2]) end
return count
"""


def pending_key(bid: uuid.UUID) -> str:
    return "ingest:mairui-daily:pending:" + str(bid)


def publish_once(rds: Any, stream: str, kind: str, bid: uuid.UUID) -> bool:  # noqa: ANN401
    return bool(rds.eval(PUBLISH_ONCE, 2, stream, pending_key(bid), kind, str(bid)))


def acknowledge(rds: Any, stream: str, group: str, bid: uuid.UUID, mid: Any) -> None:  # noqa: ANN401
    rds.eval(ACK, 2, stream, pending_key(bid), group, mid)
