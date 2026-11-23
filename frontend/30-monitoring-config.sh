#!/bin/sh
set -eu

# These are public destinations. Emit only characters safe in a JSON string.
public_url() {
    case "$1" in
        http://*|https://*) ;;
        *) return 0 ;;
    esac
    allowed=$(printf '%s' "$1" | LC_ALL=C tr -cd 'A-Za-z0-9:/.%_~?=&#+;,-')
    if [ "$allowed" = "$1" ]; then
        printf '%s' "$allowed"
    fi
}

grafana=$(public_url "${OPSBRIDGE_GRAFANA_URL:-}")
prometheus=$(public_url "${OPSBRIDGE_PROMETHEUS_URL:-}")
printf '{"grafana":"%s","prometheus":"%s"}\n' "$grafana" "$prometheus" > /usr/share/nginx/html/opsbridge-monitoring.json
