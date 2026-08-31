#!/bin/bash

# Activate virtual environment
if [ ! -d "venv" ]; then
    echo "Error: virtual environment not found. Run ./install.sh first."
    exit 1
fi

source venv/bin/activate

# Forward all arguments directly to the Python script
python3 app.py

exit $?
