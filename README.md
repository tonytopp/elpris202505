# Electricity Price Controller

A web application that controls MQTT devices based on electricity prices from elprisetjustnu.se API, with SMHI weather integration for Vänersborg (hardcoded).

## Features

- Real-time electricity price monitoring (Today and Tomorrow for SE3)
- SMHI weather integration for Vänersborg (temperature)
- MQTT support for device control (Device1, Device2)
- Responsive web interface (Bootstrap 5, Chart.js)
- Displays current and forecasted electricity prices
- Control MQTT devices with price thresholds
- Configuration for MQTT broker details via API and saved to `.env` file.
- Logging of application activity and errors to `app_run.log`.

## Prerequisites

- Python 3.8+
- pip (Python package manager)
- An MQTT broker (e.g., mosquitto, HiveMQ)

## Setup

1.  **Clone the repository (once it's on GitHub):**
    ```bash
    git clone <repository-url-you-will-create>
    cd elpris202505
    ```
2.  **Create a virtual environment (recommended):**
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
4.  **Configure environment variables:**
    Copy `.env.example` to a new file named `.env`.
    ```bash
    cp .env.example .env
    ```
    Review and edit the `.env` file with your actual MQTT broker details and a strong `SECRET_KEY` if desired (though the app has defaults and can save MQTT settings via its API).

5.  **Run the application:**
    ```bash
    python app.py
    ```
6.  Open `http://127.0.0.1:5000` in your browser.

## Configuration via Web Interface

- **MQTT Broker Settings:** Can be configured via the `/api/mqtt/update` endpoint (typically through a settings page in the web UI if implemented). These settings are saved to the `.env` file.
- **Device Thresholds:** Can be managed via the `/api/devices` endpoint.

## MQTT Topics (Example for default devices)

- `home/device1/state` - Device 1 state (on/off)
- `home/device2/state` - Device 2 state (on/off)

(Note: Threshold topics like `home/device1/threshold` might be published by the app but are not explicitly subscribed to by default in the provided `app.py` for *receiving* threshold changes *from* MQTT by this app version.)

## Log File

Application activity, including errors, is logged to `app_run.log` in the application directory. This file is overwritten each time the application starts.

## License

MIT
