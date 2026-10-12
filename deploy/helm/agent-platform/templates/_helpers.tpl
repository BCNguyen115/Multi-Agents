{{- define "agent.fullname" -}}
{{- printf "%s-%s" .Release.Name .Chart.Name | trunc 40 | trimSuffix "-" -}}
{{- end -}}

{{- define "agent.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "agent.secretName" -}}
{{- default (printf "%s-secrets" (include "agent.fullname" .)) .Values.existingSecret -}}
{{- end -}}
