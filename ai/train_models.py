
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


# Project directories
ROOT = Path(__file__).resolve().parents[1]
DATASET_DIR = ROOT / "dataset"
MODELS_DIR = ROOT / "models"

DATASET_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

DATA_FILE = DATASET_DIR / "sprint_tasks.csv"

NUMERIC_FEATURES = [
    "complexity",
    "dependencies",
    "days_remaining",
    "team_workload"
]

CATEGORICAL_FEATURES = ["priority"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES


def create_sample_dataset():
    """Create reproducible demonstration data."""
    rng = np.random.default_rng(42)
    rows = []

    for _ in range(600):
        complexity = int(rng.integers(1, 6))
        dependencies = int(rng.integers(0, 6))
        days_remaining = int(rng.integers(1, 15))
        team_workload = int(rng.integers(30, 111))
        priority = rng.choice(["Low", "Medium", "High", "Critical"])

        priority_extra = {
            "Low": 0,
            "Medium": 1,
            "High": 2,
            "Critical": 3
        }[priority]

        # Demonstration effort formula with random variation
        estimated_hours = (
            2
            + complexity * 3.5
            + dependencies * 1.8
            + priority_extra * 1.2
            + team_workload * 0.06
            + rng.normal(0, 2)
        )
        estimated_hours = max(1, round(estimated_hours, 1))

        # Generate a sample delay outcome.
        # This is a synthetic label, not real historical evidence.
        risk_score = (
            complexity * 0.65
            + dependencies * 0.55
            + team_workload * 0.035
            + priority_extra * 0.25
            - days_remaining * 0.28
            + rng.normal(0, 1.0)
        )

        delayed = int(risk_score > 5.2)

        rows.append({
            "complexity": complexity,
            "priority": priority,
            "dependencies": dependencies,
            "days_remaining": days_remaining,
            "team_workload": team_workload,
            "estimated_hours": estimated_hours,
            "delayed": delayed
        })

    df = pd.DataFrame(rows)
    df.to_csv(DATA_FILE, index=False)
    return df


def build_pipeline(model):
    preprocessing = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", NUMERIC_FEATURES),
            (
                "priority",
                OneHotEncoder(handle_unknown="ignore"),
                CATEGORICAL_FEATURES
            )
        ]
    )

    return Pipeline([
        ("preprocessing", preprocessing),
        ("model", model)
    ])


def main():
    df = create_sample_dataset()

    X = df[FEATURES]
    y_effort = df["estimated_hours"]
    y_risk = df["delayed"]

    X_train, X_test, effort_train, effort_test = train_test_split(
        X, y_effort, test_size=0.2, random_state=42
    )

    effort_model = build_pipeline(
        RandomForestRegressor(
            n_estimators=150,
            random_state=42,
            min_samples_leaf=2
        )
    )
    effort_model.fit(X_train, effort_train)

    effort_score = effort_model.score(X_test, effort_test)

    joblib.dump(
        effort_model,
        MODELS_DIR / "effort_model.joblib"
    )

    X_train, X_test, risk_train, risk_test = train_test_split(
        X, y_risk, test_size=0.2, random_state=42,
        stratify=y_risk
    )

    risk_model = build_pipeline(
        RandomForestClassifier(
            n_estimators=150,
            random_state=42,
            min_samples_leaf=2,
            class_weight="balanced"
        )
    )
    risk_model.fit(X_train, risk_train)

    risk_score = risk_model.score(X_test, risk_test)

    joblib.dump(
        risk_model,
        MODELS_DIR / "risk_model.joblib"
    )

    print("AI model training completed!")
    print(f"Sample dataset: {DATA_FILE}")
    print(f"Effort model test R²: {effort_score:.3f}")
    print(f"Risk model test accuracy: {risk_score:.3f}")
    print(f"Dataset rows: {len(df)}")
    print(f"Delayed examples: {int(df['delayed'].sum())}")
    print("Saved models in:", MODELS_DIR)


if __name__ == "__main__":
    main()
