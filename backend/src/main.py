from datetime import date
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from .auth import current_user, issue_token, password_hash, require_roles
from .db import query, execute
from .services import audit, validate_blend, enqueue_quota, serialize_row

app = FastAPI(title="Pulp Output Quota API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class LoginIn(BaseModel):
    email: str
    password: str
class BlendIn(BaseModel):
    blend_code: str = Field(min_length=3, max_length=40)
    virgin_pct: float
    recycled_pct: float
    broke_pct: float
    moisture_pct: float
    ash_pct: float
    note: str = ""
class LotIn(BaseModel):
    lot_code: str
    grade: str
    source_mix: str
    target_moisture_pct: float
    blend_id: int
    machine_run_id: int
    owner_name: str
class MachineIn(BaseModel):
    run_code: str
    machine_name: str
    line_speed_mpm: float
    basis_weight_gsm: float
    dryer_temp_c: float
    steam_pressure_kpa: float
    safety_capacity_tons: float
class ForecastIn(BaseModel):
    plan_code: str
    pulp_lot_id: int
    week_start: date
    safety_limit_tons: float
    notes: str = ""
class IssueIn(BaseModel):
    issue_code: str
    quota_plan_id: int
    material_name: str
    quantity_tons: float

@app.get("/health")
def health():
    query("SELECT 1", one=True)
    return {"status": "ok", "service": "backend"}

@app.post("/auth/login")
def login(payload: LoginIn):
    user = query("SELECT id,email,password_hash,role,display_name FROM users WHERE email=%s", (payload.email,), one=True)
    if not user or user["password_hash"] != password_hash(payload.password):
        raise HTTPException(401, "邮箱或密码不正确")
    return {"access_token": issue_token(user), "user": {k: user[k] for k in ["id","email","role","display_name"]}}

@app.get("/me")
def me(user=Depends(current_user)):
    return user

@app.get("/dashboard/summary")
def summary(user=Depends(current_user)):
    row = query("""SELECT
      (SELECT count(*) FROM pulp_lots) AS lots,
      (SELECT count(*) FROM fiber_blends WHERE status='validated') AS blends,
      (SELECT count(*) FROM quota_plans WHERE status IN ('queued','ready','split_required')) AS pending,
      (SELECT count(*) FROM material_issues WHERE status IN ('requested','approved')) AS issues""", one=True)
    recent = query("""SELECT q.plan_code,q.week_start,q.predicted_tons,q.upper_tons,q.status,l.lot_code,m.machine_name
      FROM quota_plans q JOIN pulp_lots l ON l.id=q.pulp_lot_id JOIN machine_runs m ON m.id=q.machine_run_id
      ORDER BY q.created_at DESC LIMIT 5""")
    return {"stats": {k:int(v) for k,v in row.items()}, "recent": [serialize_row(x) for x in recent]}

@app.get("/fiber-blends")
def blends(user=Depends(current_user)):
    return [serialize_row(x) for x in query("SELECT * FROM fiber_blends ORDER BY created_at DESC")]

@app.post("/fiber-blends")
def create_blend(payload: BlendIn, user=Depends(require_roles("operator", "supervisor"))):
    data = payload.model_dump()
    errors = validate_blend(data)
    if errors:
        raise HTTPException(422, {"code": "BLEND_OUT_OF_RANGE", "errors": errors})
    try:
        row = query("""INSERT INTO fiber_blends(blend_code,virgin_pct,recycled_pct,broke_pct,moisture_pct,ash_pct,status,note)
          VALUES (%s,%s,%s,%s,%s,%s,'validated',%s) RETURNING *""", (payload.blend_code,payload.virgin_pct,payload.recycled_pct,payload.broke_pct,payload.moisture_pct,payload.ash_pct,payload.note), one=True)
    except Exception:
        raise HTTPException(409, "配比编号已存在")
    audit(user["id"], "blend_validated", "fiber_blend", row["id"], {"blend_code": row["blend_code"]})
    return serialize_row(row)

@app.get("/machine-runs")
def machines(user=Depends(current_user)):
    return [serialize_row(x) for x in query("SELECT * FROM machine_runs ORDER BY machine_name")]

@app.post("/machine-runs")
def create_machine(payload: MachineIn, user=Depends(require_roles("operator", "supervisor"))):
    row = query("""INSERT INTO machine_runs(run_code,machine_name,line_speed_mpm,basis_weight_gsm,dryer_temp_c,steam_pressure_kpa,safety_capacity_tons,started_at)
      VALUES (%s,%s,%s,%s,%s,%s,%s,now()) RETURNING *""", tuple(payload.model_dump().values()), one=True)
    audit(user["id"], "machine_registered", "machine_run", row["id"], {"run_code": row["run_code"]})
    return serialize_row(row)

@app.get("/pulp-lots")
def lots(user=Depends(current_user)):
    rows = query("""SELECT l.*,b.blend_code,b.virgin_pct,b.recycled_pct,b.broke_pct,b.moisture_pct,b.status AS blend_status,
      m.run_code,m.machine_name,m.safety_capacity_tons
      FROM pulp_lots l JOIN fiber_blends b ON b.id=l.blend_id JOIN machine_runs m ON m.id=l.machine_run_id ORDER BY l.created_at DESC""")
    return [serialize_row(x) for x in rows]

@app.post("/pulp-lots")
def create_lot(payload: LotIn, user=Depends(require_roles("operator", "supervisor"))):
    blend = query("SELECT * FROM fiber_blends WHERE id=%s", (payload.blend_id,), one=True)
    machine = query("SELECT * FROM machine_runs WHERE id=%s", (payload.machine_run_id,), one=True)
    if not blend or not machine:
        raise HTTPException(404, "配比或机台不存在")
    if blend["status"] != "validated":
        raise HTTPException(422, "只有已验证配比可绑定到浆料批次")
    row = query("""INSERT INTO pulp_lots(lot_code,grade,source_mix,target_moisture_pct,blend_id,machine_run_id,status,received_at,owner_name)
      VALUES (%s,%s,%s,%s,%s,%s,'registered',now(),%s) RETURNING *""", (payload.lot_code,payload.grade,payload.source_mix,payload.target_moisture_pct,payload.blend_id,payload.machine_run_id,payload.owner_name), one=True)
    audit(user["id"], "lot_registered", "pulp_lot", row["id"], {"lot_code": row["lot_code"]})
    return serialize_row(row)

@app.get("/quota-plans")
def plans(user=Depends(current_user)):
    rows = query("""SELECT q.*,l.lot_code,l.grade,b.blend_code,b.virgin_pct,b.recycled_pct,b.broke_pct,
      m.run_code,m.machine_name,m.safety_capacity_tons
      FROM quota_plans q JOIN pulp_lots l ON l.id=q.pulp_lot_id JOIN fiber_blends b ON b.id=l.blend_id
      JOIN machine_runs m ON m.id=q.machine_run_id ORDER BY q.created_at DESC""")
    return [serialize_row(x) for x in rows]

@app.post("/quota-plans/forecast")
def create_forecast(payload: ForecastIn, user=Depends(require_roles("operator", "supervisor"))):
    lot = query("""SELECT l.*,b.status AS blend_status,b.virgin_pct,b.recycled_pct,b.broke_pct,b.moisture_pct,m.id AS machine_id,m.safety_capacity_tons
      FROM pulp_lots l JOIN fiber_blends b ON b.id=l.blend_id JOIN machine_runs m ON m.id=l.machine_run_id WHERE l.id=%s""", (payload.pulp_lot_id,), one=True)
    if not lot:
        raise HTTPException(404, "浆料批次不存在")
    blend_data = {k: lot[k] for k in ['virgin_pct','recycled_pct','broke_pct','moisture_pct','ash_pct'] if k in lot}
    blend_data['ash_pct'] = query("SELECT ash_pct FROM fiber_blends WHERE id=%s", (lot['blend_id'],), one=True)['ash_pct']
    errors = validate_blend(blend_data)
    if lot["blend_status"] != "validated" or errors:
        raise HTTPException(422, {"code": "BLEND_OUT_OF_RANGE", "message": "纤维配比不在工艺范围，不能生成配额", "errors": errors})
    exists = query("SELECT id FROM quota_plans WHERE plan_code=%s", (payload.plan_code,), one=True)
    if exists:
        raise HTTPException(409, "配额编号已存在")
    row = query("""INSERT INTO quota_plans(plan_code,pulp_lot_id,machine_run_id,week_start,safety_limit_tons,created_by,notes)
      VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id,plan_code,status""", (payload.plan_code, payload.pulp_lot_id, lot['machine_id'], payload.week_start, payload.safety_limit_tons, user['id'], payload.notes), one=True)
    execute("UPDATE pulp_lots SET status='forecasted' WHERE id=%s", (payload.pulp_lot_id,))
    audit(user["id"], "quota_forecast_queued", "quota_plan", row["id"], {"plan_code": row["plan_code"]})
    enqueue_quota(row["id"])
    return row

@app.post("/quota-plans/{plan_id}/split")
def split_plan(plan_id: int, user=Depends(require_roles("operator", "supervisor"))):
    plan = query("SELECT * FROM quota_plans WHERE id=%s", (plan_id,), one=True)
    if not plan:
        raise HTTPException(404, "配额提案不存在")
    if plan["status"] != "split_required":
        raise HTTPException(409, "当前提案无需拆分")
    split_weeks = 2
    planned = round(float(plan["safety_limit_tons"]) * 0.92, 2)
    row = query("UPDATE quota_plans SET split_required=false, split_weeks=%s, planned_tons=%s, status='ready', notes='已拆分为两周交付，每周避开机台安全上限' WHERE id=%s RETURNING *", (split_weeks, planned, plan_id), one=True)
    audit(user["id"], "quota_split", "quota_plan", plan_id, {"split_weeks": split_weeks, "planned_tons": planned})
    return serialize_row(row)

@app.post("/quota-plans/{plan_id}/approve")
def approve_plan(plan_id: int, user=Depends(require_roles("supervisor"))):
    plan = query("SELECT * FROM quota_plans WHERE id=%s", (plan_id,), one=True)
    if not plan:
        raise HTTPException(404, "配额提案不存在")
    if plan["status"] != "ready" or not plan["planned_tons"]:
        raise HTTPException(409, "提案必须完成试算，且拆分要求已处理后才能批准")
    row = query("UPDATE quota_plans SET status='approved', approved_by=%s, approved_at=now() WHERE id=%s RETURNING *", (user["id"], plan_id), one=True)
    execute("UPDATE pulp_lots SET status='allocated' WHERE id=%s", (plan["pulp_lot_id"],))
    audit(user["id"], "quota_approved", "quota_plan", plan_id, {"planned_tons": float(row["planned_tons"])})
    return serialize_row(row)

@app.get("/material-issues")
def issues(user=Depends(current_user)):
    rows = query("""SELECT i.*,q.plan_code,q.planned_tons,l.lot_code FROM material_issues i
      JOIN quota_plans q ON q.id=i.quota_plan_id JOIN pulp_lots l ON l.id=q.pulp_lot_id ORDER BY i.created_at DESC""")
    return [serialize_row(x) for x in rows]

@app.post("/material-issues")
def request_issue(payload: IssueIn, user=Depends(require_roles("operator", "supervisor"))):
    plan = query("SELECT * FROM quota_plans WHERE id=%s", (payload.quota_plan_id,), one=True)
    if not plan or plan["status"] != "approved":
        raise HTTPException(422, "只有已批准配额才能创建领料计划")
    used = query("SELECT COALESCE(SUM(quantity_tons),0) AS total FROM material_issues WHERE quota_plan_id=%s AND status IN ('requested','approved','issued')", (payload.quota_plan_id,), one=True)["total"]
    if float(used) + payload.quantity_tons > float(plan["planned_tons"]):
        raise HTTPException(422, {"code": "ISSUE_OVER_QUOTA", "message": "领料量超过已批准周配额", "remaining_tons": round(float(plan["planned_tons"]) - float(used), 2)})
    try:
        row = query("""INSERT INTO material_issues(issue_code,quota_plan_id,material_name,quantity_tons,requested_by)
          VALUES (%s,%s,%s,%s,%s) RETURNING *""", (payload.issue_code,payload.quota_plan_id,payload.material_name,payload.quantity_tons,user['id']), one=True)
    except Exception:
        raise HTTPException(409, "领料请求编号已存在")
    audit(user["id"], "material_issue_requested", "material_issue", row["id"], {"quantity_tons": payload.quantity_tons})
    return serialize_row(row)

@app.post("/material-issues/{issue_id}/approve")
def approve_issue(issue_id: int, user=Depends(require_roles("supervisor"))):
    row = query("UPDATE material_issues SET status='approved', approved_by=%s WHERE id=%s AND status='requested' RETURNING *", (user['id'], issue_id), one=True)
    if not row:
        raise HTTPException(409, "领料计划不存在或已处理")
    audit(user["id"], "material_issue_approved", "material_issue", issue_id, {})
    return serialize_row(row)

@app.get("/audit-logs")
def logs(user=Depends(require_roles("supervisor"))):
    return [serialize_row(x) for x in query("SELECT a.*,u.display_name FROM audit_logs a LEFT JOIN users u ON u.id=a.actor_id ORDER BY a.created_at DESC LIMIT 50")]
