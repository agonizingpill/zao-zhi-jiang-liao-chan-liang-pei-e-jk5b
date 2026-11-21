import json
from datetime import date
from decimal import Decimal
import redis
from .config import REDIS_URL
from .db import execute, query

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

BLEND_LIMITS = {
    "virgin_pct": (40, 80),
    "recycled_pct": (15, 50),
    "broke_pct": (0, 15),
    "moisture_pct": (8, 14),
    "ash_pct": (0, 12),
}

def audit(user_id, action, entity, entity_id, detail):
    execute("INSERT INTO audit_logs(actor_id, action, entity, entity_id, detail) VALUES (%s,%s,%s,%s,%s)", (user_id, action, entity, entity_id, json.dumps(detail, ensure_ascii=False)))

def validate_blend(values):
    errors = []
    for key, (low, high) in BLEND_LIMITS.items():
        value = float(values[key])
        if not low <= value <= high:
            errors.append(f"{key} 必须在 {low} 到 {high} 之间")
    total = float(values["virgin_pct"]) + float(values["recycled_pct"]) + float(values["broke_pct"])
    if abs(total - 100) > 0.01:
        errors.append(f"纤维比例合计必须为100%，当前为 {total:.2f}%")
    return errors

def enqueue_quota(plan_id):
    redis_client.rpush("pulp:quota_jobs", str(plan_id))

def decimal_json(value):
    if isinstance(value, Decimal):
        return float(value)
    return value

def serialize_row(row):
    if not row:
        return row
    return {k: decimal_json(v) for k, v in row.items()}

def quota_with_relations(row):
    if not row:
        return None
    return serialize_row(row)
