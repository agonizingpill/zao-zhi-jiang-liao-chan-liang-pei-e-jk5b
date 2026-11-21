import json
import os
import time
from datetime import datetime
from pathlib import Path
import redis
from .config import REDIS_URL
from .db import query, execute
from .algorithm import train_and_predict

heartbeat = Path("/shared/worker-heartbeat")
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

def run_job(plan_id):
    row = query("""
      SELECT q.id, q.machine_run_id, q.pulp_lot_id, q.safety_limit_tons,
             b.virgin_pct, b.recycled_pct, b.broke_pct, b.moisture_pct,
             m.line_speed_mpm, m.basis_weight_gsm, m.dryer_temp_c,
             m.steam_pressure_kpa, m.safety_capacity_tons
      FROM quota_plans q
      JOIN pulp_lots l ON l.id=q.pulp_lot_id
      JOIN fiber_blends b ON b.id=l.blend_id
      JOIN machine_runs m ON m.id=q.machine_run_id
      WHERE q.id=%s
    """, (plan_id,), one=True)
    if not row:
        return
    features = [row["virgin_pct"], row["recycled_pct"], row["broke_pct"], row["moisture_pct"], row["line_speed_mpm"], row["basis_weight_gsm"], row["dryer_temp_c"], row["steam_pressure_kpa"], row["safety_capacity_tons"]]
    result = train_and_predict(features)
    split_required = float(result["upper_tons"]) > float(row["safety_capacity_tons"])
    status = "split_required" if split_required else "ready"
    notes = "预测上界跨越机台安全上限，必须先拆分周计划" if split_required else "区间处于机台安全范围，可提交主管审批"
    execute("""UPDATE quota_plans SET predicted_tons=%s, lower_tons=%s, upper_tons=%s,
      split_required=%s, status=%s, notes=%s WHERE id=%s""", (result["predicted_tons"], result["lower_tons"], result["upper_tons"], split_required, status, notes, plan_id))
    execute("INSERT INTO audit_logs(action, entity, entity_id, detail) VALUES ('forecast_completed','quota_plan',%s,%s)", (plan_id, json.dumps(result)))

if __name__ == "__main__":
    while True:
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        heartbeat.touch()
        try:
            item = redis_client.blpop("pulp:quota_jobs", timeout=3)
            if item:
                run_job(int(item[1]))
        except Exception as exc:
            execute("INSERT INTO audit_logs(action, entity, detail) VALUES ('worker_error','quota_plan',%s)", (json.dumps({"error": str(exc)}),))
            time.sleep(2)
