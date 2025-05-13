#!/usr/bin/env python3
"""
3EM Energy Meter Dashboard
A web-based dashboard for monitoring and troubleshooting Shelly 3EM energy meters.
"""

import requests
import json
import time
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify, request

# Configuration
DEFAULT_3EM_IP = "192.168.1.194"
REFRESH_INTERVAL = 5  # seconds
MAX_HISTORY_POINTS = 100  # Maximum number of data points to store

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'shelly3em-dashboard'

# Global variables to store meter data
meter_data = {
    "ip_address": DEFAULT_3EM_IP,
    "last_updated": None,
    "status": None,
    "config": None,
    "history": {
        "timestamps": [],
        "phase_a": [],
        "phase_b": [],
        "phase_c": [],
        "total": []
    },
    "error": None
}

def get_device_status(ip_address):
    """Get full device status from the 3EM meter"""
    try:
        url = f"http://{ip_address}/rpc/Shelly.GetStatus"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error connecting to device: {str(e)}")
        return None

def get_device_config(ip_address):
    """Get device configuration"""
    try:
        url = f"http://{ip_address}/rpc/Shelly.GetConfig"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            return None
    except Exception as e:
        print(f"Error getting device config: {str(e)}")
        return None

def update_meter_data():
    """Update meter data in the background"""
    global meter_data
    
    while True:
        try:
            ip = meter_data["ip_address"]
            status = get_device_status(ip)
            
            if status:
                meter_data["status"] = status
                meter_data["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                meter_data["error"] = None
                
                # Extract power data
                if 'em:0' in status:
                    em_data = status['em:0']
                    
                    # Add to history
                    timestamp = datetime.now().strftime('%H:%M:%S')
                    meter_data["history"]["timestamps"].append(timestamp)
                    
                    # Phase A
                    phase_a_power = em_data.get('a_act_power', 0)
                    meter_data["history"]["phase_a"].append(phase_a_power)
                    
                    # Phase B
                    phase_b_power = em_data.get('b_act_power', 0)
                    meter_data["history"]["phase_b"].append(phase_b_power)
                    
                    # Phase C
                    phase_c_power = em_data.get('c_act_power', 0)
                    meter_data["history"]["phase_c"].append(phase_c_power)
                    
                    # Total
                    total_power = em_data.get('total_act_power', 0)
                    meter_data["history"]["total"].append(total_power)
                    
                    # Limit history size
                    if len(meter_data["history"]["timestamps"]) > MAX_HISTORY_POINTS:
                        meter_data["history"]["timestamps"] = meter_data["history"]["timestamps"][-MAX_HISTORY_POINTS:]
                        meter_data["history"]["phase_a"] = meter_data["history"]["phase_a"][-MAX_HISTORY_POINTS:]
                        meter_data["history"]["phase_b"] = meter_data["history"]["phase_b"][-MAX_HISTORY_POINTS:]
                        meter_data["history"]["phase_c"] = meter_data["history"]["phase_c"][-MAX_HISTORY_POINTS:]
                        meter_data["history"]["total"] = meter_data["history"]["total"][-MAX_HISTORY_POINTS:]
            else:
                meter_data["error"] = f"Failed to connect to 3EM meter at {ip}"
                
        except Exception as e:
            meter_data["error"] = f"Error updating meter data: {str(e)}"
            
        time.sleep(REFRESH_INTERVAL)

@app.route('/')
def index():
    """Render the dashboard"""
    return render_template('3em_dashboard.html')

@app.route('/api/meter-data')
def api_meter_data():
    """API endpoint to get current meter data"""
    return jsonify(meter_data)

@app.route('/api/update-ip', methods=['POST'])
def api_update_ip():
    """API endpoint to update the meter IP address"""
    global meter_data
    
    data = request.get_json()
    new_ip = data.get('ip')
    
    if new_ip:
        meter_data["ip_address"] = new_ip
        # Also update the config
        config = get_device_config(new_ip)
        if config:
            meter_data["config"] = config
        return jsonify({"success": True, "message": f"IP updated to {new_ip}"})
    else:
        return jsonify({"success": False, "message": "Invalid IP address"})

@app.route('/api/reset-history', methods=['POST'])
def api_reset_history():
    """API endpoint to reset the history data"""
    global meter_data
    
    meter_data["history"] = {
        "timestamps": [],
        "phase_a": [],
        "phase_b": [],
        "phase_c": [],
        "total": []
    }
    
    return jsonify({"success": True, "message": "History data reset"})

def create_templates():
    """Create the HTML template for the dashboard"""
    import os
    
    templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(templates_dir, exist_ok=True)
    
    dashboard_html = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>3EM Energy Meter Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            padding-top: 20px;
            background-color: #f5f5f5;
        }
        .card {
            margin-bottom: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        .card-header {
            font-weight: bold;
        }
        .power-value {
            font-size: 2.5rem;
            font-weight: bold;
        }
        .power-unit {
            font-size: 1.2rem;
        }
        .text-success {
            color: #28a745 !important;
        }
        .text-danger {
            color: #dc3545 !important;
        }
        .phase-indicator {
            width: 15px;
            height: 15px;
            display: inline-block;
            border-radius: 50%;
            margin-right: 5px;
        }
        .phase-a {
            background-color: #ff6384;
        }
        .phase-b {
            background-color: #36a2eb;
        }
        .phase-c {
            background-color: #4bc0c0;
        }
        .phase-total {
            background-color: #ffcd56;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .info-label {
            font-weight: bold;
        }
        #error-alert {
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="text-center mb-4">3EM Energy Meter Dashboard</h1>
        
        <div class="row mb-3">
            <div class="col-md-6">
                <div class="input-group">
                    <input type="text" id="ip-input" class="form-control" placeholder="3EM IP Address" value="192.168.1.194">
                    <button class="btn btn-primary" id="update-ip-btn">Update IP</button>
                </div>
            </div>
            <div class="col-md-6 text-end">
                <span class="me-3">Last updated: <span id="last-updated">Never</span></span>
                <button class="btn btn-secondary" id="reset-history-btn">Reset History</button>
            </div>
        </div>
        
        <div class="alert alert-danger" id="error-alert" role="alert">
            Error connecting to the 3EM meter.
        </div>
        
        <div class="row">
            <!-- Power Overview -->
            <div class="col-md-12">
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        Power Overview
                    </div>
                    <div class="card-body">
                        <div class="row">
                            <div class="col-md-3">
                                <div class="card">
                                    <div class="card-header bg-danger text-white">
                                        Phase A
                                    </div>
                                    <div class="card-body text-center">
                                        <div id="phase-a-power" class="power-value">--</div>
                                        <div class="power-unit">W</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card">
                                    <div class="card-header bg-primary text-white">
                                        Phase B
                                    </div>
                                    <div class="card-body text-center">
                                        <div id="phase-b-power" class="power-value">--</div>
                                        <div class="power-unit">W</div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card">
                                    <div class="card-header bg-success text-white">
                                        Phase C (Solar)
                                    </div>
                                    <div class="card-body text-center">
                                        <div id="phase-c-power" class="power-value">--</div>
                                        <div class="power-unit">W</div>
                                        <div id="phase-c-status" class="mt-2"></div>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-3">
                                <div class="card">
                                    <div class="card-header bg-warning text-dark">
                                        Total
                                    </div>
                                    <div class="card-body text-center">
                                        <div id="total-power" class="power-value">--</div>
                                        <div class="power-unit">W</div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Power Chart -->
            <div class="col-md-12">
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        Power History
                    </div>
                    <div class="card-body">
                        <canvas id="power-chart" height="300"></canvas>
                    </div>
                </div>
            </div>
            
            <!-- Detailed Information -->
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        Electrical Parameters
                    </div>
                    <div class="card-body">
                        <h5>Phase A</h5>
                        <div class="info-row">
                            <span class="info-label">Current:</span>
                            <span id="phase-a-current">-- A</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Voltage:</span>
                            <span id="phase-a-voltage">-- V</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Power Factor:</span>
                            <span id="phase-a-pf">--</span>
                        </div>
                        
                        <hr>
                        
                        <h5>Phase B</h5>
                        <div class="info-row">
                            <span class="info-label">Current:</span>
                            <span id="phase-b-current">-- A</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Voltage:</span>
                            <span id="phase-b-voltage">-- V</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Power Factor:</span>
                            <span id="phase-b-pf">--</span>
                        </div>
                        
                        <hr>
                        
                        <h5>Phase C</h5>
                        <div class="info-row">
                            <span class="info-label">Current:</span>
                            <span id="phase-c-current">-- A</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Voltage:</span>
                            <span id="phase-c-voltage">-- V</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Power Factor:</span>
                            <span id="phase-c-pf">--</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Energy Data -->
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header bg-primary text-white">
                        Energy Data
                    </div>
                    <div class="card-body">
                        <h5>Consumption (kWh)</h5>
                        <div class="info-row">
                            <span class="info-label">Phase A:</span>
                            <span id="phase-a-energy">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Phase B:</span>
                            <span id="phase-b-energy">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Phase C:</span>
                            <span id="phase-c-energy">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Total:</span>
                            <span id="total-energy">--</span>
                        </div>
                        
                        <hr>
                        
                        <h5>Return (kWh)</h5>
                        <div class="info-row">
                            <span class="info-label">Phase A:</span>
                            <span id="phase-a-return">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Phase B:</span>
                            <span id="phase-b-return">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Phase C:</span>
                            <span id="phase-c-return">--</span>
                        </div>
                        <div class="info-row">
                            <span class="info-label">Total:</span>
                            <span id="total-return">--</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <footer class="text-center mt-4 mb-4">
            <p>3EM Energy Meter Dashboard | <a href="https://github.com/tonytopp" target="_blank">Tony Topp</a></p>
        </footer>
    </div>
    
    <script>
        // Initialize power chart
        const ctx = document.getElementById('power-chart').getContext('2d');
        const powerChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Phase A',
                        data: [],
                        borderColor: '#ff6384',
                        backgroundColor: 'rgba(255, 99, 132, 0.1)',
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: 'Phase B',
                        data: [],
                        borderColor: '#36a2eb',
                        backgroundColor: 'rgba(54, 162, 235, 0.1)',
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: 'Phase C',
                        data: [],
                        borderColor: '#4bc0c0',
                        backgroundColor: 'rgba(75, 192, 192, 0.1)',
                        tension: 0.4,
                        borderWidth: 2
                    },
                    {
                        label: 'Total',
                        data: [],
                        borderColor: '#ffcd56',
                        backgroundColor: 'rgba(255, 205, 86, 0.1)',
                        tension: 0.4,
                        borderWidth: 2
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        title: {
                            display: true,
                            text: 'Power (W)'
                        }
                    },
                    x: {
                        title: {
                            display: true,
                            text: 'Time'
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top',
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `${context.dataset.label}: ${context.raw} W`;
                            }
                        }
                    }
                }
            }
        });
        
        // Function to update the dashboard with new data
        function updateDashboard() {
            fetch('/api/meter-data')
                .then(response => response.json())
                .then(data => {
                    // Update last updated time
                    document.getElementById('last-updated').textContent = data.last_updated || 'Never';
                    
                    // Check for errors
                    const errorAlert = document.getElementById('error-alert');
                    if (data.error) {
                        errorAlert.textContent = data.error;
                        errorAlert.style.display = 'block';
                    } else {
                        errorAlert.style.display = 'none';
                    }
                    
                    // Update IP input
                    document.getElementById('ip-input').value = data.ip_address;
                    
                    // Update power values if status data is available
                    if (data.status && data.status['em:0']) {
                        const emData = data.status['em:0'];
                        
                        // Phase A
                        const phaseAPower = emData.a_act_power || 0;
                        document.getElementById('phase-a-power').textContent = phaseAPower.toFixed(1);
                        document.getElementById('phase-a-power').className = phaseAPower < 0 ? 'power-value text-success' : 'power-value text-danger';
                        
                        // Phase B
                        const phaseBPower = emData.b_act_power || 0;
                        document.getElementById('phase-b-power').textContent = phaseBPower.toFixed(1);
                        document.getElementById('phase-b-power').className = phaseBPower < 0 ? 'power-value text-success' : 'power-value text-danger';
                        
                        // Phase C
                        const phaseCPower = emData.c_act_power || 0;
                        document.getElementById('phase-c-power').textContent = phaseCPower.toFixed(1);
                        document.getElementById('phase-c-power').className = phaseCPower < 0 ? 'power-value text-success' : 'power-value text-danger';
                        
                        // Phase C status badge
                        if (phaseCPower < 0) {
                            document.getElementById('phase-c-status').innerHTML = '<span class="badge bg-success">PRODUCING</span>';
                        } else {
                            document.getElementById('phase-c-status').innerHTML = '<span class="badge bg-warning text-dark">CONSUMING</span>';
                        }
                        
                        // Total
                        const totalPower = emData.total_act_power || 0;
                        document.getElementById('total-power').textContent = totalPower.toFixed(1);
                        document.getElementById('total-power').className = totalPower < 0 ? 'power-value text-success' : 'power-value text-danger';
                        
                        // Update electrical parameters
                        document.getElementById('phase-a-current').textContent = `${emData.a_current || 0} A`;
                        document.getElementById('phase-a-voltage').textContent = `${emData.a_voltage || 0} V`;
                        document.getElementById('phase-a-pf').textContent = emData.a_pf || 0;
                        
                        document.getElementById('phase-b-current').textContent = `${emData.b_current || 0} A`;
                        document.getElementById('phase-b-voltage').textContent = `${emData.b_voltage || 0} V`;
                        document.getElementById('phase-b-pf').textContent = emData.b_pf || 0;
                        
                        document.getElementById('phase-c-current').textContent = `${emData.c_current || 0} A`;
                        document.getElementById('phase-c-voltage').textContent = `${emData.c_voltage || 0} V`;
                        document.getElementById('phase-c-pf').textContent = emData.c_pf || 0;
                    }
                    
                    // Update energy data if available
                    if (data.status && data.status['emdata:0']) {
                        const emData = data.status['emdata:0'];
                        
                        document.getElementById('phase-a-energy').textContent = (emData.a_total_act_energy || 0).toFixed(2);
                        document.getElementById('phase-b-energy').textContent = (emData.b_total_act_energy || 0).toFixed(2);
                        document.getElementById('phase-c-energy').textContent = (emData.c_total_act_energy || 0).toFixed(2);
                        document.getElementById('total-energy').textContent = (emData.total_act || 0).toFixed(2);
                        
                        document.getElementById('phase-a-return').textContent = (emData.a_total_act_ret_energy || 0).toFixed(2);
                        document.getElementById('phase-b-return').textContent = (emData.b_total_act_ret_energy || 0).toFixed(2);
                        document.getElementById('phase-c-return').textContent = (emData.c_total_act_ret_energy || 0).toFixed(2);
                        document.getElementById('total-return').textContent = (emData.total_act_ret || 0).toFixed(2);
                    }
                    
                    // Update chart
                    if (data.history && data.history.timestamps.length > 0) {
                        powerChart.data.labels = data.history.timestamps;
                        powerChart.data.datasets[0].data = data.history.phase_a;
                        powerChart.data.datasets[1].data = data.history.phase_b;
                        powerChart.data.datasets[2].data = data.history.phase_c;
                        powerChart.data.datasets[3].data = data.history.total;
                        powerChart.update();
                    }
                })
                .catch(error => {
                    console.error('Error fetching meter data:', error);
                    document.getElementById('error-alert').textContent = 'Error connecting to the server.';
                    document.getElementById('error-alert').style.display = 'block';
                });
        }
        
        // Update IP address
        document.getElementById('update-ip-btn').addEventListener('click', function() {
            const newIp = document.getElementById('ip-input').value;
            
            fetch('/api/update-ip', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ ip: newIp })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    updateDashboard();
                } else {
                    alert('Error: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Error updating IP:', error);
                alert('Error updating IP address');
            });
        });
        
        // Reset history
        document.getElementById('reset-history-btn').addEventListener('click', function() {
            fetch('/api/reset-history', {
                method: 'POST'
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(data.message);
                    updateDashboard();
                } else {
                    alert('Error: ' + data.message);
                }
            })
            .catch(error => {
                console.error('Error resetting history:', error);
                alert('Error resetting history data');
            });
        });
        
        // Initial update
        updateDashboard();
        
        // Set up periodic updates
        setInterval(updateDashboard, 5000);
    </script>
</body>
</html>
    """
    
    with open(os.path.join(templates_dir, '3em_dashboard.html'), 'w') as f:
        f.write(dashboard_html)

if __name__ == '__main__':
    # Create template files
    create_templates()
    
    # Start the background data collection thread
    data_thread = threading.Thread(target=update_meter_data, daemon=True)
    data_thread.start()
    
    # Start the Flask app
    app.run(host='0.0.0.0', port=8085, debug=False)
