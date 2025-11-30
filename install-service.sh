#!/bin/bash
# Install ElevenLabs Reader API as a systemd user service
# Run this script to enable automatic startup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="elevenlabs-reader"
SERVICE_FILE="${SCRIPT_DIR}/${SERVICE_NAME}.service"
USER_SERVICE_DIR="${HOME}/.config/systemd/user"
VENV_DIR="${SCRIPT_DIR}/venv"

echo "=== ElevenLabs Reader Service Installer ==="
echo ""

# Check if service file exists
if [[ ! -f "$SERVICE_FILE" ]]; then
    echo "Error: Service file not found at ${SERVICE_FILE}"
    exit 1
fi

# Create and set up virtual environment if it doesn't exist
if [[ ! -d "$VENV_DIR" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    echo "Installing dependencies..."
    "$VENV_DIR/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"
    echo "Virtual environment ready."
elif [[ ! -f "$VENV_DIR/bin/uvicorn" ]]; then
    echo "Installing missing dependencies..."
    "$VENV_DIR/bin/pip" install --quiet -r "${SCRIPT_DIR}/requirements.txt"
fi

# Create user systemd directory if it doesn't exist
mkdir -p "$USER_SERVICE_DIR"

# Copy/symlink the service file
echo "Installing service to ${USER_SERVICE_DIR}..."
cp "$SERVICE_FILE" "${USER_SERVICE_DIR}/${SERVICE_NAME}.service"

# Reload systemd user daemon
echo "Reloading systemd user daemon..."
systemctl --user daemon-reload

# Enable the service to start on login
echo "Enabling service to start automatically..."
systemctl --user enable "$SERVICE_NAME"

# Enable lingering so service starts even without login session
echo "Enabling user lingering (service will run at boot, not just on login)..."
loginctl enable-linger "$USER" 2>/dev/null || sudo loginctl enable-linger "$USER"

# Start the service now
echo "Starting the service..."
systemctl --user start "$SERVICE_NAME"

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Useful commands:"
echo "  Check status:    systemctl --user status ${SERVICE_NAME}"
echo "  View logs:       journalctl --user -u ${SERVICE_NAME} -f"
echo "  Stop service:    systemctl --user stop ${SERVICE_NAME}"
echo "  Restart:         systemctl --user restart ${SERVICE_NAME}"
echo "  Disable:         systemctl --user disable ${SERVICE_NAME}"
echo ""
echo "API available at: http://127.0.0.1:8011"
echo "Health check:     curl http://127.0.0.1:8011/healthz"

