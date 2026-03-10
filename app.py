from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import sqlite3
import time 
import hmac
last_alert_time = 0 
last_email_alert_time = 0
# Cooldown period in seconds (e.g., 300 seconds = 5 minutes)
ALERT_COOLDOWN = 120
EMAIL_ALERT_COOLDOWN = 300
CPU_ABSOLUTE_ALERT_THRESHOLD = 80
MEMORY_ABSOLUTE_ALERT_THRESHOLD = 85
DISK_ABSOLUTE_ALERT_THRESHOLD = 90
BASELINE_POINTS_REQUIRED = 30

import csv
import io
from flask import make_response

import smtplib
from email.message import EmailMessage

import psutil
from flask import Flask, render_template, jsonify, request
import json
import os  
import requests
from dotenv import load_dotenv 
try:
    from flask_httpauth import HTTPBasicAuth
except ImportError:
    HTTPBasicAuth = None

load_dotenv()
webhook_url = os.getenv('SLACK_WEBHOOK_URL')
DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME")
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD")
AUTH_ENABLED = (
    os.getenv("AUTH_ENABLED", "true").lower() in ("1", "true", "yes")
    and HTTPBasicAuth is not None
    and bool(DASHBOARD_USERNAME)
    and bool(DASHBOARD_PASSWORD)
)

if HTTPBasicAuth is None:
    print("⚠️ flask-httpauth is not installed. Dashboard auth is disabled.")
elif os.getenv("AUTH_ENABLED", "true").lower() in ("1", "true", "yes") and not AUTH_ENABLED:
    print("⚠️ AUTH_ENABLED is true but DASHBOARD_USERNAME/PASSWORD not set. Auth is disabled.")

if HTTPBasicAuth is not None:
    auth = HTTPBasicAuth()
else:
    class NoAuth:
        def verify_password(self, func):
            return func

        def login_required(self, func):
            return func

    auth = NoAuth()


@auth.verify_password
def verify_password(username, password):
    if not AUTH_ENABLED:
        return True

    return (
        hmac.compare_digest(username or "", DASHBOARD_USERNAME)
        and hmac.compare_digest(password or "", DASHBOARD_PASSWORD)
    )


def require_auth(func):
    if not AUTH_ENABLED:
        return func
    return auth.login_required(func)

def send_email_alert(subject, body):
    # Pull from .env for security
    sender_email = os.getenv("SENDER_EMAIL")
    receiver_email = os.getenv("RECEIVER_EMAIL")
    app_password = os.getenv("GMAIL_APP_PASSWORD")

    if not all([sender_email, receiver_email, app_password]):
        print("Email credentials missing in .env")
        return False

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
            return True
    except Exception as e:
        print(f"Email error: {e}") 
        return False


def generate_summary_report(days=1):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            query = "SELECT AVG(cpu), AVG(memory) FROM metrics WHERE timestamp > datetime('now', ?)"
            cursor.execute(query, (f'-{days} days',))
            avg_cpu, avg_mem = cursor.fetchone()
    except sqlite3.Error as e:
        print(f"Summary report DB error: {e}")
        return

    # Handle cases where the database might be empty to avoid errors
    cpu_val = avg_cpu if avg_cpu is not None else 0
    mem_val = avg_mem if avg_mem is not None else 0

    report_body = f"Summary Report for last {days} day(s):\nAvg CPU: {cpu_val:.2f}%\nAvg RAM: {mem_val:.2f}%"
    
    # 🟢 FIX: Only send the relevant report
    send_email_alert(f"Cloud Monitor: {days}-Day Report", report_body)


def send_anomaly_email_report(cpu, memory, disk, alert_message, current_time=None, force=False):
    global last_email_alert_time
    if current_time is None:
        current_time = time.time()

    if not force and (current_time - last_email_alert_time) <= EMAIL_ALERT_COOLDOWN:
        remaining = int(EMAIL_ALERT_COOLDOWN - (current_time - last_email_alert_time))
        return False, remaining

    report_body = (
        "Cloud Monitor Alert Report:\n"
        f"Time: {datetime.now().isoformat()}\n"
        f"CPU: {cpu:.2f}%\n"
        f"Memory: {memory:.2f}%\n"
        f"Disk: {disk:.2f}%\n"
        f"Detection: {alert_message}"
    )
    if send_email_alert("Cloud Monitor: Alert Report", report_body):
        last_email_alert_time = current_time
        return True, 0
    return False, 0
    
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
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''CREATE TABLE IF NOT EXISTS metrics 
                              (timestamp TEXT, cpu REAL, memory REAL, disk REAL)''')
            cursor.execute("INSERT INTO metrics VALUES (?, ?, ?, ?)", 
                           (datetime.now().isoformat(), cpu, memory, disk))
            conn.commit()
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
        except (OSError, json.JSONDecodeError) as e:
            print(f"History load error: {e}")
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
    # Always enforce absolute thresholds, even before baseline is built.
    if cpu > CPU_ABSOLUTE_ALERT_THRESHOLD:
        return True, "AI Alert: High CPU Usage Detected!"
    
    if memory > MEMORY_ABSOLUTE_ALERT_THRESHOLD:
        return True, "AI Alert: High Memory Usage Detected!"
    
    if disk > DISK_ABSOLUTE_ALERT_THRESHOLD:
        return True, "AI Alert: Critical Disk Space!"

    if len(history) < BASELINE_POINTS_REQUIRED:
        return False, f"Collecting baseline data... ({len(history)}/{BASELINE_POINTS_REQUIRED})"
    
    # Calculate average and standard deviation from history
    cpu_values = [h['cpu'] for h in history[-BASELINE_POINTS_REQUIRED:]]
    memory_values = [h['memory'] for h in history[-BASELINE_POINTS_REQUIRED:]]
    disk_values = [h['disk'] for h in history[-BASELINE_POINTS_REQUIRED:]]
    
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
    
    return False, "System Operating Normally"   

def get_pod_health():
    try:
        try:
            config.load_incluster_config()
        except ConfigException:
            config.load_kube_config()

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
        return pod_list, None
    except Exception as e:
        error_message = str(e)
        print(f"Pod health error: {error_message}")
        return [], error_message



@app.route('/')
@require_auth
def index():
    return render_template('index.html')


@app.route('/api/metrics')
@require_auth
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
    
    # 3. AI-Powered Anomaly Detection (use prior history, not current point)
    is_anomaly, alert_message = detect_anomaly(cpu_metric, mem_metric, disk_metric)

    # 4. Update History after detection
    data_point = {
        'cpu': cpu_metric,
        'memory': mem_metric,
        'disk': disk_metric,
        'timestamp': datetime.now().isoformat()
    }
    save_data_point(data_point) 
    save_to_db(cpu_metric, mem_metric, disk_metric)

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

        email_sent, email_remaining = send_anomaly_email_report(
            cpu_metric, mem_metric, disk_metric, alert_message, current_time=current_time
        )
        if email_sent:
            print("✓ Email alert sent.")
        elif email_remaining > 0:
            print(f"Email alert suppressed. Next available in: {email_remaining}s")
    
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
@require_auth
def get_history():
    """API endpoint to get historical data"""
    return jsonify(history[-50:])  # Return last 50 data points


@app.route('/api/demo/send-summary-email', methods=['GET', 'POST'])
@require_auth
def demo_send_summary_email():
    """Manually trigger summary email for demos."""
    days = request.args.get('days', default=1, type=int)
    if days is None or days < 1 or days > 30:
        return jsonify({"error": "days must be between 1 and 30"}), 400

    generate_summary_report(days=days)
    return jsonify({
        "status": "sent",
        "type": "summary",
        "days": days
    })


@app.route('/api/demo/send-alert-email', methods=['GET', 'POST'])
@require_auth
def demo_send_alert_email():
    """Manually trigger anomaly email report for demos."""
    payload = request.get_json(silent=True) or {}

    def read_metric(name, default):
        query_val = request.args.get(name, default=None, type=float)
        if query_val is not None:
            return query_val
        try:
            return float(payload.get(name, default))
        except (TypeError, ValueError):
            return default

    cpu = read_metric("cpu", psutil.cpu_percent(interval=0))
    memory = read_metric("memory", psutil.virtual_memory().percent)
    disk = read_metric("disk", psutil.disk_usage('/').percent)

    force_flag = request.args.get("force", str(payload.get("force", "false"))).lower()
    force_send = force_flag in ("1", "true", "yes")

    is_anomaly, alert_message = detect_anomaly(cpu, memory, disk)
    if not is_anomaly and not force_send:
        return jsonify({
            "status": "not_sent",
            "reason": "No anomaly detected. Use force=true to send anyway.",
            "alert": {"triggered": is_anomaly, "message": alert_message},
            "metrics": {"cpu": cpu, "memory": memory, "disk": disk}
        })

    email_sent, email_remaining = send_anomaly_email_report(
        cpu, memory, disk, alert_message, force=force_send
    )
    if not email_sent and email_remaining > 0:
        return jsonify({
            "status": "suppressed",
            "reason": f"Email cooldown active. Try again in {email_remaining}s.",
            "alert": {"triggered": is_anomaly, "message": alert_message},
            "metrics": {"cpu": cpu, "memory": memory, "disk": disk}
        })

    return jsonify({
        "status": "sent",
        "type": "alert",
        "alert": {"triggered": is_anomaly, "message": alert_message},
        "metrics": {"cpu": cpu, "memory": memory, "disk": disk}
    })


@app.route('/api/demo/send-slack-alert', methods=['GET', 'POST'])
@require_auth
def demo_send_slack_alert():
    """Manually trigger a Slack alert for demos."""
    global last_alert_time

    payload = request.get_json(silent=True) or {}

    message = request.args.get("message", default=None, type=str)
    if not message:
        message = payload.get("message")
    if not message:
        message = "🚨 *CloudMonitor Demo Alert:* Manual Slack alert test."

    force_flag = request.args.get("force", str(payload.get("force", "false"))).lower()
    force_send = force_flag in ("1", "true", "yes")

    if not webhook_url:
        return jsonify({
            "status": "not_sent",
            "reason": "SLACK_WEBHOOK_URL is not configured."
        }), 400

    current_time = time.time()
    if not force_send and (current_time - last_alert_time) <= ALERT_COOLDOWN:
        remaining = int(ALERT_COOLDOWN - (current_time - last_alert_time))
        return jsonify({
            "status": "suppressed",
            "reason": f"Slack cooldown active. Try again in {remaining}s.",
            "remaining_seconds": remaining
        })

    if not send_slack_message(message):
        return jsonify({
            "status": "not_sent",
            "reason": "Slack request failed. Check webhook URL and network."
        }), 502

    last_alert_time = current_time
    return jsonify({
        "status": "sent",
        "type": "slack",
        "message": message,
        "forced": force_send
    })


@app.route('/api/export-csv')
@require_auth
def export_csv():
    """Generates a CSV file from the metrics.db data"""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT timestamp, cpu, memory, disk FROM metrics ORDER BY timestamp DESC")
            data = cursor.fetchall()

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
@require_auth
def get_pods():
    pods, error = get_pod_health()
    return jsonify({
        "pods": pods,
        "error": error
    })

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
    
scheduler = None


def initialize_app_state():
    load_history()


def start_scheduler():
    global scheduler
    if scheduler is not None:
        return
    scheduler = BackgroundScheduler()
    scheduler.add_job(func=generate_summary_report, trigger='cron', hour=9, minute=0)
    scheduler.start()
    print("Background scheduler started.")


initialize_app_state()

if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or os.environ.get("FLASK_DEBUG", "").lower() != "true":
    start_scheduler()

if __name__ == '__main__':
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
    
    is_debug = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    port = int(os.environ.get('PORT', 5000))
    if is_debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        # Production: Gunicorn handles WSGI server
        app.run(host='0.0.0.0', port=port, debug=False)
    
