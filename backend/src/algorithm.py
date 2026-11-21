import numpy as np
from sklearn.ensemble import RandomForestRegressor

RANDOM_SEED = 42

def train_and_predict(features):
    rng = np.random.default_rng(RANDOM_SEED)
    x_train = rng.uniform([45, 20, 0, 9, 70, 60, 105, 320, 420], [75, 45, 12, 13, 95, 180, 125, 620, 720], size=(160, 9))
    base = (x_train[:, 0] * 0.12 + x_train[:, 1] * 0.16 - x_train[:, 2] * 0.09 - x_train[:, 3] * 0.35 + x_train[:, 4] * 0.42 + x_train[:, 5] * 0.07 + x_train[:, 6] * 0.65 + x_train[:, 7] * 0.018 + x_train[:, 8] * 0.028)
    y_train = base + rng.normal(0, 3.5, size=160)
    model = RandomForestRegressor(n_estimators=90, max_depth=8, random_state=RANDOM_SEED, min_samples_leaf=2)
    model.fit(x_train, y_train)
    x = np.array([[float(v) for v in features]], dtype=float)
    tree_predictions = np.vstack([tree.predict(x) for tree in model.estimators_]).reshape(-1)
    return {
        "predicted_tons": round(float(np.mean(tree_predictions)), 2),
        "lower_tons": round(float(np.quantile(tree_predictions, 0.10)), 2),
        "upper_tons": round(float(np.quantile(tree_predictions, 0.90)), 2),
        "model": "RandomForestRegressor",
        "seed": RANDOM_SEED,
        "trees": len(model.estimators_),
        "feature_order": ["virgin_pct", "recycled_pct", "broke_pct", "moisture_pct", "line_speed_mpm", "basis_weight_gsm", "dryer_temp_c", "steam_pressure_kpa", "safety_capacity_tons"],
    }
