#!/bin/sh

set -e

# If an argument was provided, use it as the service name prefix.
# Otherwise default to "datagov-validator".
app_name=${1:-datagov-validator}

# create the secrets service if necessary. It holds only NEW_RELIC_LICENSE_KEY
# (see README.md); `cf cups` with no `-p` creates it empty.
cf service "${app_name}-secrets" > /dev/null 2>&1 || cf cups "${app_name}-secrets"
