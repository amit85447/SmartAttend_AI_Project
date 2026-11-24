"""Append-only audit trail."""
import json
from datetime import datetime
from sqlalchemy import insert
from database.db import engine
from database.tables import audit_logs


def log(actor_type: str, actor_id, action: str, entity: str | None = None,
        entity_id=None, details: dict | None = None, eng=None):
    eng = eng or engine()
    with eng.begin() as c:
        c.execute(insert(audit_logs).values(
            ts=datetime.now(), actor_type=actor_type, actor_id=str(actor_id), action=action,
            entity=entity, entity_id=None if entity_id is None else str(entity_id),
            details=json.dumps(details, default=str) if details else None))
