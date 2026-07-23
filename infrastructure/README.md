# arenarank — Infrastructure

Production infrastructure for the FastAPI backend (proposal §10 / master plan W5).
Everything here is validated offline (no live cluster/AWS required to lint).

```
infrastructure/
  k8s/                 Kubernetes manifests (kustomize base + staging/production overlays)
    base/
      namespaces/      api / processing / data / observability (PSA labels)
      config/          ConfigMap + Secret template (+ ExternalSecret for ESO)
      api/             Deployment + Service + HPA + PDB + Ingress (ALB)
      workers/         processor pools (KEDA) + ingestion/scheduler (singleton) + ScaledObjects
    overlays/          image pin, replicas, IRSA, CORS/host per environment
  helm/arenarank/      Helm chart — the same app, parameterized (values + values-staging)
  terraform/           AWS: VPC, EKS, RDS (PG16 Multi-AZ + TimescaleDB-capable),
    modules/           ElastiCache (Redis 7), S3 (archives + lifecycle→Glacier),
    environments/      ECR, IAM (IRSA + GitHub OIDC deploy role). staging + production roots.
  observability/       Prometheus rules (§14.2) + recording rules, Grafana dashboards,
                       Loki + Tempo + OTel collector, Alertmanager, runbooks (§14.5)
```

## Topology (proposal §10.1)

```
Route53/Cloudflare → ALB → EKS
  ns api          → api Deployment (uvicorn :8000) + HPA(cpu 60%, 3→20) + ALB Ingress
  ns processing   → processor-priority / processor-standard (KEDA on Redis LLEN, 2→20)
                    ingestion (singleton poller), scheduler (singleton cron)
  ns data         → PgBouncer + exporters (RDS/ElastiCache are managed, in AWS)
  ns observability→ Prometheus, Alertmanager, Grafana, Loki, Tempo, OTel collector
AWS: RDS PG16 Multi-AZ (+ TimescaleDB), ElastiCache Redis 7, S3, ECR, IAM/IRSA
```

The backend is a **single image** (`backend/Dockerfile`); the role is chosen by the
container command: `uvicorn arena.api.app:app` (api) vs `arq arena.workers.main.<Pool>`
(workers). Health: api serves `GET /healthz`; workers use a Redis-ping exec probe.

## Deploy paths

### A) kustomize (used by CI/CD `release.yml`)
```bash
aws eks update-kubeconfig --name arenarank-prod
kubectl kustomize infrastructure/k8s/overlays/production | kubectl apply -f -
```

### B) Helm
```bash
helm upgrade --install arenarank infrastructure/helm/arenarank \
  -n api --create-namespace \
  --set image.tag=<release> \
  -f infrastructure/helm/arenarank/values.yaml          # prod
# staging: add -f infrastructure/helm/arenarank/values-staging.yaml
```

### Provision AWS (terraform)
```bash
cd infrastructure/terraform/environments/production
terraform init
terraform apply -var account_id=<acct> \
  -var rds_master_password=$RDS_PW -var redis_auth_token=$REDIS_TOKEN
```

## Prerequisites in-cluster (installed out-of-band)
- KEDA (`keda.sh`) — worker autoscaling on Redis queue depth.
- metrics-server — HPA CPU/memory.
- AWS Load Balancer Controller — the ALB Ingress.
- Prometheus Operator (kube-prometheus-stack) — ServiceMonitor/PrometheusRule CRs.
- External Secrets Operator — reconciles AWS Secrets Manager → the `arenarank-secrets` Secret.

## Validation (what was run)
- YAML: PyYAML safe_load_all on every manifest (0 failures).
- Helm: `helm lint` + `helm template` (default + staging), output re-parsed as YAML.
- Kustomize: `kubectl kustomize` for base + both overlays + observability (offline).
- Terraform: `terraform fmt -check -recursive` + `terraform validate` (staging + production).
- Prometheus: `promtool check rules` (18 rules) + `promtool check config`.
- Alertmanager: `amtool check-config`.

See `observability/runbooks/` for operational procedures (proposal §14.5).
