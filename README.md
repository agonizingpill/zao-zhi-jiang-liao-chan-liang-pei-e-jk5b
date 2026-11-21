# 造纸浆料产量配额

River Paper 纸厂用来把浆料批次、纤维配比与机台工况转成可审批的周产量配额，再约束领料计划。项目聚焦造纸车间的实际决策链，包含配比验证、机台安全边界、Random Forest 产量回归、分位数配额带、拆周、审批与物料领用。

## 真实场景

模拟客户是 River Paper 纸厂的 2 条纸机生产计划团队。过去由班组长在 Excel 中拼接浆料批次、纤维比例、机速和蒸汽压力，计划员手工估算周产量，仓库再凭邮件领料。主要痛点是配比越界直到投料时才被发现，预测上界可能跨过机台安全容量，领料单也容易超过主管批准的吨位。上游是实验室纤维配比与机台抄表，下游是生产排程和仓库发料。

## 快速启动

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:18266/api/health
```

首次启动会创建表结构并执行幂等 seed。worker 负责 Redis 队列中的 RandomForestRegressor 试算任务。

访问 `http://localhost:18266`。

## 演示账号

| 角色 | 邮箱 | 密码 | 能力 |
|---|---|---|---|
| 操作员 | operator@riverpaper.test | RiverOp2026! | 登记批次、配比、创建试算、拆分、申请领料 |
| 主管 | supervisor@riverpaper.test | RiverSup2026! | 操作员能力 + 批准配额和领料、查看审计 |
| 查看员 | viewer@riverpaper.test | RiverView2026! | 只读查看批次、配额和领料 |

## 业务模块

- 浆料批次。纸种等级、浆源组合、目标水分、责任人、绑定配比和机台。
- 纤维配比。原生浆、再生浆、损纸、含水率、灰分和工艺窗校验。
- 机台工况。机速、定量、烘缸温度、蒸汽压力、安全周产能。
- 产量配额。RandomForestRegressor 预测均值和 10%/90% 分位数带，跨安全上限时拆成两周。
- 降额复批。纸机下调安全产能后原配额立即暂停领料，worker 按新工况重算产量，主管复批后才恢复。
- 领料计划。只允许在已批准配额内累计请求物料。

## 降额与复批规则

- 在配额页面录入降额（新安全产能必须低于当前上限），配额状态转为 `reduced_pending`，新领料请求和领料审批立即暂停。
- 已经批准的领料照常办理；重算后的新额度若盖不住这部分已批准吨位，主管不能复批（接口返回 `REAPPROVE_SHORT_OF_APPROVED`）。
- 降额与领料审批并发时靠配额行锁定序：先批准的计入已占吨位，先降额的让审批返回 `ISSUE_APPROVAL_PAUSED`。
- 重算结果携带降额序号，乱序返回时只认最近一次降额，旧结果标记 `superseded`；同一重算重试执行是幂等空操作，不会重复占用吨位。
- 配额页面可查看待复批原因、已批准占用吨位和复批后还能领多少。

## 算法口径

worker 使用固定随机种子 42 生成 160 条带噪合成训练样本，特征顺序是 `virgin_pct, recycled_pct, broke_pct, moisture_pct, line_speed_mpm, basis_weight_gsm, dryer_temp_c, steam_pressure_kpa, safety_capacity_tons`。RandomForestRegressor 使用 90 棵树，输出树预测分布的均值、10% 分位数和 90% 分位数。失败态是批次不存在、配比未验证或配比越界，均在进入队列前拒绝。

## 枚举出现位置

- 角色 `operator/supervisor/viewer`：`backend/src/schema.sql`、`backend/src/auth.py`、`backend/src/main.py`、`frontend/src/app.js`。
- 批次状态 `registered/measured/forecasted/allocated/blocked`：`backend/src/schema.sql`、`backend/src/main.py`、`frontend/src/app.js`。
- 配额状态 `queued/ready/split_required/approved/rejected/reduced_pending`：`backend/src/schema.sql`、`backend/src/main.py`、`frontend/src/app.js`。
- 降额状态 `recalculating/applied/superseded`：`backend/src/schema.sql`、`backend/src/worker.py`。
- 领料状态 `requested/approved/issued/rejected`：`backend/src/schema.sql`、`backend/src/main.py`、`frontend/src/app.js`。

## 目录与技术栈

- `backend/src`。FastAPI 路由、PostgreSQL 领域表、Redis worker、认证、业务校验和算法。
- `backend/scripts`。seed 与维护脚本。
- `frontend/src`。原生 HTML/CSS/JS，Nginx 静态托管与 API 反代。
- Python 3.11、FastAPI、PostgreSQL 16、Redis 7、Nginx 1.27、scikit-learn。

## 环境变量

见 `.env.example`。端口为前端 `18266`、后端 `19266`、PostgreSQL `17766`，Redis 使用 compose 内网端口。

## License

MIT
