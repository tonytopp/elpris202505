import logging
import sys # Import sys for more comprehensive logging if needed later

# Configure basic logging to a file
logging.basicConfig(
    filename='app_run.log', # Log to this file in the same directory as app.py
    filemode='w',        # Overwrite the log file on each run
    level=logging.DEBUG, # Capture all levels of messages (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Create a logger instance
logger = logging.getLogger(__name__)

# Redirect stdout and stderr to the logger
class StreamToLogger(object):
    """
    Fake file-like stream object that redirects writes to a logger instance.
    """
    def __init__(self, logger_instance, log_level=logging.INFO):
        self.logger = logger_instance
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass # sys.stdout has a flush method, so we need one too.

sys.stdout = StreamToLogger(logger, logging.INFO)
sys.stderr = StreamToLogger(logger, logging.ERROR)

print("--- Application stdout/stderr redirected to app_run.log ---")

from flask import Flask, render_template, jsonify, request
from flask_mqtt import Mqtt
import requests
from datetime import datetime, timedelta
import os
import json
from dotenv import load_dotenv
import pytz

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a-default-fallback-secret-key-if-not-set')

# MQTT Configuration
app.config['MQTT_BROKER_URL'] = os.getenv('MQTT_BROKER_URL', '192.168.1.199')
app.config['MQTT_BROKER_PORT'] = int(os.getenv('MQTT_BROKER_PORT', 1883))
app.config['MQTT_USERNAME'] = os.getenv('MQTT_USERNAME', 'tony')
app.config['MQTT_PASSWORD'] = os.getenv('MQTT_PASSWORD', '4672')
app.config['MQTT_KEEPALIVE'] = 60
app.config['MQTT_TLS_ENABLED'] = os.getenv('MQTT_TLS_ENABLED', 'false').lower() == 'true'

mqtt = Mqtt()

def init_mqtt(app_context=None):
    if app_context:
        with app_context:
            try:
                mqtt.init_app(app)
                print(f"MQTT: Attempting to connect to broker at {app.config['MQTT_BROKER_URL']}:{app.config['MQTT_BROKER_PORT']}")
                return True
            except Exception as e:
                print(f"MQTT: Failed to initialize or connect to broker: {str(e)}")
                return False
    else: # Fallback if no app_context provided
        try:
            mqtt.init_app(app)
            print(f"MQTT: Attempting to connect to broker at {app.config['MQTT_BROKER_URL']}:{app.config['MQTT_BROKER_PORT']}")
            return True
        except Exception as e:
            print(f"MQTT: Failed to initialize or connect to broker: {str(e)}")
            return False

# Initialize MQTT with app context
with app.app_context():
    if not init_mqtt(app.app_context()):
        print("MQTT: Initial connection failed. Will rely on Flask-MQTT auto-reconnect.")

# SMHI API Configuration
SMHI_BASE_URL = "https://opendata-download-metfcst.smhi.se/api"
VANERSBORG_COORDS = "12.3167,58.3833"  # Vänersborg coordinates

# Cache for weather data
weather_cache = {
    'timestamp': None,
    'data': None,
    'location': None
}

# Store device states and configurations
devices = {
    'device1': {
        'name': 'Device 1',
        'state': 'off',
        'threshold': 100,
        'mqtt_topic': 'home/device1',
        'enabled': True,
        'type': 'switch',
        'description': 'First test device'
    },
    'device2': {
        'name': 'Device 2',
        'state': 'off',
        'threshold': 80,
        'mqtt_topic': 'home/device2',
        'enabled': True,
        'type': 'switch',
        'description': 'Second test device'
    },
    'shelly-roller': {
        'name': 'Roller Shutter',
        'state': 'off',
        'threshold': 100,
        'mqtt_topic': 'shellyplus2pm-08b61fcf9aa0',
        'ip_address': '192.168.1.114',
        'device_id': 'shellyplus2pm-08b61fcf9aa0',
        'enabled': True,
        'type': 'shelly',
        'description': 'Shelly Plus 2PM Roller Shutter'
    }
}

def get_electricity_prices():
    sweden_tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(sweden_tz)
    prices = []
    for days_ahead in [0, 1]:
        target_date = now + timedelta(days=days_ahead)
        year = target_date.year
        month = target_date.month
        day = target_date.day
        date_formats = [
            f"{year}/{month:02d}-{day:02d}_SE3.json",
            f"{year}-{month:02d}-{day:02d}_SE3.json",
            f"{year}/{month}-{day}_SE3.json",
            f"{year}-{month}-{day}_SE3.json"
        ]
        base_url = "https://www.elprisetjustnu.se/api/v1/prices/"
        for date_str in date_formats:
            url = base_url + date_str
            print(f"Trying URL: {url}")
            try:
                response = requests.get(url, timeout=10) # Added timeout
                print(f"Response status: {response.status_code}")
                if response.status_code == 200:
                    day_prices = response.json()
                    print(f"Successfully retrieved {len(day_prices)} price entries for {target_date.date()}")
                    for price_item in day_prices:
                        prices.append({
                            'time_start': price_item['time_start'],
                            'SEK_per_kWh': price_item['SEK_per_kWh'],
                            'date': target_date.date().isoformat()
                        })
                    break
                elif response.status_code == 404:
                    print(f"404 Not Found for URL: {url}")
                    continue
                response.raise_for_status()
            except Exception as e:
                print(f"Error with {url}: {str(e)}")
    if not prices:
        print("Failed to fetch prices after multiple attempts, returning empty list.")
        return []
    prices.sort(key=lambda x: x['time_start'])
    return prices

@app.route('/')
def index():
    current_prices = get_electricity_prices()
    return render_template('index.html', prices=current_prices, devices=devices)

def get_weather_forecast(): # Modified: always Vänersborg, no args
    """Fetch weather forecast from SMHI API for Vänersborg"""
    current_location_coords = VANERSBORG_COORDS
    try:
        if (weather_cache['data'] and
            weather_cache['location'] == current_location_coords and
            weather_cache['timestamp'] and
            (datetime.now() - weather_cache['timestamp']).total_seconds() < 3600): # 1 hour cache
            return weather_cache['data']
        lon, lat = map(float, current_location_coords.split(','))
        url = f"{SMHI_BASE_URL}/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        forecast = response.json()
        weather_cache.update({
            'timestamp': datetime.now(),
            'data': forecast,
            'location': current_location_coords
        })
        return forecast
    except Exception as e:
        print(f"Error fetching weather data: {str(e)}")
        return None

@app.route('/api/weather')
def api_weather(): # Modified: no location param
    forecast = get_weather_forecast()
    if forecast:
        return jsonify(forecast)
    return jsonify({"error": "Could not fetch weather data"}), 500

@app.route('/api/current-weather')
def api_current_weather(): # Modified: no location param
    forecast = get_weather_forecast()
    if not forecast or 'timeSeries' not in forecast:
        return jsonify({"error": "Could not fetch weather data"}), 500
    try:
        now_utc = datetime.utcnow() # Original now variable was fine
        closest_forecast = None
        min_diff = float('inf')
        for forecast_point in forecast['timeSeries']:
            forecast_time = datetime.strptime(forecast_point['validTime'], '%Y-%m-%dT%H:%M:%SZ')
            # Both now_utc (naive UTC) and forecast_time (naive from strptime) are naive.
            time_diff = abs((now_utc - forecast_time).total_seconds())
            if time_diff < min_diff:
                min_diff = time_diff
                closest_forecast = forecast_point
        if closest_forecast:
            temp_param = next((p for p in closest_forecast['parameters'] if p['name'] == 't'), None)
            temp = temp_param['values'][0] if temp_param else None
            return jsonify({
                'temperature': temp,
                'time': closest_forecast['validTime'],
                'location': 'Vänersborg' # Modified: always Vänersborg
            })
    except Exception as e:
        print(f"Error processing weather data: {str(e)}")
    return jsonify({"error": "Could not process weather data"}), 500

@app.route('/api/prices')
def api_prices():
    current_prices = get_electricity_prices()
    return jsonify(current_prices)

@app.route('/api/mqtt/status')
def mqtt_status():
    return jsonify({
        'connected': mqtt.connected,
        'broker': f"{app.config['MQTT_BROKER_URL']}:{app.config['MQTT_BROKER_PORT']}",
        'username': app.config['MQTT_USERNAME'] if app.config['MQTT_USERNAME'] else None,
        'tls': app.config['MQTT_TLS_ENABLED']
    })

@app.route('/api/mqtt/update', methods=['POST'])
def update_mqtt_config():
    try:
        data = request.get_json()
        app.config['MQTT_BROKER_URL'] = data.get('MQTT_BROKER_URL', app.config['MQTT_BROKER_URL'])
        app.config['MQTT_BROKER_PORT'] = int(data.get('MQTT_BROKER_PORT', app.config['MQTT_BROKER_PORT']))
        app.config['MQTT_USERNAME'] = data.get('MQTT_USERNAME', app.config['MQTT_USERNAME'])
        app.config['MQTT_PASSWORD'] = data.get('MQTT_PASSWORD', app.config['MQTT_PASSWORD'])
        app.config['MQTT_TLS_ENABLED'] = data.get('MQTT_TLS_ENABLED', 'false').lower() == 'true'
        
        with open('.env', 'w') as f:
            f.write(f"MQTT_BROKER_URL={app.config['MQTT_BROKER_URL']}\n")
            f.write(f"MQTT_BROKER_PORT={app.config['MQTT_BROKER_PORT']}\n")
            f.write(f"MQTT_USERNAME={app.config['MQTT_USERNAME']}\n")
            f.write(f"MQTT_PASSWORD={app.config['MQTT_PASSWORD']}\n")
            f.write(f"MQTT_TLS_ENABLED={'true' if app.config['MQTT_TLS_ENABLED'] else 'false'}\n")
            f.write(f"SECRET_KEY={app.config['SECRET_KEY']}\n") # Ensure SECRET_KEY is written
        
        if mqtt.connected:
            mqtt.disconnect()
        with app.app_context(): # Ensure context for re-initialization
            init_mqtt(app.app_context())
            
        return jsonify({'status': 'success', 'message': 'MQTT configuration updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['GET', 'POST'])
def api_devices():
    if request.method == 'POST':
        data = request.get_json()
        device_id = data.get('id')
        
        if device_id not in devices and 'name' in data: # Create new device
            devices[device_id] = {
                'name': data['name'],
                'state': 'off',
                'threshold': float(data.get('threshold', 100)),
                'mqtt_topic': data.get('mqtt_topic', f'home/device{len(devices) + 1}'),
                'enabled': data.get('enabled', True),
                'type': data.get('type', 'switch'),
                'description': data.get('description', 'New device')
            }
            return jsonify({'status': 'created', 'device': devices[device_id]})
        
        if device_id in devices: # Update existing device
            if 'threshold' in data:
                devices[device_id]['threshold'] = float(data['threshold'])
            if 'name' in data:
                devices[device_id]['name'] = data['name']
            if 'mqtt_topic' in data:
                devices[device_id]['mqtt_topic'] = data['mqtt_topic']
            if 'enabled' in data:
                devices[device_id]['enabled'] = bool(data['enabled'])
            if 'type' in data:
                devices[device_id]['type'] = data['type']
            if 'description' in data:
                devices[device_id]['description'] = data['description']
            return jsonify({'status': 'updated', 'device': devices[device_id]})
        
        return jsonify({'status': 'error', 'message': 'Invalid device ID or missing data for new device'}), 400
    
    return jsonify(devices)

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    if device_id in devices:
        deleted_device = devices.pop(device_id)
        return jsonify({'status': 'deleted', 'device': deleted_device})
    return jsonify({'status': 'error', 'message': 'Device not found'}), 404

@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    print(f"MQTT: Connected with result code {rc}")
    # Subscribe to device state topics
    if rc == 0: # Only subscribe if connection was successful
        for device_id in devices:
            try:
                topic = devices[device_id]['mqtt_topic'] + "/state"
                mqtt.subscribe(topic)
                print(f"MQTT: Subscribed to {topic}")
            except Exception as e:
                print(f"MQTT: Error subscribing to topic for device {device_id}: {str(e)}")
    else:
        print(f"MQTT: Connection failed, not subscribing to topics. Result code: {rc}")

# Using the original simpler version from the user's code for MQTT message handling
@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    try:
        topic = message.topic
        payload = message.payload.decode()
        
        print(f"MQTT: Received raw message on topic '{topic}': '{payload}'") # Log all messages
        processed = False
        for device_id, device_data in devices.items():
            if topic == f"{device_data['mqtt_topic']}/state":
                device_data['state'] = payload
                print(f"MQTT: Device {device_id} state updated to {payload}")
                processed = True
                break
        if not processed:
            print(f"MQTT: Message on topic '{topic}' did not match any device state topics.")

    except Exception as e:
        print(f"MQTT: CRITICAL ERROR processing message: {str(e)}")
        if message and hasattr(message, 'topic') and hasattr(message, 'payload'):
            try:
                print(f"MQTT: Failing message topic: {message.topic}, raw payload: {message.payload}")
            except Exception as e_log:
                print(f"MQTT: Error trying to log failing message details: {str(e_log)}")
        else:
            print("MQTT: Failing message object was None or lacked topic/payload attributes.")

@app.route('/api/devices/<device_id>/state', methods=['POST'])
def update_device_state(device_id):
    if device_id not in devices:
        return jsonify({'status': 'error', 'message': 'Device not found'}), 404
    
    data = request.get_json()
    new_state = data.get('state')
    
    if new_state not in ['on', 'off']:
        return jsonify({'status': 'error', 'message': 'Invalid state value'}), 400
    
    device = devices[device_id]
    device['state'] = new_state
    
    # Handle Shelly Plus 2PM device in roller shutter mode
    if device.get('type') == 'shelly' and device.get('device_id', '').startswith('shellyplus2pm'):
        device_base_id = device.get('mqtt_topic')
        ip_address = device.get('ip_address')
        
        # For roller shutters, 'on' means open and 'off' means close
        cover_action = "open" if new_state == "on" else "close"
        cover_id = 0  # Always use cover ID 0 for roller shutter
        
        # Try HTTP control first
        if ip_address:
            try:
                # For Shelly Plus 2PM (Gen2) in roller shutter mode
                rpc_url = f"http://{ip_address}/rpc"
                
                # Use Cover API for roller shutters
                rpc_payload = {
                    "id": 1,
                    "src": "elprisapp",
                    "method": f"Cover.{cover_action.capitalize()}",
                    "params": {"id": cover_id}
                }
                
                print(f"HTTP: Controlling Shelly device via RPC API: {rpc_url} with payload {rpc_payload}")
                response = requests.post(rpc_url, json=rpc_payload, timeout=5)
                response.raise_for_status()
                print(f"HTTP: Shelly device control response: {response.text}")
            except Exception as e:
                print(f"HTTP: Error controlling Shelly device via HTTP: {str(e)}")
                # Continue with MQTT as fallback
        
        # Also send MQTT command as backup
        # Format 1: Cover RPC format
        command_topic1 = f"{device_base_id}/rpc"
        command_method = f"Cover.{cover_action.capitalize()}"
        command_payload1 = json.dumps({
            "id": 1, 
            "src": "elprisapp",
            "method": command_method,
            "params": {"id": cover_id}
        })
        print(f"MQTT: Publishing to {command_topic1}: {command_payload1}")
        mqtt.publish(command_topic1, command_payload1)
        
        # Format 2: MQTT Control format for cover
        command_topic2 = f"{device_base_id}/command/cover:{cover_id}"
        command_payload2 = cover_action
        print(f"MQTT: Publishing to {command_topic2}: {command_payload2}")
        mqtt.publish(command_topic2, command_payload2)
    else:
        # Standard device - just publish the state to MQTT
        mqtt_topic = device.get('mqtt_topic')
        if mqtt_topic:
            mqtt.publish(f"{mqtt_topic}/command", new_state)
            print(f"MQTT: Published {new_state} to {mqtt_topic}/command")
    
    return jsonify({
        'status': 'success', 
        'device_id': device_id, 
        'state': new_state
    })

@app.route('/api/devices/roller/stop', methods=['POST'])
def stop_roller_shutter():
    device_id = 'shelly-roller'
    if device_id not in devices:
        return jsonify({'status': 'error', 'message': 'Roller shutter device not found'}), 404
    
    device = devices[device_id]
    device_base_id = device.get('mqtt_topic')
    ip_address = device.get('ip_address')
    cover_id = 0  # Always use cover ID 0 for roller shutter
    
    # Try HTTP control first
    if ip_address:
        try:
            # For Shelly Plus 2PM (Gen2) in roller shutter mode
            rpc_url = f"http://{ip_address}/rpc"
            
            # Use Cover.Stop API for roller shutters
            rpc_payload = {
                "id": 1,
                "src": "elprisapp",
                "method": "Cover.Stop",
                "params": {"id": cover_id}
            }
            
            print(f"HTTP: Stopping Shelly roller shutter via RPC API: {rpc_url} with payload {rpc_payload}")
            response = requests.post(rpc_url, json=rpc_payload, timeout=5)
            response.raise_for_status()
            print(f"HTTP: Shelly device stop response: {response.text}")
        except Exception as e:
            print(f"HTTP: Error stopping Shelly roller shutter via HTTP: {str(e)}")
            # Continue with MQTT as fallback
    
    # Also send MQTT command as backup
    # Format 1: Cover RPC format
    command_topic1 = f"{device_base_id}/rpc"
    command_payload1 = json.dumps({
        "id": 1, 
        "src": "elprisapp",
        "method": "Cover.Stop",
        "params": {"id": cover_id}
    })
    print(f"MQTT: Publishing to {command_topic1}: {command_payload1}")
    mqtt.publish(command_topic1, command_payload1)
    
    # Format 2: MQTT Control format for cover
    command_topic2 = f"{device_base_id}/command/cover:{cover_id}"
    command_payload2 = "stop"
    print(f"MQTT: Publishing to {command_topic2}: {command_payload2}")
    mqtt.publish(command_topic2, command_payload2)
    
    return jsonify({
        'status': 'success', 
        'message': 'Roller shutter stopped'
    })

if __name__ == '__main__':
    # Running with use_reloader=False to see if it improves stability
    # The reloader can sometimes cause issues or consume more resources in certain environments.
    app.run(debug=True, host='0.0.0.0', port=8080, use_reloader=False)
