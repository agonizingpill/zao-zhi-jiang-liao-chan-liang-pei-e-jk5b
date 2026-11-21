from datetime import datetime, timezone, date
from .db import query, execute
from .auth import password_hash

def upsert_user(email, password, role, name):
    row = query("SELECT id FROM users WHERE email=%s", (email,), one=True)
    if row:
        return row["id"]
    return query("INSERT INTO users(email,password_hash,role,display_name) VALUES (%s,%s,%s,%s) RETURNING id", (email, password_hash(password), role, name), one=True)["id"]

def upsert_blend(code, virgin, recycled, broke, moisture, ash, status, note):
    row = query("SELECT id FROM fiber_blends WHERE blend_code=%s", (code,), one=True)
    if row:
        return row["id"]
    return query("""INSERT INTO fiber_blends(blend_code,virgin_pct,recycled_pct,broke_pct,moisture_pct,ash_pct,status,note)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (code, virgin, recycled, broke, moisture, ash, status, note), one=True)["id"]

def upsert_machine(code, name, speed, basis, dryer, steam, safety, status='ready'):
    row = query("SELECT id FROM machine_runs WHERE run_code=%s", (code,), one=True)
    if row:
        return row["id"]
    return query("""INSERT INTO machine_runs(run_code,machine_name,line_speed_mpm,basis_weight_gsm,dryer_temp_c,steam_pressure_kpa,safety_capacity_tons,status,started_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now()) RETURNING id""", (code, name, speed, basis, dryer, steam, safety, status), one=True)["id"]

def upsert_lot(code, grade, source, target, blend, machine, owner, status='registered'):
    row = query("SELECT id FROM pulp_lots WHERE lot_code=%s", (code,), one=True)
    if row:
        return row["id"]
    return query("""INSERT INTO pulp_lots(lot_code,grade,source_mix,target_moisture_pct,blend_id,machine_run_id,status,received_at,owner_name)
      VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""", (code, grade, source, target, blend, machine, status, datetime.now(timezone.utc), owner), one=True)["id"]

def seed():
    operator = upsert_user('operator@riverpaper.test', 'RiverOp2026!', 'operator', '林小满·生产调度')
    supervisor = upsert_user('supervisor@riverpaper.test', 'RiverSup2026!', 'supervisor', '周砚·浆线主管')
    viewer = upsert_user('viewer@riverpaper.test', 'RiverView2026!', 'viewer', '何栖·计划分析')
    b1 = upsert_blend('FB-2601-A', 62, 28, 10, 10.4, 5.1, 'validated', 'A4文化纸常用配比')
    b2 = upsert_blend('FB-2601-B', 52, 38, 10, 11.2, 6.3, 'validated', '再生纤维加深配比')
    b3 = upsert_blend('FB-2601-C', 78, 18, 4, 9.3, 3.2, 'validated', '高白度订单配比')
    m1 = upsert_machine('PM-07-2611', 'PM-07文化纸机', 485, 72, 112, 510, 86)
    m2 = upsert_machine('PM-12-2611', 'PM-12包装纸机', 615, 118, 121, 610, 128)
    lots = [
      upsert_lot('PL-261121-01', 'A4-80gsm', '阔叶浆+脱墨浆', 10.5, b1, m1, '林小满', 'measured'),
      upsert_lot('PL-261121-02', 'A4-70gsm', '针叶浆+再生浆', 10.8, b2, m1, '林小满'),
      upsert_lot('PL-261121-03', '包装牛卡', 'OCC再生浆', 11.4, b2, m2, '陈放'),
      upsert_lot('PL-261121-04', '高白双胶', '漂白木浆', 9.5, b3, m1, '陈放'),
      upsert_lot('PL-261121-05', '薄页纸', '混合阔叶浆', 12.0, b1, m2, '刘芹'),
      upsert_lot('PL-261121-06', '测试批次', '异常回用浆', 16.5, b1, m1, '刘芹', 'blocked'),
    ]
    if not query("SELECT id FROM quota_plans WHERE plan_code='QP-2611-001'", one=True):
        query("""INSERT INTO quota_plans(plan_code,pulp_lot_id,machine_run_id,week_start,predicted_tons,lower_tons,upper_tons,safety_limit_tons,planned_tons,split_required,status,created_by,notes)
          VALUES ('QP-2611-001',%s,%s,%s,70.4,66.8,74.2,86,72,false,'approved',%s,'已批准的A4纸周配额') RETURNING id""", (lots[0], m1, date(2026,11,23), supervisor), one=True)
    if not query("SELECT id FROM quota_plans WHERE plan_code='QP-2611-002'", one=True):
        execute("""INSERT INTO quota_plans(plan_code,pulp_lot_id,machine_run_id,week_start,predicted_tons,lower_tons,upper_tons,safety_limit_tons,planned_tons,split_required,status,created_by,notes)
          VALUES ('QP-2611-002',%s,%s,%s,145.5,137.8,153.9,128,NULL,true,'split_required',%s,'示例：预测上界超过PM-12安全上限')""", (lots[2], m2, date(2026,11,23), operator,))
    if not query("SELECT id FROM material_issues WHERE issue_code='MI-2611-001'", one=True):
        q = query("SELECT id FROM quota_plans WHERE plan_code='QP-2611-001'", one=True)["id"]
        execute("""INSERT INTO material_issues(issue_code,quota_plan_id,material_name,quantity_tons,status,requested_by,approved_by,issued_at)
          VALUES ('MI-2611-001',%s,'漂白木浆',24,'approved',%s,%s,now())""", (q, operator, supervisor))
    if not query("SELECT id FROM quota_plans WHERE plan_code='QP-2611-003'", one=True):
        plan_id = query("""INSERT INTO quota_plans(plan_code,pulp_lot_id,machine_run_id,week_start,predicted_tons,lower_tons,upper_tons,safety_limit_tons,planned_tons,split_required,status,created_by,approved_by,approved_at,notes,reduction_seq)
          VALUES ('QP-2611-003',%s,%s,%s,63.5,60.1,66.9,70,63.5,false,'reduced_pending',%s,%s,now(),'机台安全产能下调 86→70 t：PM-07 烘缸轴承振动超阈，安全产能下调',1) RETURNING id""",
          (lots[3], m1, date(2026,11,23), operator, supervisor), one=True)["id"]
        reduction_id = query("""INSERT INTO capacity_reductions(reduction_code,quota_plan_id,machine_run_id,old_safety_limit_tons,new_safety_limit_tons,reason,status,created_by)
          VALUES ('QR-QP-2611-003-01',%s,%s,86,70,'PM-07 烘缸轴承振动超阈，安全产能下调','applied',%s) RETURNING id""",
          (plan_id, m1, supervisor), one=True)["id"]
        execute("UPDATE quota_plans SET current_reduction_id=%s, applied_reduction_id=%s WHERE id=%s", (reduction_id, reduction_id, plan_id))
        execute("""INSERT INTO material_issues(issue_code,quota_plan_id,material_name,quantity_tons,status,requested_by,approved_by)
          VALUES ('MI-2611-002',%s,'漂白木浆',20,'approved',%s,%s)""", (plan_id, operator, supervisor))
