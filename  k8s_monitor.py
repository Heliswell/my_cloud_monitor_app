from kubernetes import client, config

def fetch_cluster_status():
    try:
        # This looks for the local minikube config
        config.load_kube_config() 
        v1 = client.CoreV1Api()
        
        # Get all pods to show in your dashboard
        pods = v1.list_pod_for_all_namespaces(watch=False)
        return [{"name": p.metadata.name, "status": p.status.phase} for p in pods.items]
    except Exception as e:
        return f"K8s Connection Error: {e}"             