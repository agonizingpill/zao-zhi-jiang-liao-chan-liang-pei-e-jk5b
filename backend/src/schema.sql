CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('operator','supervisor','viewer')),
  display_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS fiber_blends (
  id SERIAL PRIMARY KEY,
  blend_code TEXT UNIQUE NOT NULL,
  virgin_pct NUMERIC(5,2) NOT NULL,
  recycled_pct NUMERIC(5,2) NOT NULL,
  broke_pct NUMERIC(5,2) NOT NULL,
  moisture_pct NUMERIC(5,2) NOT NULL,
  ash_pct NUMERIC(5,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','validated','rejected')),
  note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS machine_runs (
  id SERIAL PRIMARY KEY,
  run_code TEXT UNIQUE NOT NULL,
  machine_name TEXT NOT NULL,
  line_speed_mpm NUMERIC(8,2) NOT NULL,
  basis_weight_gsm NUMERIC(8,2) NOT NULL,
  dryer_temp_c NUMERIC(8,2) NOT NULL,
  steam_pressure_kpa NUMERIC(8,2) NOT NULL,
  safety_capacity_tons NUMERIC(10,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready' CHECK (status IN ('ready','maintenance','retired')),
  started_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS pulp_lots (
  id SERIAL PRIMARY KEY,
  lot_code TEXT UNIQUE NOT NULL,
  grade TEXT NOT NULL,
  source_mix TEXT NOT NULL,
  target_moisture_pct NUMERIC(5,2) NOT NULL,
  blend_id INTEGER NOT NULL REFERENCES fiber_blends(id),
  machine_run_id INTEGER NOT NULL REFERENCES machine_runs(id),
  status TEXT NOT NULL DEFAULT 'registered' CHECK (status IN ('registered','measured','forecasted','allocated','blocked')),
  received_at TIMESTAMPTZ NOT NULL,
  owner_name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS quota_plans (
  id SERIAL PRIMARY KEY,
  plan_code TEXT UNIQUE NOT NULL,
  pulp_lot_id INTEGER NOT NULL REFERENCES pulp_lots(id),
  machine_run_id INTEGER NOT NULL REFERENCES machine_runs(id),
  week_start DATE NOT NULL,
  predicted_tons NUMERIC(10,2),
  lower_tons NUMERIC(10,2),
  upper_tons NUMERIC(10,2),
  safety_limit_tons NUMERIC(10,2) NOT NULL,
  planned_tons NUMERIC(10,2),
  split_required BOOLEAN NOT NULL DEFAULT false,
  split_weeks INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','ready','split_required','approved','rejected')),
  created_by INTEGER NOT NULL REFERENCES users(id),
  approved_by INTEGER REFERENCES users(id),
  approved_at TIMESTAMPTZ,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS material_issues (
  id SERIAL PRIMARY KEY,
  issue_code TEXT UNIQUE NOT NULL,
  quota_plan_id INTEGER NOT NULL REFERENCES quota_plans(id),
  material_name TEXT NOT NULL,
  quantity_tons NUMERIC(10,2) NOT NULL,
  status TEXT NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','approved','issued','rejected')),
  requested_by INTEGER NOT NULL REFERENCES users(id),
  approved_by INTEGER REFERENCES users(id),
  issued_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_logs (
  id SERIAL PRIMARY KEY,
  actor_id INTEGER REFERENCES users(id),
  action TEXT NOT NULL,
  entity TEXT NOT NULL,
  entity_id INTEGER,
  detail JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_quota_status ON quota_plans(status);
CREATE INDEX IF NOT EXISTS idx_lot_status ON pulp_lots(status);
