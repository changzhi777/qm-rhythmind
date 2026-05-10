{{/*
Expand the name of the chart.
*/}}
{{- define "rhythmind.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "rhythmind.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "rhythmind.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "rhythmind.labels" -}}
helm.sh/chart: {{ include "rhythmind.chart" . }}
{{ include "rhythmind.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "rhythmind.selectorLabels" -}}
app.kubernetes.io/name: {{ include "rhythmind.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "rhythmind.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "rhythmind.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{/*
Resolve the image tag — Values.image.tag wins, else .Chart.AppVersion.
*/}}
{{- define "rhythmind.imageTag" -}}
{{- default .Chart.AppVersion .Values.image.tag }}
{{- end }}
