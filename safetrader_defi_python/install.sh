#!/bin/bash
set -e

echo "=========================================="
echo "Uniswap Arbitrum Trading Bot - Installer"
echo "=========================================="

# Check Python 3.8+
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed."
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if [[ ! $PYTHON_VERSION =~ ^(3\.[8-9]|3\.1[0-9])$ ]]; then
    echo "Error: Python 3.8+ is required. Found: $PYTHON_VERSION"
    exit 1
fi

echo "Python version: $PYTHON_VERSION"

# Create virtual environment
echo "Creating Python virtual environment..."
python3 -m venv venv

# Activate and install dependencies
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=========================================="
echo "Installation complete!"
echo "=========================================="
echo ""
echo "To run the bot:"
echo "  source venv/bin/activate"
echo "  python main.py"
echo ""
echo "Or use: ./run.sh"
echo "=========================================="