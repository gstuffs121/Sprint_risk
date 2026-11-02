from datetime import datetime
from flask import (
    Flask,
    render_template,
    jsonify,
    redirect,
    url_for,
    session,
    request
)

from config import Config
from database import (
    get_db_connection,
    init_db,
    get_active_engine,
    test_db_connection
)

# Import Blueprints
from routes.auth import auth_bp, get_current_user
from routes.dashboard import dashboard_bp, index as dashboard_view, chart_data as chart_data_view
from routes.sprints import sprints_bp, index as sprints_view
from routes.tasks import tasks_bp, index as tasks_view
from routes.predictions import predictions_bp, index as predictions_view
from routes.reports import reports_bp, index as reports_view
from routes.admin import admin_bp

# =========================================================
# FLASK APPLICATION FACTORY
# =========================================================

app = Flask(__name__)
app.config.from_object(Config)

# Ensure secret key and cookie security flags are configured
import os
import secrets
if not app.secret_key:
    app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

# Automatically verify / initialize database tables and seed baseline data
try:
    init_db()
except Exception as e:
    print("Database init warning on startup:", e)

# =========================================================
# BLUEPRINT REGISTRATIONS
# =========================================================

app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(sprints_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(predictions_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(admin_bp)


# =========================================================
# CONTEXT PROCESSORS & GLOBAL HELPERS
# =========================================================

@app.context_processor
def inject_globals():
    """Make current_user and system metadata available across all Jinja templates."""
    user = get_current_user()
    return {
        "current_user": user,
        "is_admin": user.get("role") == "admin" if user else False,
        "active_engine": get_active_engine(),
        "current_year": datetime.now().year,
        "now": datetime.now()
    }


# =========================================================
# LEGACY & BACKWARD-COMPATIBLE ROUTE ALIASES
# (Ensures all existing tests, links and url_for calls work)
# =========================================================

@app.route("/health")
def health():
    """Application and database health endpoint."""
    try:
        active_db = test_db_connection()
        return jsonify({
            "status": "success",
            "message": "SprintAI database connected successfully",
            "database": active_db,
            "engine": get_active_engine()
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


# Endpoint aliases for url_for compatibility
app.add_url_rule("/app/dashboard", endpoint="dashboard", view_func=dashboard_view)
app.add_url_rule("/app/sprints", endpoint="sprints", view_func=sprints_view)
app.add_url_rule("/app/tasks", endpoint="tasks", view_func=tasks_view)
app.add_url_rule("/app/predictions", endpoint="predictions", view_func=predictions_view)
app.add_url_rule("/app/reports", endpoint="reports", view_func=reports_view)
app.add_url_rule("/app/chart-data", endpoint="chart_data", view_func=chart_data_view)


# =========================================================
# ERROR HANDLERS
# =========================================================

@app.errorhandler(404)
def page_not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(500)
def server_error(e):
    return render_template(
        "404.html",
        error_code="500",
        error_title="Server Error",
        error_message="An unexpected server error occurred. Please try again."
    ), 500


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    is_debug = os.getenv("FLASK_DEBUG", "False").lower() in ["true", "1"]
    app.run(debug=is_debug, port=5000)
