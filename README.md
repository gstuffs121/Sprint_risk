# SprintAI

**SprintAI** is a Flask web application for organizing projects, sprints, and tasks, with machine-learning estimates for task effort and schedule-delay risk. It combines a Jinja-rendered workspace, relational persistence, dashboard/report views, and two scikit-learn inference pipelines.

> **Prototype and model caveat:** the checked-in training pipeline generates synthetic demonstration data, not historical project outcomes. Its predictions and training metrics are not evidence of real-world accuracy. Use the ML output as an experimental aid, not as a delivery commitment or an automated decision.

![SprintAI architecture diagram](docs/architecture.svg)

## Contents

- [Features](#features)
- [Technology](#technology)
- [Architecture and workflows](#architecture-and-workflows)
- [Machine-learning implementation](#machine-learning-implementation)
- [Database design](#database-design)
- [Getting started](#getting-started)
- [Routes and interfaces](#routes-and-interfaces)
- [Testing and diagnostics](#testing-and-diagnostics)
- [Security and operational notes](#security-and-operational-notes)
- [Contributing](#contributing)
- [Potential roadmap](#potential-roadmap)
- [Known limitations and verification notes](#known-limitations-and-verification-notes)

## Features

- Organize projects, link sprints to projects, and manage task status, assignment, priority, complexity, dependencies, dates, and estimated/actual hours.
- View tasks as a Kanban board or table; filter by sprint, priority, and status, and update task status by drag-and-drop or the status selector.
- Review dashboard counts, sprint capacity, recent work, risk alerts, and charts.
- Run a task-effort estimate and delay-risk classification for an existing task, and retain prediction history in the database.
- Explore hypothetical feature combinations through the prediction page's what-if interface and JSON endpoint.
- Review reports and export sprint or prediction data as CSV.
- Use administrative pages for user and project oversight, system health, settings, audit logs, and ML artifact status. Administrative routes are guarded by an admin-role check.
- Start with MySQL or use the application's automatic SQLite fallback for local development.

The repository also includes a small sample dataset and serialized model artifacts. See [Known limitations](#known-limitations-and-verification-notes) before relying on them.

## Technology

| Area | Implementation |
| --- | --- |
| Web backend | Python, Flask, Flask Blueprints, Jinja templates |
| Browser UI | HTML, CSS, vanilla JavaScript; Chart.js and Lucide are loaded in templates from CDNs |
| Persistence | MySQL Connector/Python when configured and reachable; otherwise SQLite via `sqlite3` |
| ML and data | pandas, NumPy, scikit-learn pipelines, joblib model artifacts |
| Configuration | `python-dotenv` loads local environment settings from `.env` |
| Tests | Python `unittest` suites and standalone connection/prediction scripts |

Dependencies and pinned versions are listed in [`requirements.txt`](requirements.txt). The repository does not declare a supported Python version in a project manifest; use a Python version compatible with those pinned packages.

## Architecture and workflows

`app.py` creates the Flask app, loads `Config`, attempts database initialization, and registers the route Blueprints. The route modules use the database helpers directly and render Jinja templates or return JSON/CSV responses. `database.py` provides a dictionary-row-compatible wrapper for SQLite and a connection helper that tries MySQL first and falls back to a local `sprint_risk.db` SQLite file when it cannot connect. The browser's shared JavaScript handles Kanban updates and calls the JSON prediction endpoint.

The diagram above is an original overview of this request and data flow. Key code areas:

```text
app.py                 Flask app setup, initialization, Blueprint registration, /health
config.py              Environment-backed Flask and MySQL settings
database.py            MySQL/SQLite connections, schema initialization, audit logging
database.sql           MySQL schema definition
routes/                Authentication, projects, dashboard, sprints, tasks, predictions, reports, admin
ai/                    Training pipeline and effort/risk inference functions
dataset/               Demonstration CSV used by the training script
models/                Serialized effort and risk model artifacts
templates/             Jinja pages, admin views, and reusable partials
static/                Shared CSS and browser JavaScript
tests/                 unittest app, project, route, and security tests
utils/                 Input helpers and admin provisioning CLI
```

### Typical workspace flow

1. A user creates projects, sprints, and tasks through HTML forms. Route handlers in `routes/projects.py`, `routes/sprints.py`, and `routes/tasks.py` write records and call `log_audit` for relevant changes.
2. The dashboard and reports query projects, sprints, tasks, and prediction history to render summaries. The task board persists status changes through `POST /tasks/<task_id>/update-status`.
3. A user submits an existing task for a prediction. `routes/predictions.py` derives the model inputs from task fields and workload counts, calls `ai/effort_model.py` and `ai/risk_model.py`, and inserts the results into `predictions`.
4. The what-if UI sends hypothetical inputs to `POST /api/predict`; this endpoint returns results without recording a prediction-history row.

### Application startup and persistence

Importing `app.py` calls `init_db()`. The database helper creates the application's tables and may seed a starter project, sprints/tasks, a sample prediction, and settings if the corresponding tables are empty. With MySQL, the configured database must be available; [`database.sql`](database.sql) creates the named database and schema. If a MySQL connection attempt fails, the helper silently switches to SQLite in the repository directory. Check `/health` and the admin health page to see the active backend; do not assume the app is using MySQL just because MySQL settings are present.

## Machine-learning implementation

### Features and outputs

Both pipelines use the same five inputs:

- Numeric: `complexity`, `dependencies`, `days_remaining`, and `team_workload`.
- Categorical: `priority` (`Low`, `Medium`, `High`, or `Critical`).

The task-based prediction route derives remaining days from the task due date (or uses a default when absent), counts open tasks for the assignee or sprint, and clamps model inputs to configured ranges.

| Pipeline | Estimator | Output |
| --- | --- | --- |
| Effort | `RandomForestRegressor` | Estimated hours, rounded and floored at 0.5 hours |
| Delay risk | `RandomForestClassifier` | Probability for the delayed class, a threshold-based risk band, and a binary predicted-delay flag |

`ai/train_models.py` builds a scikit-learn `Pipeline` with `ColumnTransformer` preprocessing: numeric fields pass through and priority is one-hot encoded. It creates 600 reproducible synthetic rows (`numpy.random.default_rng(42)`), splits train/test data, trains the regression and classification models, then saves them to `models/effort_model.joblib` and `models/risk_model.joblib`. Its printed R² and accuracy scores are computed against synthetic holdout data and should not be read as production-quality model metrics.

Retrain locally with:

```bash
python ai/train_models.py
```

This regenerates `dataset/sprint_tasks.csv` and overwrites both model artifacts. The artifacts are serialized with joblib; only load model files from a trusted source.

### Important retraining mismatch

The admin handler in `routes/admin.py` imports `create_sample_dataset` and `train_models` from `ai.train_models`, but the checked-in module defines `create_sample_dataset()`, `build_pipeline()`, and `main()`—it does **not** define a `train_models()` function. Therefore the admin `POST /admin/ai/retrain` action currently cannot complete successfully as written. The command-line script `python ai/train_models.py` invokes `main()` and is the verified training entry point. This documentation does not describe the admin retraining action as working.

## Database design

`database.py` creates parallel SQLite/MySQL versions of the application's tables at startup. `database.sql` is the MySQL schema script. The central records and relationships are:

| Table | Purpose and relationships |
| --- | --- |
| `users` | User identity, password hash, role, and active state. Referenced by project ownership, sprint creator, and audit records. |
| `projects` | Project name/key/status and optional owner. A project can be linked to multiple sprints. |
| `sprints` | Project iteration, dates, capacity, and status. A sprint contains tasks. |
| `tasks` | Work item, priority, complexity, dependencies, effort, status, due date, and delay flag. References a sprint. |
| `predictions` | Historical predicted hours, risk probability/level, explanation, model version, and creator. References a task. |
| `audit_logs` | Recorded actions, optional user identity, details, and IP address. |
| `system_settings` | Key/value settings seeded by database initialization and editable in the admin UI. |

Foreign-key behavior in the schema includes cascade deletion from sprint to tasks and task to predictions, and set-null behavior for optional project/user references. SQLite enables foreign-key enforcement in its connection helper.

## Getting started

### Prerequisites

- Python installed with support for the versions pinned in `requirements.txt`.
- A local MySQL server and an already-created database if you want to use MySQL. SQLite is used automatically if the MySQL connector cannot establish a connection.
- Git and a terminal.

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/gstuffs121/Sprint_risk.git
cd Sprint_risk
python -m venv .venv
```

Activate it:

```bash
# macOS / Linux
source .venv/bin/activate

# Windows PowerShell
.venv\Scripts\Activate.ps1
```

### 2. Install Python dependencies

```bash
python -m pip install -r requirements.txt
```

### 3. Configure local settings

Create a root-level `.env` file. The file is ignored by Git; do not commit real credentials or secret values.

```dotenv
SECRET_KEY=replace-with-a-long-random-value
MYSQL_HOST=localhost
MYSQL_USER=your_local_database_user
MYSQL_PASSWORD=your_local_database_password
MYSQL_DATABASE=sprint_risk_db
```

`config.py` provides development defaults, including a placeholder secret and default MySQL connection values. Do not rely on these defaults outside local development. If MySQL is selected, create the database and tables using `database.sql` or ensure the configured database already exists before starting the application. If MySQL is unreachable, startup falls back to SQLite instead.

Optional initial administrator provisioning through `init_db()` uses `INITIAL_ADMIN_USERNAME` and `INITIAL_ADMIN_PASSWORD` (password length of at least eight characters); `INITIAL_ADMIN_EMAIL` is optional. Do not put an actual password in a command, commit it, or share it in logs. Alternatively, provision an administrator interactively using the CLI described below.

### 4. Ensure model artifacts are available

The repository includes `models/effort_model.joblib` and `models/risk_model.joblib`. If these files are absent or you intentionally want to regenerate them, run:

```bash
python ai/train_models.py
```

This uses synthetic demonstration data and overwrites the dataset/model files. Do not interpret its metrics as real-world validation.

### 5. Start the development server

```bash
python app.py
```

The app listens on port `5000`; open <http://127.0.0.1:5000/>. `FLASK_DEBUG=true` enables Flask debug mode in `app.py`; keep it disabled for any non-development use. This repository documents the built-in Flask development server only and does not specify a production deployment configuration.

### Create an administrator (optional)

The CLI prompts for missing values and prompts for the password without echoing it:

```bash
python -m utils.create_admin
```

It validates the username, email, and minimum password length, hashes the password, creates an `admin` account, and records an audit event. The CLI also accepts `--username`, `--email`, and `--fullname`. Avoid passing a real password with `--password`, since command-line arguments may be visible to other local processes or stored in shell history.

## Routes and interfaces

The following are the principal routes declared in the route modules and `app.py`. Routes that create, edit, or delete data generally use HTML form submissions; task status changes also accept JSON.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/` | Dashboard workspace |
| `GET`, `POST` | `/login`, `/register` | Sign in and public registration |
| `GET` | `/logout` | Clear the current session |
| `GET`, `POST` | `/profile` | View/update the signed-in user's profile |
| `GET`, `POST` | `/projects` | List and create projects |
| `GET` | `/projects/<project_id>` | Project detail |
| `POST` | `/projects/<project_id>/edit`, `/projects/<project_id>/delete` | Edit or delete a project |
| `GET` | `/api/projects` | Project list JSON for UI dropdowns |
| `GET`, `POST` | `/sprints` | List and create sprints |
| `GET` | `/sprints/<sprint_id>` | Sprint detail |
| `POST` | `/sprints/<sprint_id>/edit`, `/sprints/<sprint_id>/delete` | Edit or delete a sprint |
| `GET`, `POST` | `/tasks` | Task board/table and task creation |
| `POST` | `/tasks/<task_id>/update-status` | Update status; JSON requests receive JSON responses |
| `POST` | `/tasks/<task_id>/edit`, `/tasks/<task_id>/delete` | Edit or delete a task |
| `GET`, `POST` | `/predictions` | Prediction page and stored-task prediction submissions |
| `POST` | `/api/predict` | Stateless what-if prediction JSON endpoint |
| `GET` | `/predictions/export` | Prediction-history CSV export |
| `GET` | `/reports` | Project/sprint/task analytics page |
| `GET` | `/reports/export`, `/reports/export-sprints` | Sprint CSV export aliases |
| `GET` | `/health` | JSON database/app health check |
| `GET` | `/api/chart-data` | Dashboard chart data JSON |
| `GET` | `/admin/` | Admin overview |
| `GET` | `/admin/users`, `/admin/projects`, `/admin/sprints`, `/admin/tasks` | Administrative oversight pages |
| `POST` | `/admin/users/create`, `/admin/users/<user_id>/toggle-status`, `/admin/users/<user_id>/edit-role`, `/admin/users/<user_id>/delete` | Admin user-management actions |
| `GET` | `/admin/ai`, `/admin/health`, `/admin/logs`, `/admin/settings` | ML status, system health, audit logs, and settings |
| `POST` | `/admin/ai/retrain`, `/admin/settings` | Admin retraining action (currently mismatched; see above) and settings update |

`app.py` also registers legacy `/app/...` URL aliases for dashboard, projects, sprints, tasks, predictions, reports, and chart data. Admin pages are protected by `admin_required` on the admin Blueprint.

## Testing and diagnostics

Run the repository's `unittest` test files with:

```bash
python -m unittest discover -s tests -v
```

There is no checked-in test configuration or CI workflow in the inspected repository. The tests initialize and access the configured application database; use a disposable local database or isolated environment and account for the startup seed/test data before running them against any data you care about.

Additional manual diagnostics are available:

```bash
python test_connection.py
python test_prediction.py
```

`test_prediction.py` loads the serialized models and prints an example effort/risk result. It requires both model files and installed dependencies. These commands were identified from repository files; this documentation update does not claim that they were executed as part of this change.

## Security and operational notes

### Behaviors present in the code

- Passwords are stored as Werkzeug-generated password hashes and checked during login.
- Public registration forces the new account role to `user`; it does not accept a submitted role as authority.
- The admin Blueprint checks the session role on every request and records unauthorized admin access attempts.
- Flask session cookies are configured `HttpOnly` and `SameSite=Lax` in `app.py`.
- An initial administrator can be provisioned from explicit environment variables or through the interactive CLI; there is no predictable default admin account creation in `init_db()`.
- `.env`, local SQLite files, and serialized model artifacts are ignored by `.gitignore` (the model artifacts currently present in the repository are tracked files).

### Do not assume production hardening

The project has no documented production server, TLS, reverse-proxy, or deployment configuration. `config.py` has development fallback values, and `app.py` does not set the `Secure` cookie flag. Several workspace route handlers do not apply `login_required`; only routes that explicitly use the decorator are protected by it, while the admin Blueprint has its own global guard. Review and harden authorization, CSRF coverage, session settings, debug behavior, database permissions/backups, and error/log handling before exposing an instance beyond a trusted local environment. The presence of security-related helpers or tests is not a security certification.

Treat user-controlled task/project data as sensitive. Do not include real database credentials, secret keys, passwords, or private task data in issues, logs, screenshots, commits, or this README.

## Contributing

Contributions should remain grounded in the implementation and include appropriate tests or reproducible verification steps.

1. Open an issue describing the behavior or documentation change before substantial work.
2. Create a focused branch and keep changes scoped to the agreed task.
3. Add or update tests for behavior changes; do not use production or valuable local data for test runs.
4. Run the relevant tests and describe any environment-dependent checks that could not be run.
5. Open a pull request with a concise summary, testing notes, and known limitations.

No `CONTRIBUTING.md` or license file was present in the inspected repository. Check with the repository owner before assuming a contribution license or adding licensing terms.

## Potential roadmap

These are possible follow-up areas suggested by the current implementation, not a published project commitment:

- Replace synthetic-only model training with a documented, privacy-conscious evaluation process based on representative data.
- Repair and test the admin retraining integration so its imports match the training-module API, or remove/disable the unsupported action.
- Add stronger route-level authorization and request protection consistently across workspace-changing endpoints.
- Add isolated test-database configuration and repeatable automated test execution.
- Document supported Python versions, deployment/runtime operations, schema migrations, and backup/recovery procedures.
- Review prediction calibration, validation strategy, model artifact provenance, and monitoring before any operational use.

## Known limitations and verification notes

- Training labels and targets are generated from formulas and random noise in `ai/train_models.py`; the checked-in CSV/model files do not establish that the models learned from historical production work.
- The admin retraining route references a missing `train_models` symbol and is not operational as written; the standalone `python ai/train_models.py` script is the available training entry point.
- SQLite fallback is automatic after MySQL connection failure and can change which database receives writes. Confirm the active backend before relying on persisted data.
- `database.py` initializes and seeds data on application startup, so a first run may create example records.
- The exact supported Python runtime and production deployment process are not specified by a project manifest or deployment files.
- No license, contribution policy document, or CI workflow was found in the repository root inventory.
