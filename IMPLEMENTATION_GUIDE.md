# Step-by-Step Implementation Guide
## Features 2, 3, 4: Multi-Metric Dashboard + Alert System + Health Checks

---

## ✅ FEATURE 2: Multi-Metric Dashboard (Disk, Network, Processes)

### Step 1: Update app.py to collect additional metrics

Replace your current `app.py` with the enhanced version that includes:

**New Metrics Added:**
1. **Disk Usage** - Shows % of disk space used
2. **Network Traffic** - Total data sent/received in GB
3. **Top Processes** - Top 5 processes by CPU and Memory

**Code Changes:**

```python
# Add these imports at the top
import psutil
from datetime import datetime
import json
import os

# Add this function to get top processes
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
    
    # Sort by CPU and Memory
    processes_by_cpu = sorted(processes, key=lambda x: x['cpu'], reverse=True)[:limit]
    processes_by_memory = sorted(processes, key=lambda x: x['memory'], reverse=True)[:limit]
    
    return {
        'by_cpu': processes_by_cpu,
        'by_memory': processes_by_memory
    }

# Update your /api/metrics endpoint
@app.route('/api/metrics')
def get_metrics():
    # Existing metrics
    cpu_metric = psutil.cpu_percent(interval=1)
    mem_metric = psutil.virtual_memory().percent
    
    # NEW: Add disk metrics
    disk_metric = psutil.disk_usage('/').percent
    
    # NEW: Add network metrics
    net_io = psutil.net_io_counters()
    network_sent_gb = round(net_io.bytes_sent / (1024**3), 2)
    network_recv_gb = round(net_io.bytes_recv / (1024**3), 2)
    
    # NEW: Get top processes
    top_processes = get_top_processes(5)
    
    return jsonify({
        'cpu': cpu_metric,
        'memory': mem_metric,
        'disk': disk_metric,  # NEW
        'network': {          # NEW
            'sent_gb': network_sent_gb,
            'recv_gb': network_recv_gb
        },
        'top_processes': top_processes,  # NEW
        'timestamp': datetime.now().isoformat()
    })
```

### Step 2: Test the new metrics

```bash
# Run your app
python3 app.py

# In another terminal, test the API
curl http://localhost:5000/api/metrics

# You should see output like:
{
  "cpu": 15.2,
  "memory": 63.5,
  "disk": 46.6,
  "network": {
    "sent_gb": 2.45,
    "recv_gb": 5.32
  },
  "top_processes": {
    "by_cpu": [
      {"pid": 1234, "name": "chrome", "cpu": 25.3, "memory": 5.2},
      ...
    ],
    "by_memory": [
      {"pid": 5678, "name": "python", "cpu": 3.1, "memory": 12.5},
      ...
    ]
  }
}
```

### Step 3: Update the frontend (index.html)

Replace your `templates/index.html` with the enhanced version that displays:
- Disk usage gauge
- Network traffic cards
- Top processes tables

**What the new UI shows:**
1. ✅ 3 Gauges: CPU, Memory, Disk
2. ✅ Network Stats: Data sent/received
3. ✅ Process Tables: Top 5 by CPU and Memory
4. ✅ Historical chart with all metrics

---

## ✅ FEATURE 3: Real Alert System

### Step 1: Add anomaly detection logic

The enhanced `app.py` already includes this. Here's how it works:

```python
def detect_anomaly(cpu, memory, disk):
    """
    AI-powered anomaly detection
    Compares current values to historical average
    """
    if len(history) < 30:
        return False, "Collecting baseline data..."
    
    # Calculate averages from last 30 data points
    avg_cpu = sum([h['cpu'] for h in history[-30:]]) / 30
    avg_memory = sum([h['memory'] for h in history[-30:]]) / 30
    
    # Detect unusual spikes
    if abs(cpu - avg_cpu) > 30:
        return True, f"⚠ Unusual CPU Spike! Current: {cpu}%, Normal: {avg_cpu:.1f}%"
    
    if abs(memory - avg_memory) > 15:
        return True, f"⚠ Unusual Memory Pattern! Current: {memory}%, Normal: {avg_memory:.1f}%"
    
    # Absolute thresholds
    if cpu > 80:
        return True, "⚠ High CPU Usage!"
    
    if memory > 85:
        return True, "⚠ High Memory Usage!"
    
    if disk > 90:
        return True, "⚠ Critical Disk Space!"
    
    return False, "✓ System Normal"
```

### Step 2: Test the alert system

**Trigger a CPU alert:**
```python
# Run this in a Python terminal to spike CPU
import multiprocessing
import time

def stress_cpu():
    while True:
        x = 0
        for i in range(10000000):
            x += i

if __name__ == '__main__':
    # This will max out your CPU cores
    processes = []
    for i in range(multiprocessing.cpu_count()):
        p = multiprocessing.Process(target=stress_cpu)
        p.start()
        processes.append(p)
    
    time.sleep(10)  # Run for 10 seconds
    
    for p in processes:
        p.terminate()
```

**Watch the dashboard:**
- The alert box will turn RED
- Message will show: "⚠ High CPU Usage Detected!"
- The box will pulse/animate

### Step 3: Add email/Slack notifications (Optional)

To send actual alerts via email or Slack:

**Option A: Email alerts**
```python
import smtplib
from email.mime.text import MIMEText

def send_email_alert(message):
    msg = MIMEText(message)
    msg['Subject'] = 'System Alert - CloudMonitor'
    msg['From'] = 'your-email@gmail.com'
    msg['To'] = 'alert-recipient@gmail.com'
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login('your-email@gmail.com', 'your-app-password')
        smtp.send_message(msg)

# Call this in detect_anomaly when alert is triggered
if is_anomaly:
    send_email_alert(alert_message)
```

**Option B: Slack webhook** (Easier, Free)
```python
import requests

def send_slack_alert(message):
    webhook_url = "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
    payload = {
        "text": f"🚨 *System Alert*\n{message}"
    }
    requests.post(webhook_url, json=payload)

# Usage
if is_anomaly:
    send_slack_alert(alert_message)
```

**Get Slack webhook:**
1. Go to https://api.slack.com/messaging/webhooks
2. Create a new app
3. Add Incoming Webhook
4. Copy webhook URL
5. Paste in your code

---

## ✅ FEATURE 4: Health Check & Readiness Endpoints

### Step 1: Add Kubernetes-compatible endpoints

Already included in enhanced `app.py`:

```python
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
        # Check if all systems are operational
        psutil.cpu_percent()
        psutil.virtual_memory()
        return jsonify({'status': 'ready'}), 200
    except Exception as e:
        return jsonify({'status': 'not ready', 'error': str(e)}), 503
```

### Step 2: Test health endpoints

```bash
# Test health check
curl http://localhost:5000/health

# Expected output:
{
  "status": "healthy",
  "timestamp": "2026-02-10T14:30:00.123456"
}

# Test readiness check
curl http://localhost:5000/ready

# Expected output:
{
  "status": "ready"
}
```

### Step 3: Update Kubernetes deployment to use health checks

Create/update your `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cloud-monitor
spec:
  replicas: 2
  selector:
    matchLabels:
      app: cloud-monitor
  template:
    metadata:
      labels:
        app: cloud-monitor
    spec:
      containers:
      - name: cloud-monitor
        image: your-dockerhub-username/cloud-monitor:latest
        ports:
        - containerPort: 5000
        
        # NEW: Add health checks
        livenessProbe:
          httpGet:
            path: /health
            port: 5000
          initialDelaySeconds: 10
          periodSeconds: 30
        
        readinessProbe:
          httpGet:
            path: /ready
            port: 5000
          initialDelaySeconds: 5
          periodSeconds: 10
```

**What this does:**
- **Liveness probe**: Kubernetes checks `/health` every 30 seconds. If it fails, pod is restarted.
- **Readiness probe**: Kubernetes checks `/ready` every 10 seconds. If it fails, pod is removed from load balancer.

---

## 🧪 TESTING ALL FEATURES

### Test Checklist:

#### ✅ Feature 2: Multi-Metric Dashboard
- [ ] Open http://localhost:5000
- [ ] Verify 3 gauges showing: CPU, Memory, Disk
- [ ] Check network stats updating (GB sent/received)
- [ ] Verify top processes table showing real processes
- [ ] Check historical chart displays all 3 metrics

#### ✅ Feature 3: Alert System
- [ ] Let app run for 5 minutes to collect baseline
- [ ] Spike CPU (open many browser tabs or run stress test)
- [ ] Alert box turns red and shows warning
- [ ] Test email/Slack notification (if configured)

#### ✅ Feature 4: Health Checks
- [ ] `curl http://localhost:5000/health` returns 200
- [ ] `curl http://localhost:5000/ready` returns 200
- [ ] Stop psutil and verify `/ready` returns 503

---

## 📦 INSTALLATION & DEPLOYMENT

### Step 1: Install dependencies

```bash
pip install flask psutil
```

### Step 2: Run the enhanced app

```bash
python3 app_enhanced.py
```

### Step 3: Access the dashboard

Open browser: http://localhost:5000

### Step 4: Build Docker image (for deployment)

```bash
# Update Dockerfile if needed
docker build -t your-username/cloud-monitor:v2 .

# Run locally
docker run -p 5000:5000 your-username/cloud-monitor:v2

# Push to Docker Hub
docker push your-username/cloud-monitor:v2
```

---

## 🎯 WHAT YOU'VE ACHIEVED

### Before (Feature 1 only):
- ✅ CPU & Memory gauges
- ✅ Historical data storage

### After (Features 1-4):
- ✅ CPU, Memory, **Disk** gauges
- ✅ **Network traffic** monitoring
- ✅ **Top processes** tracking
- ✅ Historical data with charts
- ✅ **AI-powered anomaly detection**
- ✅ **Real-time alerts** (visual + optional email/Slack)
- ✅ **Health check endpoints** for Kubernetes

---

## 🚀 NEXT STEPS (Optional Enhancements)

1. **Add more metrics**:
   - Temperature sensors
   - GPU usage (if available)
   - Container metrics (if running in Docker)

2. **Improve AI detection**:
   - Use sklearn IsolationForest for better anomaly detection
   - Train on more historical data

3. **Add user authentication**:
   - Login system
   - Role-based access

4. **Export reports**:
   - Generate PDF reports
   - CSV export of historical data

5. **Multiple servers**:
   - Monitor multiple servers from one dashboard
   - Agent-based architecture

---

## 📸 SCREENSHOTS FOR DOCUMENTATION

Take these screenshots:

1. **Dashboard with all metrics** (CPU, Memory, Disk, Network, Processes)
2. **Alert triggered** (Red alert box with message)
3. **Historical chart** (Line graph showing trends)
4. **Health check response** (Terminal showing curl output)
5. **Top processes table** (Showing real running processes)

---

## ❓ TROUBLESHOOTING

### Issue: No data in historical chart
**Solution**: Wait 1-2 minutes for data to accumulate, then refresh page

### Issue: Top processes table empty
**Solution**: Make sure psutil has permissions:
```bash
sudo pip install psutil
python3 app_enhanced.py
```

### Issue: Alert never triggers
**Solution**: 
1. Check if history has >30 data points
2. Manually spike CPU/memory to trigger threshold

### Issue: Network stats show 0 GB
**Solution**: Restart the system or wait for network activity

---

## ✅ COMPLETION CHECKLIST

- [ ] Copied app_enhanced.py to your project
- [ ] Copied index_enhanced.html to templates/
- [ ] Installed dependencies: `pip install flask psutil`
- [ ] Tested locally: `python3 app_enhanced.py`
- [ ] Verified all 3 gauges display correctly
- [ ] Network stats showing data
- [ ] Top processes table populating
- [ ] Alert system tested and working
- [ ] Health endpoints tested
- [ ] Screenshots taken for documentation
- [ ] Ready to deploy to Docker/Kubernetes

---

**Need help with any step? Ask me and I'll provide more detailed guidance!**
