#!/bin/bash
set -e
echo "Activating virtual environment..."
source venv/bin/activate
export FLASK_APP=app.py
export FLASK_ENV=development
echo "Starting Flask application..."
python app.py