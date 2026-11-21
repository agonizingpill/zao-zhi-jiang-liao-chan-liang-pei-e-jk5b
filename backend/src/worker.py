import json
import os
import time
from datetime import datetime
from pathlib import Path
import redis
from .config import REDIS_URL
from .db import query, execute, transaction
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
    planned = None if split_required else result["predicted_tons"]
    execute("""UPDATE quota_plans SET predicted_tons=%s, lower_tons=%s, upper_tons=%s,
      split_required=%s, status=%s, planned_tons=%s, notes=%s WHERE id=%s""", (result["predicted_tons"], result["lower_tons"], result["upper_tons"], split_required, status, planned, notes, plan_id))
    execute("INSERT INTO audit_logs(action, entity, entity_id, detail) VALUES ('forecast_completed','quota_plan',%s,%s)", (plan_id, json.dumps(result)))

def run_recalc(reduction_id):
    row = query("""
      SELECT r.id, r.status, r.quota_plan_id, r.new_safety_limit_tons,
             b.virgin_pct, b.recycled_pct, b.broke_pct, b.moisture_pct,
             m.line_speed_mpm, m.basis_weight_gsm, m.dryer_temp_c, m.steam_pressure_kpa
      FROM capacity_reductions r
      JOIN quota_plans q ON q.id=r.quota_plan_id
      JOIN pulp_lots l ON l.id=q.pulp_lot_id
      JOIN fiber_blends b ON b.id=l.blend_id
      JOIN machine_runs m ON m.id=r.machine_run_id
      WHERE r.id=%s
    """, (reduction_id,), one=True)
    if not row:
        return
    # 用降额后的新工况（新安全产能）重算产量
    features = [row["virgin_pct"], row["recycled_pct"], row["broke_pct"], row["moisture_pct"], row["line_speed_mpm"], row["basis_weight_gsm"], row["dryer_temp_c"], row["steam_pressure_kpa"], row["new_safety_limit_tons"]]
    result = train_and_predict(features)
    planned = round(min(result["predicted_tons"], float(row["new_safety_limit_tons"]) * 0.92), 2)
    with transaction() as cur:
        cur.execute("SELECT status FROM capacity_reductions WHERE id=%s FOR UPDATE", (reduction_id,))
        reduction = cur.fetchone()
        if not reduction or reduction["status"] != "recalculating":
            return  # 重试或已被取代：不再重复落库，吨位不会重复占用
        cur.execute("SELECT current_reduction_id FROM quota_plans WHERE id=%s FOR UPDATE", (row["quota_plan_id"],))
        plan = cur.fetchone()
        if not plan or plan["current_reduction_id"] != reduction_id:
            # 乱序返回的旧结果：只认最近一次降额，旧结果标记为已取代
            cur.execute("UPDATE capacity_reductions SET status='superseded' WHERE id=%s", (reduction_id,))
            cur.execute("INSERT INTO audit_logs(action, entity, entity_id, detail) VALUES ('recalc_superseded','capacity_reduction',%s,%s)", (reduction_id, json.dumps({"quota_plan_id": row["quota_plan_id"]})))
            return
        cur.execute("""UPDATE quota_plans SET predicted_tons=%s, lower_tons=%s, upper_tons=%s, planned_tons=%s,
          applied_reduction_id=%s, notes=%s WHERE id=%s""",
          (result["predicted_tons"], result["lower_tons"], result["upper_tons"], planned, reduction_id,
           "降额重算完成，待主管复批", row["quota_plan_id"]))
        cur.execute("UPDATE capacity_reductions SET status='applied' WHERE id=%s", (reduction_id,))
        cur.execute("INSERT INTO audit_logs(action, entity, entity_id, detail) VALUES ('recalc_completed','capacity_reduction',%s,%s)",
          (reduction_id, json.dumps({**result, "planned_tons": planned, "quota_plan_id": row["quota_plan_id"]})))

if __name__ == "__main__":
    while True:
        heartbeat.parent.mkdir(parents=True, exist_ok=True)
        heartbeat.touch()
        try:
            item = redis_client.blpop(["pulp:quota_jobs", "pulp:recalc_jobs"], timeout=3)
            if item:
                if item[0] == "pulp:recalc_jobs":
                    run_recalc(int(item[1]))
                else:
                    run_job(int(item[1]))
        except Exception as exc:
            execute("INSERT INTO audit_logs(action, entity, detail) VALUES ('worker_error','quota_plan',%s)", (json.dumps({"error": str(exc)}),))
            time.sleep(2)
