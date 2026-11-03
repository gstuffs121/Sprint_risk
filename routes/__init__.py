from routes.auth import auth_bp
from routes.projects import projects_bp
from routes.dashboard import dashboard_bp
from routes.sprints import sprints_bp
from routes.tasks import tasks_bp
from routes.predictions import predictions_bp
from routes.reports import reports_bp
from routes.admin import admin_bp

__all__ = [
    "auth_bp",
    "projects_bp",
    "dashboard_bp",
    "sprints_bp",
    "tasks_bp",
    "predictions_bp",
    "reports_bp",
    "admin_bp"
]
