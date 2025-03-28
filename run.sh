#!/bin/bash

# Display header
echo "======================================"
echo "Earthquake Emergency Lost and Found Bot"
echo "======================================"
echo "Using python-telegram-bot v20+"
echo "======================================"

# Check if conda is installed
if ! command -v conda &> /dev/null; then
    echo "Conda is not installed. Please install Miniconda or Anaconda first."
    exit 1
fi

# Check if the environment exists
if ! conda env list | grep -q "lost_and_found_bot"; then
    echo "Setting up conda environment for the first time..."
    conda env create -f environment.yml
    if [ $? -ne 0 ]; then
        echo "Failed to create conda environment. Please check environment.yml file."
        exit 1
    fi
    echo "Environment created successfully!"
else
    echo "Environment already exists. Updating dependencies..."
    conda env update -f environment.yml
fi

# Activate the environment and run the bot
echo "Starting the bot..."
eval "$(conda shell.bash hook)"
conda activate lost_and_found_bot

# Run the bot application
python app.py

# Deactivate the environment when done
conda deactivate
echo "Bot stopped. Environment deactivated."
