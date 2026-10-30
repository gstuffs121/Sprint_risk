
# SprintAI — AI-Driven Sprint Risk and Effort Estimation Engine

SprintAI is a web-based project management prototype that combines sprint and task tracking with machine-learning-based effort estimation and delay-risk prediction.

## Features

- Create and manage sprints
- Record tasks, priorities, complexity and dependencies
- Track task status and estimated/actual effort
- Predict task effort using a trained regression model
- Estimate delay risk using a trained classification model
- Store prediction history in MySQL
- View sprint statistics and project reports
- Responsive dashboard interface

## Technology stack

- Frontend: HTML, CSS, JavaScript, Chart.js
- Backend: Python and Flask
- Database: MySQL
- Machine learning: pandas, scikit-learn and joblib
- Models: Random Forest regression and classification

## Requirements

- Python 3.11 or a compatible Python version
- MySQL Server
- VS Code or another code editor

## Setup

### 1. Open the project directory

```powershell
cd D:\Users\Admin\Desktop\sprint_risk_engine
```

### 2. Activate the virtual environment

```powershell
.\venv\Scripts\Activate.ps1
```

If the environment has not been created yet:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root and set your local MySQL credentials:

```text
SECRET_KEY=replace-with-a-long-random-secret
MYSQL_HOST=localhost
MYSQL_USER=root
MYSQL_PASSWORD=your-local-mysql-password
MYSQL_DATABASE=sprint_risk_db
```

Replace the example password with your own local MySQL password. Never commit `.env` to GitHub.

### 5. Prepare the database

Create the `sprint_risk_db` database and its required tables using the project's database SQL script or the schema already created for your project.

### 6. Train the machine-learning models

If the model files do not exist, run:

```powershell
python ai/train_models.py
```

This creates the training dataset and saves the model files under `models/`.

### 7. Run the application

```powershell
python app.py
```

Open the local address shown in the terminal, normally:

http://127.0.0.1:5000/

## Main pages

- `/` — Dashboard
- `/sprints` — Sprint management
- `/tasks` — Task management
- `/predictions` — AI effort and delay-risk predictions
- `/reports` — Project reports
- `/health` — Basic application health endpoint

## Machine-learning inputs

The models use features including:

- Task complexity
- Task priority
- Number of dependencies
- Days remaining
- Team workload

The regression model estimates task effort. The classification model estimates the probability of delay.

## Important limitation

The initial dataset is synthetic and was generated for project demonstration and model development. Reported training/test metrics do not establish real-world performance. Validate the models using historical sprint data before relying on predictions for actual project decisions.

## Project structure

```text
sprint_risk_engine/
├── ai/
├── dataset/
├── models/
├── routes/
├── templates/
├── static/
│   ├── css/
│   ├── js/
│   └── images/
├── tests/
├── utils/
├── app.py
├── config.py
├── database.py
├── database.sql
├── requirements.txt
└── README.md
```
