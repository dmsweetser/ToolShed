#!/bin/bash
set -e

echo "=========================================="
echo "Uniswap Arbitrum Trading Bot - Runner"
echo "=========================================="

# Check virtual environment
if [ ! -d "venv" ]; then
    echo "Error: Virtual environment not found. Run install.sh first."
    exit 1
fi

# Activate virtual environment
source venv/bin/activate

# Run the bot
echo "Starting trading bot..."
echo "Press Ctrl+C to stop."
echo ""
python main.py

echo ""
echo "Bot stopped."