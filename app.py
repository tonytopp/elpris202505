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
import threading

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

# Temperature and energy data storage
class DataStorage:
    def __init__(self, filename='temperature_data.json', max_days=30):
        self.filename = filename
        self.max_days = max_days
        self.data = self.load_data()
    
    def load_data(self):
        try:
            if os.path.exists(self.filename):
                with open(self.filename, 'r') as f:
                    return json.load(f)
            return {'hourly_records': []}
        except Exception as e:
            print(f"Error loading data: {str(e)}")
            return {'hourly_records': []}
    
    def save_data(self):
        try:
            with open(self.filename, 'w') as f:
                json.dump(self.data, f, indent=2)
            print(f"Data saved to {self.filename}")
            return True
        except Exception as e:
            print(f"Error saving data: {str(e)}")
            return False
    
    def add_hourly_record(self, indoor_temp, outdoor_temp, roller_position, electricity_price, solar_production=0):
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:00:00")  # Round to the hour
        
        # Check if we already have a record for this hour
        for record in self.data['hourly_records']:
            if record['timestamp'] == timestamp:
                # Update existing record
                record.update({
                    'indoor_temp': indoor_temp,
                    'outdoor_temp': outdoor_temp,
                    'roller_position': roller_position,
                    'electricity_price': electricity_price,
                    'solar_production': solar_production
                })
                self.save_data()
                return
        
        # Add new record
        self.data['hourly_records'].append({
            'timestamp': timestamp,
            'indoor_temp': indoor_temp,
            'outdoor_temp': outdoor_temp,
            'roller_position': roller_position,
            'electricity_price': electricity_price,
            'solar_production': solar_production
        })
        
        # Remove old records (keep only max_days)
        if len(self.data['hourly_records']) > self.max_days * 24:
            self.data['hourly_records'] = self.data['hourly_records'][-(self.max_days * 24):]
        
        self.save_data()
    
    def get_records(self, days=1):
        now = datetime.now()
        start_date = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        
        # Filter records by date
        filtered_records = [record for record in self.data['hourly_records'] 
                          if record['timestamp'] >= start_date]
        
        return filtered_records

# Initialize data storage
data_storage = DataStorage()

# Function to fetch indoor sensor data
def fetch_indoor_sensor_data():
    """Fetch data from the indoor temperature sensor"""
    try:
        print("Attempting to fetch indoor sensor data...")
        sensor_ip = devices['indoor-sensor']['ip']
        print(f"Connecting to sensor at {sensor_ip}...")
        
        # Store previous values to retain them if no new data
        prev_temp = devices['indoor-sensor']['temperature']
        prev_humidity = devices['indoor-sensor']['humidity']
        prev_battery = devices['indoor-sensor']['battery']
        
        try:
            response = requests.get(f'http://{sensor_ip}/status', timeout=5)
            print(f"Sensor response status code: {response.status_code}")
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    print(f"Received data from sensor: {data}")
                    
                    # Extract temperature, humidity, and battery data
                    if 'tmp' in data and data['tmp'].get('is_valid', False):
                        devices['indoor-sensor']['temperature'] = data['tmp']['value']
                        print(f"Temperature extracted: {data['tmp']['value']}°C")
                    else:
                        print("Temperature data not found or not valid in sensor response")
                        # Retain previous temperature value
                        if prev_temp is not None:
                            devices['indoor-sensor']['temperature'] = prev_temp
                            print(f"Retained previous temperature value: {prev_temp}°C")
                    
                    if 'hum' in data and data['hum'].get('is_valid', False):
                        devices['indoor-sensor']['humidity'] = data['hum']['value']
                        print(f"Humidity extracted: {data['hum']['value']}%")
                    else:
                        print("Humidity data not found or not valid in sensor response")
                        # Retain previous humidity value
                        if prev_humidity is not None:
                            devices['indoor-sensor']['humidity'] = prev_humidity
                            print(f"Retained previous humidity value: {prev_humidity}%")
                    
                    if 'bat' in data:
                        devices['indoor-sensor']['battery'] = data['bat']['value']
                        print(f"Battery level extracted: {data['bat']['value']}%")
                    else:
                        print("Battery data not found in sensor response")
                        # Retain previous battery value
                        if prev_battery is not None:
                            devices['indoor-sensor']['battery'] = prev_battery
                            print(f"Retained previous battery value: {prev_battery}%")
                    
                    devices['indoor-sensor']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    
                    # Use this temperature as the primary indoor temperature
                    # This will override any temperature from the Shelly device
                    if devices['indoor-sensor']['temperature'] is not None:
                        # Update the heat pump device with this temperature
                        devices['shelly-roller']['indoor_temp'] = devices['indoor-sensor']['temperature']
                        print(f"Heat pump indoor_temp updated to: {devices['indoor-sensor']['temperature']}°C")
                    else:
                        print("No temperature data available to update heat pump")
                    
                    return True
                except ValueError as e:
                    print(f"Error parsing JSON from sensor: {str(e)}")
                    print(f"Response content: {response.text[:100]}...")
                    # Retain previous values on error
                    if prev_temp is not None:
                        devices['indoor-sensor']['temperature'] = prev_temp
                    if prev_humidity is not None:
                        devices['indoor-sensor']['humidity'] = prev_humidity
                    if prev_battery is not None:
                        devices['indoor-sensor']['battery'] = prev_battery
                    return False
            else:
                print(f"Failed to get data from sensor, status code: {response.status_code}")
                # Retain previous values on error
                if prev_temp is not None:
                    devices['indoor-sensor']['temperature'] = prev_temp
                if prev_humidity is not None:
                    devices['indoor-sensor']['humidity'] = prev_humidity
                if prev_battery is not None:
                    devices['indoor-sensor']['battery'] = prev_battery
                return False
        except Exception as e:
            print(f"Error connecting to sensor: {str(e)}")
            # Retain previous values on connection error
            if prev_temp is not None:
                devices['indoor-sensor']['temperature'] = prev_temp
            if prev_humidity is not None:
                devices['indoor-sensor']['humidity'] = prev_humidity
            if prev_battery is not None:
                devices['indoor-sensor']['battery'] = prev_battery
            return False
    except Exception as e:
        print(f"Error fetching indoor sensor data: {str(e)}")
        return False

# Function to fetch energy meter data
def fetch_energy_meter_data():
    """Fetch data from the 3EM energy meter"""
    try:
        print("Attempting to fetch energy meter data...")
        meter_ip = devices['energy-meter']['ip']
        print(f"Connecting to energy meter at {meter_ip}...")
        
        # The 3EM meter uses the Shelly RPC API
        url = f"http://{meter_ip}/rpc/Shelly.GetStatus"
        print(f"Trying endpoint: {url}")
        
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            try:
                data = response.json()
                print(f"Received data from energy meter: {data}")
                
                # Store the raw data for debugging
                devices['energy-meter']['raw_data'] = data
                
                # Update last_updated timestamp
                devices['energy-meter']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                # Extract data from the 3EM meter format
                # The 3EM meter has data in 'em:0' and 'emdata:0' sections
                if 'em:0' in data:
                    em_data = data['em:0']
                    
                    # Total power consumption across all phases
                    if 'total_act_power' in em_data:
                        # Keep in watts for display
                        consumption = em_data['total_act_power']
                        devices['energy-meter']['consumption'] = consumption
                    
                    # Individual phase data
                    if 'a_act_power' in em_data:
                        devices['energy-meter']['phase_a_power'] = round(em_data['a_act_power'], 1)
                    if 'b_act_power' in em_data:
                        devices['energy-meter']['phase_b_power'] = round(em_data['b_act_power'], 1)
                    if 'c_act_power' in em_data:
                        devices['energy-meter']['phase_c_power'] = round(em_data['c_act_power'], 1)
                    
                    # Voltage information
                    if 'a_voltage' in em_data:
                        devices['energy-meter']['voltage'] = round(em_data['a_voltage'], 1)
                    
                    # Current information
                    if 'total_current' in em_data:
                        devices['energy-meter']['current'] = round(em_data['total_current'], 2)
                
                # Calculate production based on negative power values
                # In 3EM meters, negative total power values indicate energy being sent back to the grid
                total_power = em_data.get('total_act_power', 0)
                if total_power < 0:
                    # We have production (negative values mean sending back to grid)
                    devices['energy-meter']['production'] = total_power
                    # Update solar production in app config
                    app.config['SOLAR_PRODUCTION'] = total_power
                else:
                    # No production or not sending back to grid
                    devices['energy-meter']['production'] = 0
                    
                # Store the total power value for display
                devices['energy-meter']['total_power'] = total_power
                
                # Detect heat pump state based on power consumption changes
                # Add current reading to the list of recent readings
                devices['energy-meter']['power_readings'].append(total_power)
                
                # Keep only the last 3 readings
                if len(devices['energy-meter']['power_readings']) > 3:
                    devices['energy-meter']['power_readings'] = devices['energy-meter']['power_readings'][-3:]
                
                # Need at least 2 readings to detect changes
                if len(devices['energy-meter']['power_readings']) >= 2:
                    # Get the two most recent readings
                    current_power = devices['energy-meter']['power_readings'][-1]
                    prev_power = devices['energy-meter']['power_readings'][-2]
                    
                    # Calculate the change in power consumption
                    power_change = current_power - prev_power
                    threshold = devices['energy-meter']['detection_threshold']
                    print(f"Power change: {power_change}W (from {prev_power}W to {current_power}W)")
                    
                    # If power increases by threshold or more, heat pump is likely ON
                    if power_change >= threshold:
                        print(f"Detected heat pump turning ON based on power increase of {power_change}W")
                        devices['shelly-roller']['state'] = 'on'
                        devices['shelly-roller']['auto_detected'] = True
                    
                    # If power decreases by threshold or more, heat pump is likely OFF
                    elif power_change <= -threshold:
                        print(f"Detected heat pump turning OFF based on power decrease of {power_change}W")
                        devices['shelly-roller']['state'] = 'off'
                        devices['shelly-roller']['auto_detected'] = True
                    
                # Energy totals from emdata:0 section
                if 'emdata:0' in data:
                    emdata = data['emdata:0']
                    if 'total_act' in emdata:
                        devices['energy-meter']['total_consumption_kwh'] = round(emdata['total_act'], 1)
                    if 'total_act_ret' in emdata:
                        devices['energy-meter']['total_return_kwh'] = round(emdata['total_act_ret'], 1)
                
                print(f"Energy meter data updated successfully")
                return True
            except ValueError as e:
                print(f"Error parsing JSON from energy meter: {str(e)}")
                print(f"Response content: {response.text[:100]}...")
                return False
            except KeyError as e:
                print(f"Missing expected key in energy meter data: {str(e)}")
                return False
        
        print(f"Failed to get data from energy meter, status code: {response.status_code}")
        return False
    except Exception as e:
        print(f"Error fetching energy meter data: {str(e)}")
        return False

# Schedule to fetch sensor data every 5 minutes
def schedule_sensor_data_fetch():
    fetch_indoor_sensor_data()
    fetch_energy_meter_data()
    
    # Record data for history
    record_current_data()
    
    # Schedule the next fetch in 5 minutes
    threading.Timer(300, schedule_sensor_data_fetch).start()
    
# Function to record current data for history
def record_current_data():
    """Record current data to the history file"""
    try:
        # Get current values
        indoor_temp = None
        if devices['indoor-sensor']['temperature'] is not None:
            indoor_temp = devices['indoor-sensor']['temperature']
        elif devices['shelly-roller']['indoor_temp'] is not None:
            indoor_temp = devices['shelly-roller']['indoor_temp']
            
        outdoor_temp = app.config.get('OUTDOOR_TEMP')
        roller_position = 'open' if devices['shelly-roller']['state'] == 'on' else 'closed'
        electricity_price = app.config.get('CURRENT_PRICE', 0)
        
        # Get solar production from energy meter if available
        solar_production = 0
        if devices['energy-meter'].get('total_power') is not None:
            if devices['energy-meter']['total_power'] < 0:
                # Negative power means we're producing
                solar_production = abs(devices['energy-meter']['total_power'])
        else:
            # Use manually set solar production if meter not available
            solar_production = app.config.get('SOLAR_PRODUCTION', 0)
        
        # Record data
        if indoor_temp is not None and outdoor_temp is not None:
            data_storage.add_hourly_record(
                indoor_temp=indoor_temp,
                outdoor_temp=outdoor_temp,
                roller_position=roller_position,
                electricity_price=electricity_price,
                solar_production=solar_production
            )
            print(f"Recorded data: Indoor: {indoor_temp}°C, Outdoor: {outdoor_temp}°C, Price: {electricity_price}, Solar: {solar_production}W")
        else:
            print("Skipped recording data due to missing temperature values")
    except Exception as e:
        print(f"Error recording data: {str(e)}")


# Start the scheduler
schedule_sensor_data_fetch()

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
    'shelly-roller': {
        'id': 'shelly-roller',
        'name': 'Shelly Plus 2PM Roller',
        'type': 'roller',
        'state': 'off',  # Default to 'off' instead of 'unknown' for better UX
        'indoor_temp': None,
        'mqtt_topic': 'shellyplus2pm-08b61fcf9aa0',
        'ip_address': '192.168.1.114',
        'device_id': 'shellyplus2pm-08b61fcf9aa0',
        'enabled': True,
        'auto_detected': False  # Flag to indicate if state was auto-detected
    },
    'indoor-sensor': {
        'id': 'indoor-sensor',
        'name': 'Indoor Temperature Sensor',
        'type': 'sensor',
        'ip': '192.168.1.239',
        'temperature': None,
        'humidity': None,
        'battery': None,
        'last_updated': None
    },
    'energy-meter': {
        'id': 'energy-meter',
        'name': '3EM Energy Meter',
        'type': 'meter',
        'ip': '192.168.1.194',
        'consumption': None,
        'production': None,
        'voltage': None,
        'current': None,
        'last_updated': None,
        'power_readings': [],  # Store recent power readings for more reliable detection
        'detection_threshold': 2000  # 2kW threshold for heat pump detection
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

def fetch_indoor_sensor_data():
    """Fetch data from the indoor temperature sensor"""
    try:
        sensor_ip = devices['indoor-sensor']['ip']
        response = requests.get(f'http://{sensor_ip}/status', timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            
            # Extract temperature, humidity, and battery data
            if 'tmp' in data and data['tmp']['is_valid']:
                devices['indoor-sensor']['temperature'] = data['tmp']['value']
            
            if 'hum' in data and data['hum']['is_valid']:
                devices['indoor-sensor']['humidity'] = data['hum']['value']
            
            if 'bat' in data:
                devices['indoor-sensor']['battery'] = data['bat']['value']
            
            devices['indoor-sensor']['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Use this temperature as the primary indoor temperature
            # This will override any temperature from the Shelly device
            if devices['indoor-sensor']['temperature'] is not None:
                # Update the heat pump device with this temperature
                devices['shelly-roller']['indoor_temp'] = devices['indoor-sensor']['temperature']
            
            return True
        return False
    except Exception as e:
        print(f"Error fetching indoor sensor data: {str(e)}")
        return False

def update_device_state(device_id, state):
    """Update device state"""
    if device_id in devices:
        devices[device_id]['state'] = state
        return True
    return False

@app.route('/api/devices/<device_id>/state', methods=['POST'])
def update_device_state_api(device_id):
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
        pass

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

# Enhanced MQTT message handling with temperature data collection
@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    try:
        topic = message.topic
        payload = message.payload.decode()
        
        print(f"MQTT: Received raw message on topic '{topic}': '{payload}'") # Log all messages
        processed = False
        
        # Handle Shelly temperature readings
        if "shellyplus2pm" in topic and "/status" in topic:
            try:
                data = json.loads(payload)
                
                # Check if this is a temperature reading
                if 'temperature' in topic or 'temperature:0' in topic:
                    indoor_temp = None
                    # Different Shelly models report temperature differently
                    if 'tC' in data:
                        indoor_temp = data['tC']  # Temperature in Celsius
                    elif 'value' in data:
                        indoor_temp = data['value']  # Some models use this format
                    
                    if indoor_temp is not None:
                        # Store the temperature reading
                        devices['shelly-roller']['indoor_temp'] = indoor_temp
                        print(f"Indoor temperature updated: {indoor_temp}°C")
                        
                        # Get current outdoor temperature from weather API
                        outdoor_temp = None
                        try:
                            weather_data = get_current_weather()
                            if weather_data and 'temperature' in weather_data:
                                outdoor_temp = weather_data['temperature']
                        except Exception as we:
                            print(f"Error getting outdoor temperature: {str(we)}")
                        
                        # Get current roller position
                        roller_position = devices['shelly-roller'].get('state', 'unknown')
                        
                        # Get current electricity price
                        current_hour = datetime.now().hour
                        electricity_price = None
                        prices = get_electricity_prices()
                        for price in prices:
                            price_time = datetime.fromisoformat(price['time_start'].replace('Z', '+00:00'))
                            if price_time.hour == current_hour and price_time.date() == datetime.now().date():
                                electricity_price = price['SEK_per_kWh']
                                break
                        
                        # Store hourly record
                        if current_hour != devices['shelly-roller'].get('last_recorded_hour', None):
                            data_storage.add_hourly_record(
                                indoor_temp=indoor_temp,
                                outdoor_temp=outdoor_temp,
                                roller_position=roller_position,
                                electricity_price=electricity_price
                            )
                            devices['shelly-roller']['last_recorded_hour'] = current_hour
                            print(f"Recorded hourly data at {current_hour}:00")
                        
                        processed = True
            except json.JSONDecodeError:
                print(f"MQTT: Error decoding JSON from topic {topic}")
        
        # Handle regular device state updates
        if not processed:
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

# Helper function to get current weather
def get_current_weather():
    forecast = get_weather_forecast()
    if not forecast or 'timeSeries' not in forecast:
        return None
    
    try:
        now_utc = datetime.utcnow()
        closest_forecast = None
        min_diff = float('inf')
        
        for forecast_point in forecast['timeSeries']:
            forecast_time = datetime.strptime(forecast_point['validTime'], '%Y-%m-%dT%H:%M:%SZ')
            time_diff = abs((now_utc - forecast_time).total_seconds())
            if time_diff < min_diff:
                min_diff = time_diff
                closest_forecast = forecast_point
        
        if closest_forecast:
            temp_param = next((p for p in closest_forecast['parameters'] if p['name'] == 't'), None)
            temp = temp_param['values'][0] if temp_param else None
            return {
                'temperature': temp,
                'time': closest_forecast['validTime']
            }
    except Exception as e:
        print(f"Error processing weather data: {str(e)}")
    
    return None

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

@app.route('/api/temperature/data', methods=['GET'])
def get_temperature_data():
    days = request.args.get('days', default=1, type=int)
    records = data_storage.get_records(days=days)
    
    # Calculate energy savings if we have enough data
    if len(records) > 0:
        for record in records:
            # Simple energy savings calculation based on temperature difference
            # and whether the heat pump was in the optimal state
            if 'indoor_temp' in record and 'outdoor_temp' in record and 'roller_position' in record:
                indoor_temp = record.get('indoor_temp')
                outdoor_temp = record.get('outdoor_temp')
                heatpump_state = record.get('roller_position')  # Using roller_position field for heat pump state
                electricity_price = record.get('electricity_price', 0)
                
                if indoor_temp is not None and outdoor_temp is not None:
                    # Calculate temperature difference
                    temp_diff = indoor_temp - outdoor_temp
                    
                    # Get solar production data (negative value means excess production/selling to grid)
                    grid_consumption = record.get('solar_production', 0)
                    
                    # Determine optimal heat pump state based on temperatures, electricity price, and solar production
                    optimal_state = None
                    target_temp = 22  # Default target temperature
                    
                    # If we have excess solar production (negative grid consumption), use it!
                    if grid_consumption < 0:  # We're producing more than consuming (selling to grid)
                        optimal_state = 'on'  # Always turn on heat pump to use excess solar
                        
                        # If we have significant excess production, increase target temp to store more heat
                        if grid_consumption < -1.0:  # More than 1kW excess
                            target_temp = 24  # Store more heat
                        elif grid_consumption < -2.0:  # More than 2kW excess
                            target_temp = 25  # Store even more heat
                    
                    # If we're buying electricity (positive grid consumption), be more conservative
                    else:
                        # If it's cold inside (below 21°C), heat pump should be ON
                        # unless electricity is very expensive
                        if indoor_temp < 21:
                            if electricity_price and electricity_price > 3.0:  # Very expensive electricity
                                optimal_state = 'off'  # Turn off to save money
                            else:
                                optimal_state = 'on'   # Turn on to heat
                        # If it's comfortable inside (21-23°C)
                        elif 21 <= indoor_temp <= 23:
                            if electricity_price and electricity_price > 2.0:  # Expensive electricity
                                optimal_state = 'off'  # Turn off to save money
                            else:
                                optimal_state = 'on'   # Keep on for comfort
                        # If it's warm inside (above target_temp)
                        elif indoor_temp > target_temp:
                            optimal_state = 'off'      # No need for heating
                    
                    # Calculate energy savings
                    energy_saved = 0
                    solar_benefit = 0
                    
                    # Record the target temperature for reference
                    record['target_temp'] = target_temp
                    
                    if optimal_state and heatpump_state == optimal_state:
                        if grid_consumption < 0:  # We're using excess solar production
                            # Calculate benefit of using our own solar instead of selling to grid
                            # Typically, selling price is lower than buying price (about 70% of buying price)
                            solar_benefit = abs(grid_consumption) * electricity_price * 0.3  # The price difference
                            energy_saved = solar_benefit
                            
                            # Add thermal storage benefit
                            if indoor_temp > 22:  # We're storing heat above comfort temperature
                                # Each degree above 22 represents stored thermal energy
                                thermal_storage = (indoor_temp - 22) * 0.5  # kWh per degree of thermal mass
                                energy_saved += thermal_storage
                                
                        elif optimal_state == 'off' and electricity_price:
                            # If heat pump is correctly OFF when it should be, savings are based on electricity price
                            # Assuming heat pump uses about 1.5 kWh per hour when running
                            energy_saved = 1.5 * electricity_price
                        elif optimal_state == 'on' and temp_diff < 0:
                            # If heat pump is correctly ON when it's cold, savings are based on efficiency
                            # Heat pumps are more efficient than direct electric heating (about 3x)
                            # Assuming direct electric heating would use 3 kWh for the same heating
                            energy_saved = 2.0  # kWh saved compared to direct electric heating
                    
                    # Add solar production info to the record
                    record['grid_consumption'] = grid_consumption
                    record['solar_benefit'] = round(solar_benefit, 2)
                    
                    # Add energy savings to the record
                    record['energy_saved'] = round(energy_saved, 2)
                    record['optimal_state'] = optimal_state
    
    return jsonify({
        'records': records,
        'total_records': len(records),
        'days_requested': days
    })

@app.route('/api/solar/update', methods=['POST'])
def update_solar_production():
    """Update the current solar production data"""
    try:
        data = request.get_json()
        if 'production' not in data:
            return jsonify({'error': 'Missing production value'}), 400
            
        production = float(data['production'])
        
        # Store the latest solar production value
        app.config['SOLAR_PRODUCTION'] = production
        
        # Update the latest hourly record with this solar production value
        records = data_storage.get_records(days=1)
        if records:
            latest_record = records[0]
            indoor_temp = latest_record.get('indoor_temp')
            outdoor_temp = latest_record.get('outdoor_temp')
            roller_position = latest_record.get('roller_position')
            electricity_price = latest_record.get('electricity_price')
            
            # Update the record with new solar production
            data_storage.add_hourly_record(
                indoor_temp, 
                outdoor_temp, 
                roller_position, 
                electricity_price, 
                production
            )
        
        return jsonify({
            'success': True,
            'message': f'Solar production updated to {production} kW',
            'production': production
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/temperature-dashboard')
def temperature_dashboard():
    # Get the latest 24 hours of data
    records = data_storage.get_records(days=1)
    
    # Calculate total energy saved
    total_energy_saved = sum(record.get('energy_saved', 0) for record in records)
    total_solar_benefit = sum(record.get('solar_benefit', 0) for record in records)
    
    # Fetch the latest data from sensors and meters
    fetch_indoor_sensor_data()
    fetch_energy_meter_data()
    
    # Get the latest indoor and outdoor temperatures
    # First try to get from indoor sensor, then from Shelly device, default to N/A
    if devices['indoor-sensor'].get('temperature') is not None:
        latest_indoor_temp = devices['indoor-sensor']['temperature']
        print(f"Using indoor sensor temperature: {latest_indoor_temp}°C")
    elif devices['shelly-roller'].get('indoor_temp') is not None:
        latest_indoor_temp = devices['shelly-roller']['indoor_temp']
        print(f"Using Shelly device temperature: {latest_indoor_temp}°C")
    else:
        latest_indoor_temp = 'N/A'
        print("No temperature data available from any sensor")
    latest_outdoor_temp = None
    try:
        weather_data = get_current_weather()
        if weather_data and 'temperature' in weather_data:
            latest_outdoor_temp = weather_data['temperature']
    except Exception:
        pass
    
    # Get current solar production
    current_solar = app.config.get('SOLAR_PRODUCTION', 0)
    
    return render_template(
        'temperature_dashboard.html',
        records=records,
        total_energy_saved=round(total_energy_saved, 2),
        total_solar_benefit=round(total_solar_benefit, 2),
        latest_indoor_temp=latest_indoor_temp,
        latest_outdoor_temp=latest_outdoor_temp,
        roller_state=devices['shelly-roller'].get('state', 'unknown'),
        current_solar=current_solar,
        devices=devices  # Pass the entire devices dictionary to access all sensor data
    )

@app.route('/history')
def history_view():
    # Get days parameter from query string, default to 7
    days = request.args.get('days', default=7, type=int)
    
    # Get the historical records
    records = data_storage.get_records(days=days)
    
    # Record current data to ensure we have the latest
    record_current_data()
    
    # Get the filename where data is stored
    data_filename = os.path.abspath(data_storage.filename)
    
    return render_template(
        'history.html',
        records=records,
        days=days,
        data_filename=data_filename
    )

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
