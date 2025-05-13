#!/usr/bin/env python3
"""
3EM Energy Meter Checker
A utility to check and troubleshoot Shelly 3EM energy meter settings and data.
"""

import requests
import json
import argparse
import time
from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import print as rprint

console = Console()

def get_device_info(ip_address):
    """Get basic device information"""
    try:
        url = f"http://{ip_address}/shelly"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            console.print(f"[red]Error getting device info: Status code {response.status_code}[/red]")
            return None
    except Exception as e:
        console.print(f"[red]Error connecting to device: {str(e)}[/red]")
        return None

def get_device_status(ip_address):
    """Get full device status"""
    try:
        url = f"http://{ip_address}/rpc/Shelly.GetStatus"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            console.print(f"[red]Error getting device status: Status code {response.status_code}[/red]")
            return None
    except Exception as e:
        console.print(f"[red]Error connecting to device: {str(e)}[/red]")
        return None

def get_device_config(ip_address):
    """Get device configuration"""
    try:
        url = f"http://{ip_address}/rpc/Shelly.GetConfig"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return response.json()
        else:
            console.print(f"[red]Error getting device config: Status code {response.status_code}[/red]")
            return None
    except Exception as e:
        console.print(f"[red]Error connecting to device: {str(e)}[/red]")
        return None

def display_device_info(info):
    """Display basic device information"""
    if not info:
        return
    
    console.print(Panel.fit(
        f"[bold]Device Information[/bold]\n"
        f"Type: {info.get('type', 'Unknown')}\n"
        f"Model: {info.get('model', 'Unknown')}\n"
        f"MAC: {info.get('mac', 'Unknown')}\n"
        f"Firmware: {info.get('fw_id', 'Unknown')}\n"
        f"Auth: {'Enabled' if info.get('auth', False) else 'Disabled'}\n",
        title="Shelly 3EM", 
        border_style="green"
    ))

def display_power_data(status):
    """Display power data from all phases"""
    if not status or 'em:0' not in status:
        console.print("[red]No power data available[/red]")
        return
    
    em_data = status['em:0']
    
    # Create a table for power data
    table = Table(title="Power Data")
    table.add_column("Phase", style="cyan")
    table.add_column("Current (A)", justify="right", style="magenta")
    table.add_column("Voltage (V)", justify="right", style="magenta")
    table.add_column("Power (W)", justify="right", style="green")
    table.add_column("Apparent Power (VA)", justify="right", style="yellow")
    table.add_column("Power Factor", justify="right", style="blue")
    table.add_column("Frequency (Hz)", justify="right", style="magenta")
    
    # Add data for each phase
    phases = ['a', 'b', 'c']
    for phase in phases:
        current = em_data.get(f'{phase}_current', 'N/A')
        voltage = em_data.get(f'{phase}_voltage', 'N/A')
        power = em_data.get(f'{phase}_act_power', 'N/A')
        apparent = em_data.get(f'{phase}_aprt_power', 'N/A')
        pf = em_data.get(f'{phase}_pf', 'N/A')
        freq = em_data.get(f'{phase}_freq', 'N/A')
        
        # Format the power value with color based on direction
        power_str = f"{power}"
        if power is not None and power < 0:
            power_str = f"[bold green]{power}[/bold green]"
        elif power is not None:
            power_str = f"[bold red]{power}[/bold red]"
        
        table.add_row(
            phase.upper(),
            f"{current}" if current is not None else "N/A",
            f"{voltage}" if voltage is not None else "N/A",
            power_str,
            f"{apparent}" if apparent is not None else "N/A",
            f"{pf}" if pf is not None else "N/A",
            f"{freq}" if freq is not None else "N/A"
        )
    
    # Add total row
    total_current = em_data.get('total_current', 'N/A')
    total_power = em_data.get('total_act_power', 'N/A')
    total_apparent = em_data.get('total_aprt_power', 'N/A')
    
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"{total_current}" if total_current is not None else "N/A",
        "N/A",
        f"{total_power}" if total_power is not None else "N/A",
        f"{total_apparent}" if total_apparent is not None else "N/A",
        "N/A",
        "N/A"
    )
    
    console.print(table)

def display_energy_data(status):
    """Display energy consumption and return data"""
    if not status or 'emdata:0' not in status:
        console.print("[red]No energy data available[/red]")
        return
    
    emdata = status['emdata:0']
    
    # Create a table for energy data
    table = Table(title="Energy Data (kWh)")
    table.add_column("Phase", style="cyan")
    table.add_column("Consumption (kWh)", justify="right", style="red")
    table.add_column("Return (kWh)", justify="right", style="green")
    
    # Add data for each phase
    phases = ['a', 'b', 'c']
    for phase in phases:
        consumption = emdata.get(f'{phase}_total_act_energy', 'N/A')
        returned = emdata.get(f'{phase}_total_act_ret_energy', 'N/A')
        
        table.add_row(
            phase.upper(),
            f"{consumption:.2f}" if isinstance(consumption, (int, float)) else "N/A",
            f"{returned:.2f}" if isinstance(returned, (int, float)) else "N/A"
        )
    
    # Add total row
    total_consumption = emdata.get('total_act', 'N/A')
    total_return = emdata.get('total_act_ret', 'N/A')
    
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"{total_consumption:.2f}" if isinstance(total_consumption, (int, float)) else "N/A",
        f"{total_return:.2f}" if isinstance(total_return, (int, float)) else "N/A"
    )
    
    console.print(table)

def display_network_info(status):
    """Display network information"""
    if not status:
        return
    
    wifi_info = status.get('wifi', {})
    eth_info = status.get('eth', {})
    mqtt_info = status.get('mqtt', {})
    cloud_info = status.get('cloud', {})
    
    network_panel = Panel.fit(
        f"[bold]Network Information[/bold]\n\n"
        f"[bold]WiFi:[/bold]\n"
        f"  Connected: {wifi_info.get('connected', False)}\n"
        f"  SSID: {wifi_info.get('ssid', 'N/A')}\n"
        f"  IP: {wifi_info.get('ip', 'N/A')}\n"
        f"  RSSI: {wifi_info.get('rssi', 'N/A')}\n\n"
        f"[bold]Ethernet:[/bold]\n"
        f"  Connected: {eth_info.get('connected', False)}\n"
        f"  IP: {eth_info.get('ip', 'N/A')}\n\n"
        f"[bold]MQTT:[/bold]\n"
        f"  Connected: {mqtt_info.get('connected', False)}\n\n"
        f"[bold]Cloud:[/bold]\n"
        f"  Connected: {cloud_info.get('connected', False)}\n"
        f"  Enabled: {cloud_info.get('enabled', False)}\n",
        title="Network Status", 
        border_style="blue"
    )
    
    console.print(network_panel)

def display_system_info(status):
    """Display system information"""
    if not status or 'sys' not in status:
        return
    
    sys_info = status['sys']
    
    uptime_seconds = sys_info.get('uptime', 0)
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{int(days)}d {int(hours)}h {int(minutes)}m {int(seconds)}s"
    
    system_panel = Panel.fit(
        f"[bold]System Information[/bold]\n\n"
        f"Time: {sys_info.get('time', 'N/A')}\n"
        f"Uptime: {uptime_str}\n"
        f"RAM Size: {sys_info.get('ram_size', 'N/A')} bytes\n"
        f"RAM Free: {sys_info.get('ram_free', 'N/A')} bytes\n"
        f"FS Size: {sys_info.get('fs_size', 'N/A')} bytes\n"
        f"FS Free: {sys_info.get('fs_free', 'N/A')} bytes\n"
        f"Restart Required: {sys_info.get('restart_required', False)}\n",
        title="System Status", 
        border_style="yellow"
    )
    
    console.print(system_panel)

def monitor_power(ip_address, interval=5, count=None):
    """Monitor power data in real-time"""
    try:
        i = 0
        while count is None or i < count:
            console.clear()
            console.print(f"[bold]3EM Power Monitor[/bold] - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            console.print(f"Monitoring device at [bold]{ip_address}[/bold] (Press Ctrl+C to stop)")
            console.print("")
            
            status = get_device_status(ip_address)
            if status:
                display_power_data(status)
            else:
                console.print("[red]Failed to get device status[/red]")
            
            if count is not None:
                i += 1
                if i < count:
                    console.print(f"\nRefreshing in {interval} seconds... ({i}/{count})")
                    time.sleep(interval)
            else:
                console.print(f"\nRefreshing in {interval} seconds... (Press Ctrl+C to stop)")
                time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[yellow]Monitoring stopped by user[/yellow]")

def main():
    parser = argparse.ArgumentParser(description='Shelly 3EM Energy Meter Checker')
    parser.add_argument('--ip', type=str, default='192.168.1.194', help='IP address of the 3EM device')
    parser.add_argument('--info', action='store_true', help='Show basic device information')
    parser.add_argument('--status', action='store_true', help='Show device status')
    parser.add_argument('--config', action='store_true', help='Show device configuration')
    parser.add_argument('--power', action='store_true', help='Show power data')
    parser.add_argument('--energy', action='store_true', help='Show energy data')
    parser.add_argument('--network', action='store_true', help='Show network information')
    parser.add_argument('--system', action='store_true', help='Show system information')
    parser.add_argument('--monitor', action='store_true', help='Monitor power data in real-time')
    parser.add_argument('--interval', type=int, default=5, help='Refresh interval for monitoring (seconds)')
    parser.add_argument('--count', type=int, help='Number of times to refresh when monitoring')
    parser.add_argument('--all', action='store_true', help='Show all available information')
    parser.add_argument('--raw', action='store_true', help='Show raw JSON data')
    
    args = parser.parse_args()
    
    # Default to showing all if no specific options are selected
    if not any([args.info, args.status, args.config, args.power, args.energy, 
                args.network, args.system, args.monitor, args.all, args.raw]):
        args.all = True
    
    ip_address = args.ip
    console.print(f"[bold]Shelly 3EM Checker[/bold] - Connecting to {ip_address}...")
    
    if args.monitor:
        monitor_power(ip_address, args.interval, args.count)
        return
    
    # Get device information
    if args.info or args.all:
        info = get_device_info(ip_address)
        if info:
            display_device_info(info)
            if args.raw:
                console.print("\n[bold]Raw Device Info:[/bold]")
                console.print(json.dumps(info, indent=2))
        else:
            console.print("[red]Failed to get device information[/red]")
    
    # Get device status
    status = None
    if args.status or args.power or args.energy or args.network or args.system or args.all:
        status = get_device_status(ip_address)
        if status and args.status:
            console.print("\n[bold]Device Status:[/bold]")
            if args.raw:
                console.print(json.dumps(status, indent=2))
            else:
                console.print("Device status retrieved successfully. Use specific options to view details.")
    
    # Display power data
    if status and (args.power or args.all):
        console.print("")
        display_power_data(status)
    
    # Display energy data
    if status and (args.energy or args.all):
        console.print("")
        display_energy_data(status)
    
    # Display network information
    if status and (args.network or args.all):
        console.print("")
        display_network_info(status)
    
    # Display system information
    if status and (args.system or args.all):
        console.print("")
        display_system_info(status)
    
    # Get device configuration
    if args.config or args.all:
        config = get_device_config(ip_address)
        if config:
            console.print("\n[bold]Device Configuration:[/bold]")
            if args.raw:
                console.print(json.dumps(config, indent=2))
            else:
                console.print("Configuration retrieved successfully. Use --raw to view the full configuration.")
        else:
            console.print("[red]Failed to get device configuration[/red]")

if __name__ == "__main__":
    main()
