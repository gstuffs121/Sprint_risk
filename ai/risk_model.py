
from pathlib import Path

import joblib
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "risk_model.joblib"


def predict_risk(
    complexity,
    priority,
    dependencies,
    days_remaining,
    team_workload
):
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "Risk model not found. Run python ai/train_models.py first."
        )

    model = joblib.load(MODEL_PATH)

    task = pd.DataFrame([{
        "complexity": int(complexity),
        "priority": str(priority).title(),
        "dependencies": int(dependencies),
        "days_remaining": int(days_remaining),
        "team_workload": int(team_workload)
    }])

    probabilities = model.predict_proba(task)[0]
    classes = list(model.classes_)
    delayed_index = classes.index(1)

    probability = float(probabilities[delayed_index])
    percentage = round(probability * 100, 1)

    if percentage < 25:
        level = "Low"
    elif percentage < 50:
        level = "Medium"
    elif percentage < 75:
        level = "High"
    else:
        level = "Critical"

    return {
        "risk_probability": percentage,
        "risk_level": level,
        "predicted_delay": bool(model.predict(task)[0])
    }
