from kubernetes import client, config
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import sqlite3
import time 
last_alert_time = 0 
# Cooldown period in seconds (e.g., 300 seconds = 5 minutes)
ALERT_COOLDOWN = 120

import csv
import io
from flask import make_response

import smtplib
from email.message import EmailMessage

import psutil
from flask import Flask, render_template, jsonify
from datetime import datetime
import json
import os  

import requests
from dotenv import load_dotenv 

load_dotenv()
webhook_url = os.getenv('SLACK_WEBHOOK_URL')

def send_email_alert(subject, body):
    # Pull from .env for security
    sender_email = os.getenv("SENDER_EMAIL")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all([sender_email, receiver_email, app_password]):
        print("Email credentials missing in .env")
        return

    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = receiver_email
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.send_message(msg)
            print(f"Email sent: {subject}")
    except Exception as e:
        print(f"Email error: {e}") 


def generate_summary_report(days=1):
    conn = sqlite3.connect(DB_PATH) # Using your dynamic path
    cursor = conn.cursor()
    
    # Simple query to get average metrics from the last X days
    query = "SELECT AVG(cpu), AVG(memory) FROM metrics WHERE timestamp > datetime('now', ?)"
    cursor.execute(query, (f'-{days} days',))
    
    avg_cpu, avg_mem = cursor.fetchone()
    conn.close()

    # Handle cases where the database might be empty to avoid errors
    cpu_val = avg_cpu if avg_cpu is not None else 0
    mem_val = avg_mem if avg_mem is not None else 0

    report_body = f"Summary Report for last {days} day(s):\nAvg CPU: {cpu_val:.2f}%\nAvg RAM: {mem_val:.2f}%"
    
    # 🟢 FIX: Only send the relevant report
    send_email_alert(f"Cloud Monitor: {days}-Day Report", report_body)
    
def send_slack_message(text):
    """Sends a notification to the Slack webhook URL"""
    if not webhook_url:
        print("❌ SLACK_WEBHOOK_URL not set in .env")
        return False
    
    payload = {"text": text}
    try:
        response = requests.post(webhook_url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Slack error: {e}")
        return False


app = Flask(__name__)

# File to store historical data
DATA_FILE = 'backend_data.json'

# Global variable to store recent data points (In-memory history)
# We need history to "teach" the AI what is normal
history = [] 
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, 'metrics.db')

def save_to_db(cpu, memory, disk):
    """Saves metrics to SQL so the CSV export works"""
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS metrics 
                          (timestamp TEXT, cpu REAL, memory REAL, disk REAL)''')
        cursor.execute("INSERT INTO metrics VALUES (?, ?, ?, ?)", 
                       (datetime.now().isoformat(), cpu, memory, disk))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

def load_history():
    """Load historical data from JSON file"""
    global history
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                history = json.load(f)
                # Keep only last 100 data points
                if len(history) > 100:
                    history = history[-100:]
        except:
            history = []

def save_data_point(data):
    """Save current data point to history"""
    global history
    history.append(data)
    
    # Keep only the last 100 data points to keep it fast and responsive
    if len(history) > 100:
        history.pop(0)
    
    # Save to file
    try:
        with open(DATA_FILE, 'w') as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving data: {e}")

def get_top_processes(limit=5):
    """Get top CPU and Memory consuming processes"""
    processes = []
    
    for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            pinfo = proc.info
            processes.append({
                'pid': pinfo['pid'],
                'name': pinfo['name'],
                'cpu': round(pinfo['cpu_percent'], 1),
                'memory': round(pinfo['memory_percent'], 1)
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    
    # Sort by CPU usage
    processes_by_cpu = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:limit]
    
    # Sort by Memory usage
    processes_by_memory = sorted(processes, key=lambda x: x['memory'], reverse=True)[:limit]
    
    return {
        'by_cpu': processes_by_cpu,
        'by_memory': processes_by_memory
    }

def detect_anomaly(cpu, memory, disk):
    """
    Simple anomaly detection based on historical data
    Returns: (is_anomaly, message)
    """
    if len(history) < 30:  # Need at least 30 data points
        return False, "Collecting baseline data..."
    
    # Calculate average and standard deviation from history
    cpu_values = [h['cpu'] for h in history[-30:]]
    memory_values = [h['memory'] for h in history[-30:]]
    disk_values = [h['disk'] for h in history[-30:]]
    
    avg_cpu = sum(cpu_values) / len(cpu_values)
    avg_memory = sum(memory_values) / len(memory_values)
    avg_disk = sum(disk_values) / len(disk_values)
    
    # Simple threshold-based detection
    # Anomaly if current value is significantly different from average
    cpu_diff = abs(cpu - avg_cpu)
    memory_diff = abs(memory - avg_memory)
    disk_diff = abs(disk - avg_disk)
    
    # Thresholds
    if cpu_diff > 30:
        return True, f"AI Alert: Unusual CPU Spike Detected! (Current: {cpu}%, Normal: {avg_cpu:.1f}%)"
    
    if memory_diff > 15:
        return True, f"AI Alert: Unusual Memory Pattern Detected! (Current: {memory}%, Normal: {avg_memory:.1f}%)"
    
    if disk_diff > 5:
        return True, f"AI Alert: Unusual Disk Usage Change! (Current: {disk}%, Normal: {avg_disk:.1f}%)"
    
    # Check absolute thresholds
    if cpu > 80:             
        return True, "Alert: High CPU Usage Detected!"
    
    if memory > 85:
        return True, "Alert: High Memory Usage Detected!"
    
    if disk > 90:
        return True, "Alert: Critical Disk Space!"
    
    return False, "System Normal"   

def get_pod_health():
    try:
        # Check if we are in the cloud (EKS) or local (Laptop/Minikube)
        try:
            config.load_incluster_config() # Try Cloud first
        except:
            config.load_kube_config()      # Fallback to Local/Minikube

        v1 = client.CoreV1Api()
        pods = v1.list_pod_for_all_namespaces(watch=False)
        
        pod_list = []
        for pod in pods.items:
            pod_list.append({
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "ip": pod.status.pod_ip,
                "health": "healthy" if pod.status.phase == "Running" else "critical" # Added health flag
            })
        return pod_list
    except Exception as e:
        return [] # Return empty list so the frontend doesn't crash



@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/metrics')
def get_metrics():
    """API endpoint to get current system metrics with Alert Cooldown"""
    global last_alert_time
   # name: cloudmonitor-sa

    # 1. Collect Metrics (Don't forget these!)
    cpu_metric = psutil.cpu_percent(interval=1)
    mem_metric = psutil.virtual_memory().percent
    disk_metric = psutil.disk_usage('/').percent
    
    # 2. Network and Processes
    net_io = psutil.net_io_counters()
    network_sent_gb = round(net_io.bytes_sent / (1024**3), 2)
    network_recv_gb = round(net_io.bytes_recv / (1024**3), 2)
    top_processes = get_top_processes(5)
    
    # 3. Update History
    data_point = {
        'cpu': cpu_metric,
        'memory': mem_metric,
        'disk': disk_metric,
        'timestamp': datetime.now().isoformat()
    }
    save_data_point(data_point) 

    save_to_db(cpu_metric, mem_metric, disk_metric)
    
    # 4. AI-Powered Anomaly Detection
    is_anomaly, alert_message = detect_anomaly(cpu_metric, mem_metric, disk_metric)

    # 5. Throttled Slack Trigger
    if is_anomaly:
        current_time = time.time()
        # Only send if the 300-second cooldown has passed
        if (current_time - last_alert_time) > ALERT_COOLDOWN:
            send_slack_message(f"🚨 *CloudMonitor Alert:* {alert_message}")
            last_alert_time = current_time 
            print("✓ Slack alert sent.")
        else:
            remaining = int(ALERT_COOLDOWN - (current_time - last_alert_time))
            print(f"Alert suppressed. Next available in: {remaining}s")
    
    # 6. Return data to the Dashboard
    return jsonify({
        'cpu': cpu_metric,
        'memory': mem_metric,
        'disk': disk_metric,
        'network': {'sent_gb': network_sent_gb, 'recv_gb': network_recv_gb},
        'top_processes': top_processes,
        'alert': {'triggered': is_anomaly, 'message': alert_message},
        'timestamp': datetime.now().isoformat()
    })


@app.route('/api/history')
def get_history():
    """API endpoint to get historical data"""
    return jsonify(history[-50:])  # Return last 50 data points

@app.route('/api/export-csv')
def export_csv():
    """Generates a CSV file from the metrics.db data"""
    try:
        # Use the database you've already established in your actual app
        conn = sqlite3.connect('metrics.db')
        cursor = conn.cursor()
        
        # Select the same columns seen in your history endpoint
      
        cursor.execute("SELECT timestamp, cpu, memory, disk FROM metrics ORDER BY timestamp DESC")
        data = cursor.fetchall()
        conn.close()

        # Create CSV in memory using io.StringIO
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Timestamp', 'CPU Usage (%)', 'Memory Usage (%)', 'Disk Usage (%)']) # Headers
        writer.writerows(data)

        # Create and return the response as a downloadable file
        response = make_response(output.getvalue())
        report_time = datetime.now().strftime('%Y%m%d_%H%M')
        response.headers["Content-Disposition"] = f"attachment; filename=CloudMonitor_Report_{report_time}.csv"
        response.headers["Content-type"] = "text/csv"
        return response
    except Exception as e:
        print(f"Export Error: {e}")
        return jsonify({"error": "Failed to generate report"}), 500
    

@app.route('/api/pods')
def get_pods():
    # This calls the function you've likely started in k8s_monitor.py
    pods = get_pod_health() 
    return jsonify(pods)

@app.route('/health')
def health_check():
    """Kubernetes liveness probe"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.route('/ready')
def readiness_check():
    """Kubernetes readiness probe"""
    try:
        # Check if we can collect metrics
        psutil.cpu_percent()
        psutil.virtual_memory()
        return jsonify({'status': 'ready'}), 200
    except Exception as e:
        return jsonify({'status': 'not ready', 'error': str(e)}), 503 
    
    # --- SCHEDULER SETUP ---
# 1. Initialize the background scheduler
scheduler = BackgroundScheduler()

# 2. Schedule the report for 09:00 AM every day
scheduler.add_job(func=generate_summary_report, trigger='cron', hour=9, minute=0)

# 3. Start the scheduler thread
scheduler.start()

# --- 🧪 MANUAL EMAIL VERIFICATION ---
# Triggering this once manually right now to verify your App Password works!
print("🚀 Triggering manual email verification...")
#generate_summary_report(days=1)
# ------------------------------------

if __name__ == '__main__':
    # Load historical data on startup
    load_history()
    
    print("=" * 50)
    print("Cloud Native Monitoring App Starting...")
    print("Features Enabled:")
    print("✓ Real-time CPU & Memory Monitoring")
    print("✓ Disk Usage Monitoring")
    print("✓ Network Traffic Monitoring")
    print("✓ Top Process Tracking")
    print("✓ Historical Data Storage")
    print("✓ AI-Powered Anomaly Detection")
    print("=" * 50)
    
    app.run( host='0.0.0.0', port=5000)
    is_debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=is_debug)
    
