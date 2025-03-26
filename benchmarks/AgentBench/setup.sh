#!/bin/bash

# Change to the directory of the script
cd "$(dirname "$0")" || {
    echo "Error: Failed to change to script directory."
    exit 1
}

# Check if Conda environment exists
if conda info --envs | grep -q "agent-bench"; then
    echo "Conda environment 'agent-bench' already exists. Skipping creation."
else
    # Create a new Conda environment
    conda create -n agent-bench python=3.9 -y || {
        echo "Error: Failed to create Conda environment."
        exit 1
    }
fi

source "$(conda info --base)/etc/profile.d/conda.sh"

# Activate the Conda environment
conda activate agent-bench || {
    echo "Error: Failed to activate Conda environment. Please ensure Conda is properly installed."
    exit 1
}

# Install dependencies
pip install -r requirements.txt || {
    echo "Error: Failed to install dependencies."
    exit 1
}

# Ensure Docker is installed and running
docker ps > /dev/null 2>&1 || {
    echo "Error: Docker is not installed or running. Please install and start Docker before running this script."
    exit 1
}

# Function to check if a Docker image exists locally
image_exists() {
    docker images -q "$1" 2> /dev/null
}

# Pull required Docker images
echo "Checking and pulling Docker images..."
if [ -z "$(image_exists ubuntu)" ]; then
    docker pull ubuntu || {
        echo "Error: Failed to pull 'ubuntu' image."
        exit 1
    }
else
    echo "'ubuntu' image already exists. Skipping pull."
fi

# Build custom Docker images
echo "Checking and building custom Docker images..."
if [ -z "$(image_exists local-os/default)" ]; then
    docker build -f data/os_interaction/res/dockerfiles/default data/os_interaction/res/dockerfiles --tag local-os/default || {
        echo "Error: Failed to build 'local-os/default' Docker image."
        exit 1
    }
else
    echo "'local-os/default' image already exists. Skipping build."
fi

if [ -z "$(image_exists local-os/packages)" ]; then
    docker build -f data/os_interaction/res/dockerfiles/packages data/os_interaction/res/dockerfiles --tag local-os/packages || {
        echo "Error: Failed to build 'local-os/packages' Docker image."
        exit 1
    }
else
    echo "'local-os/packages' image already exists. Skipping build."
fi

if [ -z "$(image_exists local-os/ubuntu)" ]; then
    docker build -f data/os_interaction/res/dockerfiles/ubuntu data/os_interaction/res/dockerfiles --tag local-os/ubuntu || {
        echo "Error: Failed to build 'local-os/ubuntu' Docker image."
        exit 1
    }
else
    echo "'local-os/ubuntu' image already exists. Skipping build."
fi

# Check if OPENAI_API_KEY environment variable is set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable is not set."
    echo "Please set the environment variable using the command: export OPENAI_API_KEY=your_api_key"
    exit 1
else
    echo "OPENAI_API_KEY is set. Proceeding with the setup."
fi

echo "Setup completed successfully."
