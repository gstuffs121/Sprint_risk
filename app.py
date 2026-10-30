
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    jsonify
)

from datetime import date, datetime

from config import Config
from database import get_db_connection

from ai.effort_model import predict_effort
from ai.risk_model import predict_risk


# =========================================================
# FLASK CONFIGURATION
# =========================================================

app = Flask(__name__)
app.config.from_object(Config)

# Ensure Flask has a secret key for flash messages and sessions
if not app.secret_key:
    app.secret_key = "sprintai-development-secret-key"


# =========================================================
# DATABASE HELPER FUNCTIONS
# =========================================================

def get_connection():
    return get_db_connection()


def get_dict_cursor(connection):
    return connection.cursor(dictionary=True)


# =========================================================
# DASHBOARD
# =========================================================

@app.route("/")
def dashboard():

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        # Total sprints
        cursor.execute("SELECT COUNT(*) AS total FROM sprints")
        total_sprints = cursor.fetchone()["total"]

        # Total tasks
        cursor.execute("SELECT COUNT(*) AS total FROM tasks")
        total_tasks = cursor.fetchone()["total"]

        # Completed tasks
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM tasks
            WHERE status = 'completed'
        """)
        completed_tasks = cursor.fetchone()["total"]

        # Delayed tasks
        cursor.execute("""
            SELECT COUNT(*) AS total
            FROM tasks
            WHERE is_delayed = 1
        """)
        delayed_tasks = cursor.fetchone()["total"]

        # Total estimated hours
        cursor.execute("""
            SELECT COALESCE(SUM(estimated_hours), 0) AS total
            FROM tasks
        """)
        estimated_hours = cursor.fetchone()["total"]

        # Recent sprints
        cursor.execute("""
            SELECT *
            FROM sprints
            ORDER BY created_at DESC
            LIMIT 5
        """)
        recent_sprints = cursor.fetchall()

        # Recent tasks
        cursor.execute("""
            SELECT t.*, s.name AS sprint_name
            FROM tasks t
            LEFT JOIN sprints s ON t.sprint_id = s.id
            ORDER BY t.created_at DESC
            LIMIT 5
        """)
        recent_tasks = cursor.fetchall()

        return render_template(
            "dashboard.html",
            total_sprints=total_sprints,
            total_tasks=total_tasks,
            completed_tasks=completed_tasks,
            delayed_tasks=delayed_tasks,
            estimated_hours=estimated_hours,
            recent_sprints=recent_sprints,
            recent_tasks=recent_tasks
        )

    except Exception as e:
        print("Dashboard Error:", e)
        flash("Unable to load dashboard: " + str(e), "danger")
        return render_template(
            "dashboard.html",
            total_sprints=0,
            total_tasks=0,
            completed_tasks=0,
            delayed_tasks=0,
            estimated_hours=0,
            recent_sprints=[],
            recent_tasks=[]
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# DATABASE HEALTH CHECK
# =========================================================

@app.route("/health")
def health():

    connection = None

    try:
        connection = get_connection()

        return jsonify({
            "status": "success",
            "message": "SprintAI database connected successfully"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if connection:
            connection.close()


# =========================================================
# TASK CHART DATA
# =========================================================

@app.route("/api/chart-data")
def chart_data():

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        cursor.execute("""
            SELECT status, COUNT(*) AS total
            FROM tasks
            GROUP BY status
        """)

        results = cursor.fetchall()

        labels = []
        values = []

        for row in results:
            labels.append(row["status"])
            values.append(row["total"])

        return jsonify({
            "labels": labels,
            "values": values
        })

    except Exception as e:
        print("Chart Error:", e)
        return jsonify({
            "labels": [],
            "values": [],
            "error": str(e)
        }), 500

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# SPRINT MANAGEMENT
# =========================================================

@app.route("/sprints", methods=["GET", "POST"])
def sprints():

    connection = None
    cursor = None

    if request.method == "POST":

        name = request.form.get("name", "").strip()
        goal = request.form.get("goal", "").strip()
        start_date = request.form.get("start_date")
        end_date = request.form.get("end_date")
        capacity_hours = request.form.get("capacity_hours")
        status = request.form.get("status", "planned")

        if not name or not start_date or not end_date or not capacity_hours:
            flash("Please fill all required sprint fields.", "danger")
            return redirect(url_for("sprints"))

        try:
            capacity_hours = float(capacity_hours)

            if capacity_hours <= 0:
                flash("Capacity hours must be greater than zero.", "danger")
                return redirect(url_for("sprints"))

            if date.fromisoformat(end_date) < date.fromisoformat(start_date):
                flash("End date cannot be before start date.", "danger")
                return redirect(url_for("sprints"))

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                INSERT INTO sprints
                (name, goal, start_date, end_date, capacity_hours, status)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                name,
                goal,
                start_date,
                end_date,
                capacity_hours,
                status
            ))

            connection.commit()

            flash("Sprint created successfully!", "success")

        except Exception as e:
            if connection:
                connection.rollback()

            print("Sprint Error:", e)
            flash("Unable to create sprint: " + str(e), "danger")

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        return redirect(url_for("sprints"))

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        cursor.execute("""
            SELECT *
            FROM sprints
            ORDER BY created_at DESC
        """)

        sprint_list = cursor.fetchall()

        return render_template(
            "sprints.html",
            sprints=sprint_list,
            sprint_list=sprint_list
        )

    except Exception as e:
        print("Sprint Loading Error:", e)
        flash("Unable to load sprints: " + str(e), "danger")

        return render_template(
            "sprints.html",
            sprints=[],
            sprint_list=[]
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# TASK MANAGEMENT
# =========================================================

@app.route("/tasks", methods=["GET", "POST"])
def tasks():

    connection = None
    cursor = None

    if request.method == "POST":

        sprint_id = request.form.get("sprint_id")
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        assignee = request.form.get("assignee", "").strip()
        priority = request.form.get("priority", "Medium").title()
        complexity = request.form.get("complexity", "3")
        dependencies = request.form.get("dependencies", "0")
        estimated_hours = request.form.get("estimated_hours", "0")
        due_date = request.form.get("due_date")

        if not sprint_id or not title:
            flash("Please select a sprint and enter a task title.", "danger")
            return redirect(url_for("tasks"))

        try:
            complexity = max(1, min(5, int(complexity)))
            dependencies = max(0, min(5, int(dependencies)))
            estimated_hours = float(estimated_hours)

            if estimated_hours < 0:
                flash("Estimated hours cannot be negative.", "danger")
                return redirect(url_for("tasks"))

            if priority not in ["Low", "Medium", "High", "Critical"]:
                priority = "Medium"

            connection = get_connection()
            cursor = connection.cursor()

            cursor.execute("""
                INSERT INTO tasks (
                    sprint_id,
                    title,
                    description,
                    assignee,
                    priority,
                    complexity,
                    dependencies,
                    estimated_hours,
                    actual_hours,
                    status,
                    is_delayed,
                    due_date
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                sprint_id,
                title,
                description,
                assignee,
                priority,
                complexity,
                dependencies,
                estimated_hours,
                0,
                "todo",
                0,
                due_date if due_date else None
            ))

            connection.commit()

            flash("Task created successfully!", "success")

        except Exception as e:
            if connection:
                connection.rollback()

            print("Task Error:", e)
            flash("Unable to create task: " + str(e), "danger")

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

        return redirect(url_for("tasks"))

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        cursor.execute("""
            SELECT *
            FROM tasks
            ORDER BY created_at DESC
        """)
        task_list = cursor.fetchall()

        cursor.execute("""
            SELECT *
            FROM sprints
            ORDER BY created_at DESC
        """)
        sprint_list = cursor.fetchall()

        return render_template(
            "tasks.html",
            tasks=task_list,
            task_list=task_list,
            sprints=sprint_list
        )

    except Exception as e:
        print("Task Loading Error:", e)
        flash("Unable to load tasks: " + str(e), "danger")

        return render_template(
            "tasks.html",
            tasks=[],
            task_list=[],
            sprints=[]
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# AI EFFORT ESTIMATION AND RISK PREDICTION
# =========================================================

@app.route("/predictions", methods=["GET", "POST"])
def predictions():

    connection = None
    cursor = None

    result = None
    error = None

    if request.method == "POST":

        task_id = request.form.get("task_id")

        try:
            connection = get_connection()
            cursor = get_dict_cursor(connection)

            cursor.execute("""
                SELECT *
                FROM tasks
                WHERE id = %s
            """, (task_id,))

            task = cursor.fetchone()

            if not task:
                raise ValueError("Selected task was not found.")

            # ---------------------------------------------
            # INPUT PREPARATION
            # ---------------------------------------------

            complexity = int(task.get("complexity") or 3)
            complexity = max(1, min(5, complexity))

            priority = str(
                task.get("priority") or "Medium"
            ).title()

            if priority not in ["Low", "Medium", "High", "Critical"]:
                priority = "Medium"

            dependencies = int(task.get("dependencies") or 0)
            dependencies = max(0, min(5, dependencies))

            # Calculate remaining days
            if task.get("due_date"):
                due_date = task["due_date"]

                if isinstance(due_date, datetime):
                    due_date = due_date.date()
                elif isinstance(due_date, str):
                    due_date = date.fromisoformat(due_date)

                days_remaining = (due_date - date.today()).days
            else:
                days_remaining = 7

            days_remaining = max(1, min(14, days_remaining))

            # Calculate team workload
            if task.get("assignee"):
                cursor.execute("""
                    SELECT COUNT(*) AS total
                    FROM tasks
                    WHERE assignee = %s
                    AND status != 'completed'
                """, (task["assignee"],))
            else:
                cursor.execute("""
                    SELECT COUNT(*) AS total
                    FROM tasks
                    WHERE sprint_id = %s
                    AND status != 'completed'
                """, (task["sprint_id"],))

            open_tasks = cursor.fetchone()["total"]

            team_workload = max(
                30,
                min(110, 30 + open_tasks * 10)
            )

            # ---------------------------------------------
            # AI MODEL PREDICTIONS
            # ---------------------------------------------

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

            risk_probability = float(
                risk["risk_probability"]
            )

            risk_level = risk["risk_level"]

            explanation = (
                "Prediction is based on task complexity, priority, "
                "dependencies, remaining days and team workload."
            )

            # ---------------------------------------------
            # SAVE PREDICTION IN DATABASE
            # ---------------------------------------------

            cursor.execute("""
                INSERT INTO predictions (
                    task_id,
                    predicted_hours,
                    risk_probability,
                    risk_level,
                    explanation,
                    model_version
                )
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                task_id,
                predicted_hours,
                risk_probability,
                risk_level,
                explanation,
                "v1-synthetic-demo"
            ))

            connection.commit()

            result = {
                "title": task["title"],
                "task_title": task["title"],
                "effort": predicted_hours,
                "predicted_hours": predicted_hours,
                "risk_probability": round(risk_probability, 2),
                "risk_level": risk_level,
                "predicted_delay": risk.get("predicted_delay", False),
                "explanation": explanation
            }

            flash("AI prediction generated successfully!", "success")

        except Exception as e:
            if connection:
                connection.rollback()

            print("Prediction Error:", e)
            error = str(e)
            flash("Unable to generate prediction: " + error, "danger")

        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()

    # ---------------------------------------------
    # LOAD TASKS AND SAVED PREDICTIONS
    # ---------------------------------------------

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        cursor.execute("""
            SELECT id, title
            FROM tasks
            ORDER BY created_at DESC
        """)
        task_list = cursor.fetchall()

        cursor.execute("""
            SELECT
                p.*,
                t.title AS task_title
            FROM predictions p
            JOIN tasks t ON p.task_id = t.id
            ORDER BY p.created_at DESC
        """)
        saved_predictions = cursor.fetchall()

        return render_template(
            "predictions.html",
            tasks=task_list,
            predictions=saved_predictions,
            saved_predictions=saved_predictions,
            result=result,
            prediction_result=result,
            selected_task_id=request.form.get("task_id"),
            message=None,
            error=error
        )

    except Exception as e:
        print("Prediction Loading Error:", e)
        flash("Unable to load predictions: " + str(e), "danger")

        return render_template(
            "predictions.html",
            tasks=[],
            predictions=[],
            saved_predictions=[],
            result=result,
            prediction_result=result,
            selected_task_id=None,
            message=None,
            error=str(e)
        )

    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


# =========================================================
# REPORTS
# =========================================================

@app.route("/reports")
def reports():

    connection = None
    cursor = None

    try:
        connection = get_connection()
        cursor = get_dict_cursor(connection)

        # ---------------------------------------------
        # TASK STATISTICS
        # ---------------------------------------------

        cursor.execute("""
            SELECT
                COUNT(*) AS total_tasks,

                COALESCE(SUM(
                    CASE
                        WHEN status = 'completed'
                        THEN 1 ELSE 0
                    END
                ), 0) AS completed_tasks,

                COALESCE(SUM(
                    CASE
                        WHEN is_delayed = 1
                        THEN 1 ELSE 0
                    END
                ), 0) AS delayed_tasks,

                AVG(estimated_hours) AS average_estimated_hours,

                AVG(actual_hours) AS average_actual_hours

            FROM tasks
        """)

        task_stats = cursor.fetchone()

        # ---------------------------------------------
        # AI PREDICTION STATISTICS
        # ---------------------------------------------

        cursor.execute("""
            SELECT
                COUNT(*) AS total_predictions,
                AVG(risk_probability) AS average_risk
            FROM predictions
        """)

        prediction_stats = cursor.fetchone()

        # ---------------------------------------------
        # SPRINT PERFORMANCE
        # ---------------------------------------------

        cursor.execute("""
            SELECT
                s.id,
                s.name,
                s.status,
                s.created_at,

                COUNT(t.id) AS task_count,

                COALESCE(SUM(
                    CASE
                        WHEN t.status = 'completed'
                        THEN 1 ELSE 0
                    END
                ), 0) AS completed_count,

                COALESCE(SUM(
                    CASE
                        WHEN t.is_delayed = 1
                        THEN 1 ELSE 0
                    END
                ), 0) AS delayed_count

            FROM sprints s

            LEFT JOIN tasks t
                ON s.id = t.sprint_id

            GROUP BY
                s.id,
                s.name,
                s.status,
                s.created_at

            ORDER BY s.created_at DESC
        """)

        sprint_stats = cursor.fetchall()

        return render_template(
            "reports.html",
            task_stats=task_stats,
            prediction_stats=prediction_stats,
            sprint_stats=sprint_stats
        )

    except Exception as e:

        if connection:
            connection.rollback()

        print("Reports Error:", e)

        flash(
            "Unable to generate reports: " + str(e),
            "danger"
        )

        return render_template(
            "reports.html",

            task_stats={
                "total_tasks": 0,
                "completed_tasks": 0,
                "delayed_tasks": 0,
                "average_estimated_hours": None,
                "average_actual_hours": None
            },

            prediction_stats={
                "total_predictions": 0,
                "average_risk": None
            },

            sprint_stats=[]
        )

    finally:
        if cursor:
            cursor.close()

        if connection:
            connection.close()


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    app.run(debug=True)
