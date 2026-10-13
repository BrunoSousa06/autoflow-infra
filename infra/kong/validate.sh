#!/bin/sh
set -eu

chart_version="3.4.1"
release_name="kong"
namespace="kong"

helm repo add kong https://charts.konghq.com --force-update
helm repo update kong
helm pull "kong/kong" --version "$chart_version" --untar --untardir /tmp/kong-charts
chart_path="/tmp/kong-charts/kong"
helm lint "$chart_path" --strict --values values.yaml

rendered="$(helm template "$release_name" "$chart_path" \
  --namespace "$namespace" \
  --include-crds \
  --values values.yaml)"

assert_rendered() {
  if ! printf '%s\n' "$rendered" | grep -F "$1" >/dev/null; then
    echo "Expected rendered chart to contain: $1" >&2
    exit 1
  fi
}

assert_rendered 'image: kong:3.9.3@sha256:92035d16d7ff86b7bc12fb1d0090d29357d924238b1880f78735f3f2fea6b631'
assert_rendered 'image: kong/kubernetes-ingress-controller:3.5.13@sha256:979f12864a13031545d58623d17af7a071b417396fbb3928a169d897b056b68f'
assert_rendered 'value: "bundled,aws-lambda"'
assert_rendered 'name: kongplugins.configuration.konghq.com'
assert_rendered 'name: KONG_DATABASE'
assert_rendered 'value: "off"'
assert_rendered 'type: ClusterIP'

plugin_crd="$(printf '%s\n' "$rendered" | awk '
  /name: kongplugins\.configuration\.konghq\.com$/ { in_plugin_crd = 1 }
  in_plugin_crd { print }
  in_plugin_crd && /^---$/ { exit }
')"
if ! printf '%s\n' "$plugin_crd" | grep -F 'configFrom:' >/dev/null; then
  echo "Rendered KongPlugin CRD lacks configFrom" >&2
  exit 1
fi

if printf '%s\n' "$rendered" | grep -E 'name: kong-kong-(admin|manager|portal|portalapi)$' >/dev/null; then
  echo "Unexpected Admin API or Enterprise UI Service in rendered chart" >&2
  exit 1
fi
