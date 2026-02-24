SHELL := /bin/bash

IMAGE ?= cloud-monitor:v1
DEPLOYMENT ?= cloud-monitor
SERVICE ?= cloud-monitor-svc
NAMESPACE ?= default
TIMEOUT ?= 180s

.PHONY: help demo-start demo-image demo-secret demo-apply demo-wait demo-init demo-refresh demo-recreate demo-status demo-logs demo-url demo-clean

help:
	@echo "Local K8s Demo Targets"
	@echo "  make demo-init      # One-time setup: start minikube, load image, create secret, apply manifests, wait rollout"
	@echo "  make demo-refresh   # Fast demo refresh: start minikube, load image, rollout restart, wait"
	@echo "  make demo-recreate  # Delete and recreate deployment (use when selector/immutable field changed)"
	@echo "  make demo-status    # Show pods/service/endpoints"
	@echo "  make demo-logs      # Tail app logs"
	@echo "  make demo-url       # Print service URL"
	@echo "  make demo-clean     # Remove service/deployment/rbac resources"
	@echo ""
	@echo "Variables you can override:"
	@echo "  IMAGE=$(IMAGE)"
	@echo "  DEPLOYMENT=$(DEPLOYMENT)"
	@echo "  SERVICE=$(SERVICE)"
	@echo "  NAMESPACE=$(NAMESPACE)"
	@echo "  TIMEOUT=$(TIMEOUT)"

demo-start:
	minikube start

demo-image:
	minikube image load $(IMAGE)

demo-secret:
	@if [ ! -f .env ]; then echo ".env not found in project root"; exit 1; fi
	kubectl create secret generic cloud-monitor-secrets \
		--from-env-file=.env \
		--dry-run=client -o yaml | kubectl apply -f -

demo-apply:
	kubectl apply -f k8s-permissions.yaml
	kubectl apply -f deployment.yaml
	kubectl apply -f service.yaml

demo-wait:
	kubectl rollout status deployment/$(DEPLOYMENT) -n $(NAMESPACE) --timeout=$(TIMEOUT)

demo-init: demo-start demo-image demo-secret demo-apply demo-wait
	@echo "Demo environment is ready."
	@$(MAKE) demo-url

demo-refresh: demo-start demo-image
	kubectl rollout restart deployment/$(DEPLOYMENT) -n $(NAMESPACE)
	$(MAKE) demo-wait
	@echo "Demo rollout refreshed."
	@$(MAKE) demo-url

demo-recreate: demo-start demo-image
	kubectl delete deployment/$(DEPLOYMENT) -n $(NAMESPACE) --ignore-not-found=true
	$(MAKE) demo-secret
	$(MAKE) demo-apply
	$(MAKE) demo-wait
	@echo "Deployment recreated."
	@$(MAKE) demo-url

demo-status:
	kubectl get pods -n $(NAMESPACE) -o wide
	kubectl get svc $(SERVICE) -n $(NAMESPACE)
	kubectl get endpoints $(SERVICE) -n $(NAMESPACE)

demo-logs:
	kubectl logs -f deployment/$(DEPLOYMENT) -n $(NAMESPACE)

demo-url:
	minikube service $(SERVICE) -n $(NAMESPACE) --url

demo-clean:
	kubectl delete -f service.yaml --ignore-not-found=true
	kubectl delete -f deployment.yaml --ignore-not-found=true
	kubectl delete -f k8s-permissions.yaml --ignore-not-found=true
