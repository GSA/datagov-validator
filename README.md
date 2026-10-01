# datagov-validator

A small REST API that validates [DCAT-US](https://resources.data.gov/resources/dcat-us3/) catalogs against the DCAT-US 1.1 (federal / non-federal dataset) and DCAT-US 3.0 (catalog) JSON Schemas.

It has no database and no authentication. Its one job is the validation that used to live inside [GSA/datagov-harvester](https://github.com/GSA/datagov-harvester); the harvester's `/validate/` page now calls this service, and `harvest.data.gov/api/v1/validate` is forwarded here by the harvester's proxy.

## API

Interactive docs are served at `/docs` (OpenAPI spec at `/openapi.json`).

### `POST /api/v1/validate`

`/api/validate` redirects (308) to the latest version. Callers should pin to `/api/v1/validate`.

Request body (`application/json`):

| field | required | values |
| --- | --- | --- |
| `schema` | yes | `dcatus1.1: federal dataset`, `dcatus1.1: non-federal dataset`, `dcatus3.0 catalog` |
| `fetch_method` | yes | `url` (the service fetches the catalog) or `paste` (the catalog is in `json_text`) |
| `url` | when `fetch_method` is `url` | an `http`/`https` URL that returns `application/json` |
| `json_text` | when `fetch_method` is `paste` | the catalog document, as a string |

```sh
curl -s -X POST https://validator-dev.data.gov/api/v1/validate \
  -H 'Content-Type: application/json' \
  -d '{"schema": "dcatus3.0 catalog", "fetch_method": "url", "url": "https://example.gov/data.json"}'
```

Responses:

| status | body | meaning |
| --- | --- | --- |
| 200 | `{"validation_errors": [[identifier, message], ...]}` | Validation ran. An empty list means the catalog is valid. For 1.1, `identifier` is the dataset's `identifier`, or its position in `dataset` (an integer) when it has none. For 3.0 it is `""`, and the message starts with the JSON path instead (`$.dataset[0], ...`). |
| 400 | `{"error": "..."}` | The submission was refused: the URL couldn't be fetched (bad scheme, private/internal address, timeout, too many redirects, not JSON), the document is over 10MB, or the pasted JSON doesn't parse (reported by line and column). The message is safe to show to the person who submitted it. |
| 413 | `{"error": "..."}` | The request body is too large. |
| 422 | `{"error": "..."}` | The catalog is nested too deeply to walk. |
| 422 | `{"message": "Validation error", "detail": {...}}` | The request itself is invalid (missing or unknown fields). |
| 500 | `{"error": "..."}` | Something unexpected failed. Details are logged, not returned. |

### Limits

- Documents are limited to 10MB, whether fetched or pasted. The request body may be up to 20MB, so a pasted 10MB document still fits once JSON escaping is added.
- URL fetches get one 10 second budget, including redirects (at most 5). Every redirect target is re-checked.
- URLs that resolve to private, loopback, link-local, reserved or multicast addresses are refused. Set `ALLOW_PRIVATE_ADDRESSES=true` to allow them in local development only.

### `GET /health`

Returns `{"status": "ok"}`. Cloud Foundry's health check uses it.

## Local development

The DCAT-US 3.0 schemas come from the [GSA/dcat-us](https://github.com/GSA/dcat-us) git submodule at `_external/dcat-us`, so clone with submodules:

```sh
git clone --recurse-submodules git@github.com:GSA/datagov-validator.git
# or, in an existing clone
git submodule update --init _external/dcat-us
```

Keep the submodule pinned to the same commit as datagov-harvester's, so this service accepts and rejects the same records a harvest does.

With Poetry:

```sh
poetry install
make run      # http://localhost:8081, private fetch targets allowed
make test
make lint-check
```

With Docker:

```sh
cp .env.sample .env
make up       # http://localhost:8081
```

To use it from a local datagov-harvester, point that app's `VALIDATOR_API_URL` at `http://localhost:8081/api/v1/validate`.

## Code shared with datagov-harvester

`app/validation.py` (error-message formatting and schema loading), `app/fetch.py` (the URL fetcher and its SSRF guards) and `schemas/dcatus1.1/` are copied from datagov-harvester. The harvester still uses its own copy of the error formatter to write harvest job errors. If you change the formatting in one repo, change it in the other too, or the validator and a harvest job will describe the same bad record differently. A shared package is the planned fix.

## Deployment

Deployed to cloud.gov as `datagov-validator` (see `manifest.yml` and `vars.<space>.yml`):

| space | public route | internal route |
| --- | --- | --- |
| development | validator-dev.data.gov | datagov-validator-dev.apps.internal |
| staging | validator-staging.data.gov | datagov-validator-staging.apps.internal |
| prod | validator.data.gov | datagov-validator-prod.apps.internal |

The public routes need their domains (and CDN/WAF, if any) set up in each space before the first deploy.

One-time setup per space:

```sh
./create_cloudgov_services.sh
cf uups datagov-validator-secrets -p '{"NEW_RELIC_LICENSE_KEY": "..."}'
```

URL submissions are fetched server-side, so the app needs outbound internet access. Bind the space's egress proxy the same way the harvester does (`proxy_url`).

GitHub Actions deploys `develop` to development and `main` to staging, then prod. The workflows need `CF_SERVICE_USER`/`CF_SERVICE_AUTH` secrets in the `development`, `staging` and `prod` environments.

datagov-harvester's release workflow adds the network policies that let `datagov-harvest` and `datagov-harvest-proxy` reach this app on port 61443, so deploy this app to a space before that harvester release.

## Public domain

This project is in the worldwide [public domain](LICENSE.md).
