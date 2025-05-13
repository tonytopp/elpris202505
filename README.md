# Electricity Price Controller

A web application that controls MQTT devices based on electricity prices from elprisetjustnu.se API, with temperature-based scheduling and SMHI weather integration.

## Features

- Real-time electricity price monitoring
- Temperature-based scheduling for devices
- SMHI weather integration for automatic temperature updates
- MQTT support for device control
- Responsive web interface
- Displays current and forecasted electricity prices in a chart
- Control MQTT devices with price thresholds
- Real-time updates

## Prerequisites

- Python 3.8+
- pip (Python package manager)
- MQTT broker (e.g., mosquitto, HiveMQ)

## Setup

1. Install Python 3.8 or higher
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Configure environment variables in a `.env` file (copy from `.env.example` if available)
4. Run the application:
   ```
   python app.py
   ```
5. Open `http://localhost:5000` in your browser

## Configuration

- MQTT broker settings can be configured in the web interface
- Temperature thresholds can be set in the Settings → Temperature Rules
- Location for weather data can be set in Settings → Location

## Dependencies

- Flask
- Flask-MQTT
- Requests
- python-dotenv
- Chart.js (included)
- Bootstrap 5 (included)

## License

MIT

## Prerequisites

- Python 3.7+
- pip (Python package manager)
- MQTT broker (e.g., mosquitto, HiveMQ)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd electricity-price-controller
   ```

2. Install the required Python packages:
   ```bash
   pip install -r requirements.txt
   ```

3. Create a `.env` file in the project root with your MQTT broker details:
   ```
   MQTT_BROKER_URL=your_broker_url
   MQTT_BROKER_PORT=1883
   MQTT_USERNAME=your_username
   MQTT_PASSWORD=your_password
   ```

## Usage

1. Start the Flask application:
   ```bash
   python app.py
   ```

2. Open your web browser and navigate to `http://localhost:5000`

3. Adjust the price thresholds for your devices using the sliders

## MQTT Topics

The application uses the following MQTT topics:

- `home/device1/threshold` - Set threshold for device 1
- `home/device2/threshold` - Set threshold for device 2
- `home/device1/state` - Device 1 state (on/off)
- `home/device2/state` - Device 2 state (on/off)

## License

This project is open source and available under the MIT License.
