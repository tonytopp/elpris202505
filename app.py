from flask import Flask, render_template, jsonify, request
from flask_mqtt import Mqtt
import requests
from datetime import datetime, timedelta
import os
import json
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'  # Change this to a secure secret key

# MQTT Configuration
app.config['MQTT_BROKER_URL'] = os.getenv('MQTT_BROKER_URL', 'localhost')
app.config['MQTT_BROKER_PORT'] = int(os.getenv('MQTT_BROKER_PORT', 1883))
app.config['MQTT_USERNAME'] = os.getenv('MQTT_USERNAME', '')
app.config['MQTT_PASSWORD'] = os.getenv('MQTT_PASSWORD', '')
app.config['MQTT_KEEPALIVE'] = 60
app.config['MQTT_TLS_ENABLED'] = os.getenv('MQTT_TLS_ENABLED', 'false').lower() == 'true'

mqtt = Mqtt()

def init_mqtt():
    try:
        mqtt.init_app(app)
        print(f"Connected to MQTT broker at {app.config['MQTT_BROKER_URL']}:{app.config['MQTT_BROKER_PORT']}")
        return True
    except Exception as e:
        print(f"Failed to connect to MQTT broker: {str(e)}")
        return False

# Initialize MQTT
init_mqtt()

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
    }
}

def get_electricity_prices():
    # Get current date in Sweden timezone
    import pytz
    from datetime import datetime, timedelta
    
    sweden_tz = pytz.timezone('Europe/Stockholm')
    now = datetime.now(sweden_tz)
    
    # Get prices for today and tomorrow
    prices = []
    
    for days_ahead in [0, 1]:  # Today and tomorrow
        target_date = now + timedelta(days=days_ahead)
        year = target_date.year
        month = target_date.month
        day = target_date.day
    
        # Try different URL formats
        date_formats = [
            f"{year}/{month:02d}-{day:02d}_SE3.json",  # Format: YYYY/MM-DD_SE3.json
            f"{year}-{month:02d}-{day:02d}_SE3.json", # Format: YYYY-MM-DD_SE3.json
            f"{year}/{month}-{day}_SE3.json",        # Format: YYYY/M-D_SE3.json
            f"{year}-{month}-{day}_SE3.json"          # Format: YYYY-M-D_SE3.json
        ]
        
        base_url = "https://www.elprisetjustnu.se/api/v1/prices/"
        
        for date_str in date_formats:
            url = base_url + date_str
            print(f"Trying URL: {url}")
            try:
                response = requests.get(url)
                print(f"Response status: {response.status_code}")
                if response.status_code == 200:
                    day_prices = response.json()
                    print(f"Successfully retrieved {len(day_prices)} price entries for {target_date.date()}")
                    # Format the response
                    for price in day_prices:
                        prices.append({
                            'time_start': price['time_start'],
                            'SEK_per_kWh': price['SEK_per_kWh'],
                            'date': target_date.date().isoformat()
                        })
                    break  # Successfully got prices for this day
                elif response.status_code == 404:
                    print(f"404 Not Found for URL: {url}")
                    continue
                response.raise_for_status()
            except Exception as e:
                print(f"Error with {url}: {str(e)}")
    
    if not prices:
        print("Failed to fetch prices after multiple attempts")
        # Return some sample data so the app doesn't crash
        prices = [
            {
                'time_start': (now + timedelta(hours=i)).isoformat(),
                'SEK_per_kWh': 1.5 + (i * 0.1),
                'date': now.date().isoformat()
            }
            for i in range(24)
        ]
    
    # Sort all prices by time
    prices.sort(key=lambda x: x['time_start'])
    return prices

@app.route('/')
def index():
    prices = get_electricity_prices()
    return render_template('index.html', prices=prices, devices=devices)

def get_weather_forecast(location_coords=VANERSBORG_COORDS):
    """Fetch weather forecast from SMHI API"""
    try:
        # Check if we have a recent cache
        if (weather_cache['data'] and 
            weather_cache['location'] == location_coords and
            weather_cache['timestamp'] and 
            (datetime.now() - weather_cache['timestamp']).total_seconds() < 3600):  # 1 hour cache
            return weather_cache['data']
            
        # Get forecast for the specified coordinates
        lon, lat = map(float, location_coords.split(','))
        url = f"{SMHI_BASE_URL}/category/pmp3g/version/2/geotype/point/lon/{lon}/lat/{lat}/data.json"
        
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        forecast = response.json()
        
        # Cache the result
        weather_cache.update({
            'timestamp': datetime.now(),
            'data': forecast,
            'location': location_coords
        })
        
        return forecast
    except Exception as e:
        print(f"Error fetching weather data: {str(e)}")
        return None

@app.route('/api/weather')
def api_weather():
    location = request.args.get('location', VANERSBORG_COORDS)
    forecast = get_weather_forecast(location)
    if forecast:
        return jsonify(forecast)
    return jsonify({"error": "Could not fetch weather data"}), 500

@app.route('/api/current-weather')
def api_current_weather():
    location = request.args.get('location', VANERSBORG_COORDS)
    forecast = get_weather_forecast(location)
    
    if not forecast or 'timeSeries' not in forecast:
        return jsonify({"error": "Could not fetch weather data"}), 500
    
    try:
        # Get the current time and find the closest forecast
        now = datetime.utcnow()
        closest_forecast = None
        min_diff = float('inf')
        
        for forecast_point in forecast['timeSeries']:
            forecast_time = datetime.strptime(forecast_point['validTime'], '%Y-%m-%dT%H:%M:%SZ')
            time_diff = abs((now - forecast_time).total_seconds())
            
            if time_diff < min_diff:
                min_diff = time_diff
                closest_forecast = forecast_point
        
        if closest_forecast:
            # Extract temperature (in Celsius)
            temp_param = next((p for p in closest_forecast['parameters'] if p['name'] == 't'), None)
            temp = temp_param['values'][0] if temp_param else None
            
            return jsonify({
                'temperature': temp,
                'time': closest_forecast['validTime'],
                'location': 'Vänersborg' if location == VANERSBORG_COORDS else 'Custom Location'
            })
            
    except Exception as e:
        print(f"Error processing weather data: {str(e)}")
    
    return jsonify({"error": "Could not process weather data"}), 500

@app.route('/api/prices')
def api_prices():
    prices = get_electricity_prices()
    return jsonify(prices)

@app.route('/api/mqtt/status')
def mqtt_status():
    """Check MQTT connection status"""
    return jsonify({
        'connected': mqtt.connected,
        'broker': f"{app.config['MQTT_BROKER_URL']}:{app.config['MQTT_BROKER_PORT']}",
        'username': app.config['MQTT_USERNAME'] if app.config['MQTT_USERNAME'] else None,
        'tls': app.config['MQTT_TLS_ENABLED']
    })

@app.route('/api/mqtt/update', methods=['POST'])
def update_mqtt_config():
    """Update MQTT configuration and reconnect"""
    try:
        data = request.get_json()
        
        # Update config
        app.config['MQTT_BROKER_URL'] = data.get('MQTT_BROKER_URL', app.config['MQTT_BROKER_URL'])
        app.config['MQTT_BROKER_PORT'] = int(data.get('MQTT_BROKER_PORT', app.config['MQTT_BROKER_PORT']))
        app.config['MQTT_USERNAME'] = data.get('MQTT_USERNAME', app.config['MQTT_USERNAME'])
        app.config['MQTT_PASSWORD'] = data.get('MQTT_PASSWORD', app.config['MQTT_PASSWORD'])
        app.config['MQTT_TLS_ENABLED'] = data.get('MQTT_TLS_ENABLED', 'false').lower() == 'true'
        
        # Save to .env file
        with open('.env', 'w') as f:
            f.write(f"MQTT_BROKER_URL={app.config['MQTT_BROKER_URL']}\n")
            f.write(f"MQTT_BROKER_PORT={app.config['MQTT_BROKER_PORT']}\n")
            f.write(f"MQTT_USERNAME={app.config['MQTT_USERNAME']}\n")
            f.write(f"MQTT_PASSWORD={app.config['MQTT_PASSWORD']}\n")
            f.write(f"MQTT_TLS_ENABLED={'true' if app.config['MQTT_TLS_ENABLED'] else 'false'}\n")
        
        # Reinitialize MQTT connection
        if mqtt.connected:
            mqtt.disconnect()
        init_mqtt()
        
        return jsonify({'status': 'success', 'message': 'MQTT configuration updated'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400

@app.route('/api/devices', methods=['GET', 'POST'])
def api_devices():
    if request.method == 'POST':
        data = request.get_json()
        device_id = data.get('id')
        
        if device_id not in devices and 'name' in data:
            # Create new device
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
        
        if device_id in devices:
            # Update existing device
            if 'threshold' in data:
                devices[device_id]['threshold'] = float(data['threshold'])
                mqtt.publish(f"{devices[device_id]['mqtt_topic']}/threshold", data['threshold'])
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
        
        return jsonify({'status': 'error', 'message': 'Invalid device ID'}), 400
    
    return jsonify(devices)

@app.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    if device_id in devices:
        deleted_device = devices.pop(device_id)
        return jsonify({'status': 'deleted', 'device': deleted_device})
    return jsonify({'status': 'error', 'message': 'Device not found'}), 404

@mqtt.on_connect()
def handle_connect(client, userdata, flags, rc):
    print("Connected to MQTT broker")
    # Subscribe to device state topics
    for device in devices.values():
        mqtt.subscribe(f"{device['mqtt_topic']}/state")

@mqtt.on_message()
def handle_mqtt_message(client, userdata, message):
    topic = message.topic
    payload = message.payload.decode()
    
    # Update device state in memory when MQTT message is received
    for device_id, device in devices.items():
        if topic == f"{device['mqtt_topic']}/state":
            device['state'] = payload
            break

if __name__ == '__main__':
    app.run(debug=True)
