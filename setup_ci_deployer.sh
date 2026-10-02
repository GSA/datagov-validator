#!/bin/sh
set -u

# One-time (or re-run anytime) setup of this app's CI deploy credentials.
#
# Each cloud.gov space (development, staging, prod) already has a shared
# `ci-deployer` service account (cloud-gov-service-account / space-deployer
# plan) used by every data.gov app's GitHub Actions in that space - see
# GSA/data.gov SYSTEMS.md. This script creates it if it's somehow missing,
# then creates (or reuses) a service key scoped to this app, and writes the
# resulting username/password to a chmod-600 file per space for someone
# with admin on this repo to paste into Settings > Environments - matching
# what GSA/datagov-harvester's docs/developer.md documents doing by hand.
#
# This does not touch GitHub itself: setting environment secrets requires
# repo admin, which may not be available to whoever runs this.
#
# Requires: cf (logged in: `cf login -a https://api.fr.cloud.gov --sso`), jq.

cf_org="gsa-datagov"
app_name="datagov-validator"
key_name="${app_name}-deployer"
spaces="development staging prod"

for cmd in cf jq; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "Missing required command: $cmd" >&2
    exit 1
  }
done

cf target >/dev/null 2>&1 || {
  echo "Not logged in to cf. Run: cf login -a https://api.fr.cloud.gov --sso" >&2
  exit 1
}

overall_status=0

for space in $spaces; do
  echo "== ${space} =="

  if ! cf target -o "$cf_org" -s "$space" >/dev/null 2>&1; then
    echo "FAILED: could not target org ${cf_org} / space ${space} (do you have access?)" >&2
    overall_status=1
    continue
  fi

  if cf service ci-deployer >/dev/null 2>&1; then
    echo "ci-deployer service account already exists in ${space}"
  else
    echo "Creating ci-deployer service account in ${space}..."
    if ! cf create-service cloud-gov-service-account space-deployer ci-deployer; then
      echo "FAILED: could not create ci-deployer in ${space}" >&2
      overall_status=1
      continue
    fi

    ready=0
    for _ in $(seq 1 30); do
      status_line=$(cf service ci-deployer 2>/dev/null | grep -i "status:")
      case "$status_line" in
      *succeeded*)
        ready=1
        break
        ;;
      *failed*)
        break
        ;;
      esac
      sleep 5
    done
    if [ "$ready" != "1" ]; then
      echo "FAILED: ci-deployer did not finish provisioning in ${space}" >&2
      overall_status=1
      continue
    fi
  fi

  if cf service-keys ci-deployer 2>/dev/null | grep -qx "$key_name"; then
    echo "Service key ${key_name} already exists in ${space}"
  else
    echo "Creating service key ${key_name} in ${space}..."
    if ! cf create-service-key ci-deployer "$key_name"; then
      echo "FAILED: could not create service key in ${space}" >&2
      overall_status=1
      continue
    fi
  fi

  creds_json=$(cf service-key ci-deployer "$key_name" 2>/dev/null | sed -n '/^{/,$p')
  username=$(printf '%s' "$creds_json" | jq -r '.credentials.username // empty')
  password=$(printf '%s' "$creds_json" | jq -r '.credentials.password // empty')

  if [ -z "$username" ] || [ -z "$password" ]; then
    echo "FAILED: could not read credentials for ${key_name} in ${space}" >&2
    overall_status=1
    continue
  fi

  out_file=$(mktemp "/tmp/${app_name}-${space}-deployer.XXXXXX")
  chmod 600 "$out_file"
  {
    echo "CF_SERVICE_USER=${username}"
    echo "CF_SERVICE_AUTH=${password}"
  } >"$out_file"
  echo "Wrote credentials for ${space} to ${out_file} (chmod 600)."
  echo "  Hand this to someone with admin on GSA/datagov-validator to paste into"
  echo "  Settings > Environments > ${space} > Add secret (create the environment"
  echo "  first if it doesn't exist), then delete the file."
done

exit "$overall_status"
