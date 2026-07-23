{{/*
Common helpers for the arenarank chart.
*/}}

{{- define "arenarank.name" -}}
arenarank
{{- end -}}

{{/* Standard labels applied to every object. */}}
{{- define "arenarank.labels" -}}
app.kubernetes.io/part-of: arenarank
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{/* Fully-qualified image reference. */}}
{{- define "arenarank.image" -}}
{{ .Values.image.repository }}:{{ .Values.image.tag }}
{{- end -}}

{{/*
Pod-level securityContext shared by api + workers (restricted PSA).
*/}}
{{- define "arenarank.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{/* Container-level securityContext (read-only rootfs, drop caps). */}}
{{- define "arenarank.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* envFrom block referencing the shared ConfigMap + Secret. */}}
{{- define "arenarank.envFrom" -}}
- configMapRef:
    name: arenarank-config
- secretRef:
    name: arenarank-secrets
{{- end -}}

{{/* Redis-ping liveness exec for arq workers (no HTTP server). */}}
{{- define "arenarank.workerLiveness" -}}
exec:
  command:
    - python
    - -c
    - "import os,redis; redis.from_url(os.environ['REDIS_URL']).ping()"
initialDelaySeconds: 15
periodSeconds: 30
timeoutSeconds: 5
failureThreshold: 3
{{- end -}}
