
from ai.effort_model import predict_effort
from ai.risk_model import predict_risk


# Example task
task = {
    "complexity": 4,
    "priority": "High",
    "dependencies": 3,
    "days_remaining": 4,
    "team_workload": 85
}

print("=" * 45)
print(" SPRINTAI - AI PREDICTION TEST")
print("=" * 45)

effort = predict_effort(**{
    "complexity": task["complexity"],
    "priority": task["priority"],
    "dependencies": task["dependencies"],
    "days_remaining": task["days_remaining"],
    "team_workload": task["team_workload"]
})

risk = predict_risk(**task)

print("\nTASK DETAILS")
for key, value in task.items():
    print(f"{key.replace('_', ' ').title()}: {value}")

print("\nAI PREDICTIONS")
print(f"Estimated effort: {effort} hours")
print(f"Delay risk: {risk['risk_probability']}%")
print(f"Risk level: {risk['risk_level']}")
print(f"Predicted delay: {risk['predicted_delay']}")

print("\nPrediction test completed!")
