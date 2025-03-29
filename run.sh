#!/bin/bash

# Display header
echo "======================================"
echo "Earthquake Emergency Lost and Found Bot"
echo "======================================"
echo "Using python-telegram-bot v20+"
echo "======================================"

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

# Define environment directory
VENV_DIR="venv"

# Check if the virtual environment exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Setting up Python virtual environment for the first time..."
    python3 -m venv $VENV_DIR
    if [ $? -ne 0 ]; then
        echo "Failed to create virtual environment."
        exit 1
    fi
    echo "Environment created successfully!"
    
    # Activate the environment and install dependencies
    source $VENV_DIR/bin/activate
    pip install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "Failed to install dependencies. Please check requirements.txt file."
        deactivate
        exit 1
    fi
else
    echo "Environment already exists. Updating dependencies..."
    source $VENV_DIR/bin/activate
    pip install -r requirements.txt
fi

# Run the bot application
echo "Starting the bot..."
python app.py

# Deactivate the environment when done
deactivate
echo "Bot stopped. Environment deactivated."
