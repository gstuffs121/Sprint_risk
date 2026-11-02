import csv
import io
from datetime import date, datetime
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
    Response
)
from database import get_db_connection, get_dict_cursor, log_audit
from ai.effort_model import predict_effort
from ai.risk_model import predict_risk
from routes.auth import get_current_user

predictions_bp = Blueprint("predictions", __name__)


@predictions_bp.route("/predictions", methods=["GET", "POST"])
def index():
    user = get_current_user()
    conn = None
    cur = None

    result = None
    error = None
    selected_task_id = request.form.get("task_id") if request.method == "POST" else request.args.get("task_id")

    # Handle Task-based prediction submission
    if request.method == "POST" and selected_task_id:
        try:
            conn = get_db_connection()
            cur = get_dict_cursor(conn)

            cur.execute("SELECT * FROM tasks WHERE id = %s", (selected_task_id,))
            task = cur.fetchone()

            if not task:
                raise ValueError("Selected task not found in database.")

            # Prepare features
            complexity = max(1, min(5, int(task.get("complexity") or 3)))
            priority = str(task.get("priority") or "Medium").title()
            if priority not in ["Low", "Medium", "High", "Critical"]:
                priority = "Medium"
            dependencies = max(0, min(5, int(task.get("dependencies") or 0)))

            # Calculate remaining days
            if task.get("due_date"):
                due_val = task["due_date"]
                if isinstance(due_val, str):
                    due_val = date.fromisoformat(due_val)
                elif isinstance(due_val, datetime):
                    due_val = due_val.date()
                days_remaining = (due_val - date.today()).days
            else:
                days_remaining = 7
            days_remaining = max(1, min(14, days_remaining))

            # Team workload
            if task.get("assignee"):
                cur.execute("""
                    SELECT COUNT(*) AS total
                    FROM tasks
                    WHERE assignee = %s AND status != 'completed'
                """, (task["assignee"],))
            else:
                cur.execute("""
                    SELECT COUNT(*) AS total
                    FROM tasks
                    WHERE sprint_id = %s AND status != 'completed'
                """, (task["sprint_id"],))

            open_tasks = cur.fetchone()["total"]
            team_workload = max(30, min(110, 30 + open_tasks * 10))

            # Run ML Models
            effort = predict_effort(
                complexity=complexity,
                priority=priority,
                dependencies=dependencies,
                days_remaining=days_remaining,
                team_workload=team_workload
            )

            risk = predict_risk(
                complexity=complexity,
                priority=priority,
                dependencies=dependencies,
                days_remaining=days_remaining,
                team_workload=team_workload
            )

            predicted_hours = round(float(effort), 2)
            risk_probability = float(risk["risk_probability"])
            risk_level = risk["risk_level"]
            predicted_delay = risk.get("predicted_delay", False)

            explanation = (
                f"Model evaluation: Complexity {complexity}/5, {priority} priority, "
                f"{dependencies} dependencies with {days_remaining} days remaining and {team_workload}% team workload. "
                f"{'High risk of delivery slip identified.' if predicted_delay else 'Effort is within safe delivery margins.'}"
            )

            # Store in database
            cur.execute("""
                INSERT INTO predictions (
                    task_id, predicted_hours, risk_probability, risk_level, explanation, model_version, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                selected_task_id,
                predicted_hours,
                risk_probability,
                risk_level,
                explanation,
                "v1.0-rf-ensemble",
                user["id"] if user else None
            ))

            # Update task is_delayed flag if predicted delay is true
            if predicted_delay:
                cur.execute("UPDATE tasks SET is_delayed = 1 WHERE id = %s", (selected_task_id,))

            conn.commit()

            result = {
                "task_id": task["id"],
                "task_title": task["title"],
                "sprint_id": task["sprint_id"],
                "predicted_hours": predicted_hours,
                "effort": predicted_hours,
                "risk_probability": round(risk_probability, 1),
                "risk_level": risk_level,
                "predicted_delay": predicted_delay,
                "explanation": explanation,
                "complexity": complexity,
                "priority": priority,
                "dependencies": dependencies,
                "days_remaining": days_remaining,
                "team_workload": team_workload
            }

            log_audit(
                "AI_PREDICTION_GENERATED",
                f"Generated prediction for task #{task['id']} '{task['title']}': {predicted_hours}h, {risk_probability}% ({risk_level})",
                user_id=user["id"] if user else None,
                username=user["username"] if user else "Anonymous"
            )

            flash(f"AI Risk Assessment completed for '{task['title']}'!", "success")

        except Exception as e:
            if conn:
                conn.rollback()
            print("Prediction Generation Error:", e)
            error = str(e)
            flash("AI Prediction failed: " + error, "danger")
        finally:
            if cur:
                cur.close()
            if conn:
                conn.close()

    # Load tasks and past predictions
    try:
        conn = get_db_connection()
        cur = get_dict_cursor(conn)

        cur.execute("""
            SELECT t.id, t.title, t.priority, t.status, s.name AS sprint_name
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            ORDER BY t.created_at DESC
        """)
        tasks = cur.fetchall()

        cur.execute("""
            SELECT p.*, t.title AS task_title, s.name AS sprint_name, t.assignee
            FROM predictions p
            JOIN tasks t ON p.task_id = t.id
            LEFT JOIN sprints s ON t.sprint_id = s.id
            ORDER BY p.created_at DESC
            LIMIT 50
        """)
        prediction_history = cur.fetchall()

        # Summary KPIs
        cur.execute("SELECT COUNT(*) AS total, AVG(risk_probability) AS avg_risk, AVG(predicted_hours) AS avg_hours FROM predictions")
        summary_stats = cur.fetchone()

        return render_template(
            "predictions.html",
            user=user,
            tasks=tasks,
            predictions=prediction_history,
            saved_predictions=prediction_history,
            result=result,
            prediction_result=result,
            selected_task_id=selected_task_id,
            summary_stats=summary_stats,
            error=error
        )

    except Exception as e:
        print("Predictions Load Error:", e)
        flash("Unable to load predictions page: " + str(e), "danger")
        return render_template(
            "predictions.html",
            user=user,
            tasks=[],
            predictions=[],
            saved_predictions=[],
            result=None,
            prediction_result=None,
            selected_task_id=None,
            summary_stats={"total": 0, "avg_risk": 0, "avg_hours": 0},
            error=str(e)
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@predictions_bp.route("/api/predict", methods=["POST"])
def api_predict():
    """Real-time instant prediction API for the interactive simulator."""
    data = request.get_json() or {}

    try:
        complexity = int(data.get("complexity", 3))
        priority = str(data.get("priority", "Medium")).title()
        dependencies = int(data.get("dependencies", 0))
        days_remaining = int(data.get("days_remaining", 7))
        team_workload = int(data.get("team_workload", 50))

        complexity = max(1, min(5, complexity))
        dependencies = max(0, min(5, dependencies))
        days_remaining = max(1, min(14, days_remaining))
        team_workload = max(30, min(110, team_workload))

        if priority not in ["Low", "Medium", "High", "Critical"]:
            priority = "Medium"

        effort = predict_effort(
            complexity=complexity,
            priority=priority,
            dependencies=dependencies,
            days_remaining=days_remaining,
            team_workload=team_workload
        )

        risk = predict_risk(
            complexity=complexity,
            priority=priority,
            dependencies=dependencies,
            days_remaining=days_remaining,
            team_workload=team_workload
        )

        return jsonify({
            "status": "success",
            "predicted_hours": round(float(effort), 1),
            "risk_probability": round(float(risk["risk_probability"]), 1),
            "risk_level": risk["risk_level"],
            "predicted_delay": risk.get("predicted_delay", False)
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@predictions_bp.route("/predictions/export")
def export_csv():
    conn = get_db_connection()
    cur = get_dict_cursor(conn)
    try:
        cur.execute("""
            SELECT p.id, t.title AS task_title, s.name AS sprint_name,
                   p.predicted_hours, p.risk_probability, p.risk_level,
                   p.model_version, p.created_at
            FROM predictions p
            JOIN tasks t ON p.task_id = t.id
            LEFT JOIN sprints s ON t.sprint_id = s.id
            ORDER BY p.created_at DESC
        """)
        records = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Prediction ID", "Task Title", "Sprint", "Predicted Hours", "Risk Probability (%)", "Risk Level", "Model Version", "Timestamp"])

        for r in records:
            writer.writerow([
                r["id"],
                r["task_title"],
                r.get("sprint_name") or "Unassigned",
                r["predicted_hours"],
                r["risk_probability"],
                r["risk_level"],
                r["model_version"],
                r["created_at"]
            ])

        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=sprintai_predictions_export.csv"}
        )
    finally:
        cur.close()
        conn.close()
