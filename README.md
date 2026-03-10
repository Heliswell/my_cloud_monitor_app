# ☁️ Cloud-Native System Monitor & AI Reporter

A robust Python-based monitoring dashboard designed for local and Kubernetes environments. It features real-time metrics, AI anomaly detection, and automated reporting.

![Cloud Native Dashboard](images/dashboard.png)

## 🚀 Key Features
* **Real-time Monitoring**: Tracks CPU, RAM, Disk, and Network I/O.
* **AI Anomaly Detection**: Uses historical baselines to detect and alert on unusual resource spikes.
* **Automated Reporting**: Scheduled daily/weekly summaries sent via Gmail SMTP.
* **Health Check API**: Includes `/health` and `/ready` endpoints for Kubernetes probes.
* **Data Persistence**: Local SQLite database for historical analysis and CSV exports.

## 🛠️ Tech Stack
* **Backend**: Flask, Psutil, APScheduler
* **Database**: SQLite3
* **DevOps**: Docker, Kubernetes (Minikube/EKS), Slack Webhooks

## 📥 Local Setup
1. Clone the repo: `git clone <your-repo-link>`
2. Create venv: `python3 -m venv venv`
3. Install dependencies: `pip install -r requirements.txt`
4. Setup `.env` using `.env.example`
   - Add dashboard auth credentials to enable Basic Auth:
   - `AUTH_ENABLED=true`
   - `DASHBOARD_USERNAME=admin`
   - `DASHBOARD_PASSWORD=change-me`
5. Run: `python app.py`

## ☸️ Local Kubernetes (Minikube)
Use this flow to test pod-health and in-cluster Kubernetes API access locally before EC2.

1. Start Minikube:
`minikube start`

2. Build image into Minikube Docker daemon:
`eval $(minikube -p minikube docker-env)`
`docker build -t cloud-monitor:v1 .`

3. Create/update runtime secret from `.env`:
`kubectl create secret generic cloud-monitor-secrets --from-env-file=.env --dry-run=client -o yaml | kubectl apply -f -`

4. Apply RBAC + deployment + service:
`kubectl apply -f k8s-permissions.yaml`
`kubectl apply -f deployment.yaml`
`kubectl apply -f service.yaml`

5. Verify rollout:
`kubectl get pods -w`
`kubectl logs -f deployment/cloud-monitor`

6. Open app URL:
`minikube service cloud-monitor-svc --url`

7. Verify Kubernetes feature:
Open `<minikube-url>/api/pods` and confirm JSON has `pods` (or clear `error` if cluster API/RBAC issue).
