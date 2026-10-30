
from pathlib import Path

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "effort_model.joblib"


def predict_effort(
    complexity,
    priority,
    dependencies,
    days_remaining,
    team_workload
):
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "Effort model not found. Run python ai/train_models.py first."
        )

    model = joblib.load(MODEL_PATH)

    task = pd.DataFrame([{
        "complexity": int(complexity),
        "priority": str(priority).title(),
        "dependencies": int(dependencies),
        "days_remaining": int(days_remaining),
        "team_workload": int(team_workload)
    }])

    prediction = model.predict(task)[0]
    return round(max(0.5, float(prediction)), 1)
