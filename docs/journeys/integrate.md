# API and Python SDK integration

Use an environment **Delivery** key and the installation root URL. The key fixes
the project/environment; the request cannot select a different tenant. These
examples use the deployed `northstar-welcome` fixture from [the local example](../evaluate.md).
For an existing installation, substitute your deployed template key and its
published context contract.

## Configure a local client

The [first-email setup](../quickstart.md#load-local-credentials) loads
`VOXRIVA_URL` and `VOXRIVA_API_KEY` from protected example state without printing
the key. Production applications should obtain them from their own secret
configuration. The SDK base URL is the installation root, optionally with a
reverse-proxy path prefix, **not** `/api/v1`. HTTPS is required outside loopback.

Install the independently packaged SDK from PyPI:

```sh
python3 -m venv /tmp/voxriva-client
/tmp/voxriva-client/bin/python -m pip install voxriva-sdk==0.1.1
```

The matching wheel is also available from **API keys → Integration examples →
Download Python SDK** in the running application.

The SDK requires Python 3.10+ and HTTPX, with no server/database/provider packages.
For source development, `python -m pip install ./sdk/python` is also supported.
Use the client environment's Python for the snippets below. See
[release status](../release-status.md) for package availability and compatibility.

## Minimal runtime call

The three variants submit the **same** fixture payload with the **same** operation
key. Running them sequentially should return one notification ID, not three sends.
Keep the key/body stable across retries; use a new key for a new intended message.

=== "curl"

    ```sh
    curl --silent --show-error --fail-with-body --noproxy '*' \
      "$VOXRIVA_URL/api/v1/notifications" \
      -H "Authorization: Bearer $VOXRIVA_API_KEY" \
      -H 'Idempotency-Key: docs:welcome:001' \
      -H 'Content-Type: application/json' \
      --data-binary @docs/examples/welcome.json
    ```

=== "Python"

    ```python
    import os
    from voxriva_sdk import Client

    with Client(os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"]) as client:
        accepted = client.send(
            "northstar-welcome",
            recipient="person@example.test",
            locale="en",
            context={
                "first_name": "Taylor",
                "account_url": "https://northstar.example.test/account",
            },
            idempotency_key="docs:welcome:001",
        )
        status = client.get_notification(accepted.id)
        print(accepted.id, accepted.replayed, status.status.value)
        print(accepted.dashboard_url)
    ```

=== "Async Python"

    ```python
    import asyncio
    import os
    from voxriva_sdk import AsyncClient

    async def main():
        async with AsyncClient(os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"]) as client:
            accepted = await client.send(
                "northstar-welcome",
                recipient="person@example.test",
                locale="en",
                context={
                    "first_name": "Taylor",
                    "account_url": "https://northstar.example.test/account",
                },
                idempotency_key="docs:welcome:001",
            )
            status = await client.get_notification(accepted.id)
            print(accepted.id, accepted.replayed, status.status.value)
            print(accepted.dashboard_url)

    asyncio.run(main())
    ```

Acceptance is HTTP 202 with a relative `status_url` and `Location` header. SDK
`dashboard_url` is a human dashboard link requiring sign-in, not a public receipt.
Status may be queued/processing before it becomes Sent or another outcome.

## Validate before accepting

`client.validate(...)` and `await client.validate(...)` take the same template,
target, locale and context as `send`. The HTTP equivalent is
`POST /api/v1/notifications/validate`, with the same body and Delivery key,
without an Idempotency-Key header.

It checks current deployment/provider resolution, decryptability, target,
schema/defaults, rendering and transport-size constraints. It returns the resolved
version IDs and fallback metadata. It does not call the provider, verify live
credentials, reserve those versions, persist an ad-hoc payload or create a job.
The subsequent send resolves pointers again. Treat preflight as diagnostics,
not a transaction spanning later acceptance.

## Handle failures at the right boundary

```python
import os
from voxriva_sdk import Client, RetryPolicy, TransportError, ValidationError

operation_key = "docs:welcome:001"  # Persist with the application's operation.
with Client(
    os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"], timeout=10,
    retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.25, max_delay=30),
) as client:
    try:
        accepted = client.send(
            "northstar-welcome", recipient="person@example.test", locale="en",
            context={
                "first_name": "Taylor",
                "account_url": "https://northstar.example.test/account",
            },
            idempotency_key=operation_key,
        )
    except ValidationError as error:
        for issue in error.issues:
            print(issue.path, issue.code)
    except TransportError as error:
        assert error.idempotency_key == operation_key
        # Acceptance is uncertain. Retry later with this key and the exact body.
```

Default SDK behavior is at most three HTTP attempts for transient network errors
and HTTP 408/429/500/502/503/504, with exponential jitter. The request is encoded
once and the same key/body is used for every attempt. Retry-After is honored;
when its required wait exceeds `max_delay`, the SDK raises instead of retrying
early. A generated key survives attempts within one `send` call; recovery across
calls/process restarts requires your own stable persisted key.

HTTP 401/403/404/409/422 are not automatically retried. `ApiError` includes
`status_code`, `retryable`, `retry_after`, `attempts`, structured issues and the
send key. `ProtocolError` retains the key when an acceptance response is malformed.
Exception messages omit raw server/transport text. See the [exact HTTP failure
contract](../api.md#errors) and [delivery semantics](operate.md): an SDK HTTP retry
is different from a worker transport retry or operator replay.

## Context, locales and target selection

For email, supply `recipient`; for push, supply `device_token`. Exactly one must
be present and match the template channel. Push needs an FCM binding and real
provider/device prerequisites; see [push integration](push.md).

`locale` defaults to `en`. Locale tags are lowercased by the server, then matched
exactly through the environment/project/global chain, followed by the configured
fallback chain. There is no region truncation. See [version resolution](lifecycle.md).

Context overrides published runtime defaults at the top level. Fixtures and
schema `default` annotations do not supply runtime values. Use the
[typed template contract](email.md), [format markers](../variable-formats.md) and
[Image v1 helper/limits](../email-images.md) when extending the payload.

## Additional client behavior

`liveness()`, `readiness()` and `get_notification(id)` are read operations.
Public health calls omit the key; readiness HTTP 503 becomes a typed Unavailable
report. Redirects are refused. Default clients verify TLS and ignore proxy
environment variables. A caller-supplied HTTPX client retains lifecycle ownership
and its explicitly configured TLS/proxy/transport behavior.

The [SDK reference](../../sdk/python/README.md) lists models/errors and the
[frozen OpenAPI contract](../../contracts/delivery-v1.openapi.json) describes
runtime API compatibility. Template administration is outside that frozen SDK
surface. [MCP](../../MCP.md) provides separate scoped draft authoring, not delivery.
