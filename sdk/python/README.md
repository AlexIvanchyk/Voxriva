# Voxriva Python SDK

Typed synchronous and asynchronous clients for the Voxriva delivery API. Python 3.10+;
the only direct runtime dependency is HTTPX. No server, database, Celery, AWS or Firebase
packages are installed. `py.typed` is included.

Install from PyPI:

```bash
python -m pip install voxriva-sdk==0.1.1
```

The same version is also bundled with the application under **API keys →
Integration examples → Download Python SDK**. For local development, run
`python -m pip install ./sdk/python` from the Voxriva repository.

For runnable requests against the prepared local fixture, use
[API/SDK integration](https://alexivanchyk.github.io/Voxriva/journeys/integrate/). The reference below uses
an illustrative `welcome` contract with a required `name`; adapt it to your
published schema rather than assuming that template is preconfigured.

## Send an email

Create an environment API key, publish/connect an email template, deploy its version to
that environment, and bind an email provider. Use environment variables for credentials:

```python
import os
from voxriva_sdk import Client

with Client(os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"]) as client:
    client.validate("welcome", recipient="person@example.test", context={"name": "Ada"})
    accepted = client.send(
        "welcome", recipient="person@example.test", context={"name": "Ada"},
        idempotency_key="welcome:customer-123",  # persist this business-operation key
    )
    print(accepted.id, accepted.dashboard_url)
    delivery = client.get_notification(accepted.id)
    print(delivery.status.value)
```

`validate` checks the current deployed template/provider, locale fallback, runtime schema,
rendered content and target. It creates no notification, outbox row or audit action and
makes no provider/broker call. It does not prove remote credentials or reserve deployments;
a later send resolves and pins the versions active when it is accepted.

## Async and push

```python
import asyncio
import os
from voxriva_sdk import AsyncClient

async def main():
    async with AsyncClient(os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"]) as client:
        accepted = await client.send(
            "order-push", device_token=os.environ["FCM_DEVICE_TOKEN"],
            context={"order_id": "123"}, idempotency_key="order:123:push",
        )
        print(accepted.dashboard_url)
        print((await client.get_notification(accepted.id)).status.value)

asyncio.run(main())
```

Supply exactly one `recipient` or `device_token`, matching the template channel. Context
is runtime data; preview examples never substitute missing values. The key determines the
project/environment: do not send project IDs from another environment. Response models
contain masked delivery targets, pinned revisions, attempts and verified provider events.

## Retry and error handling

```python
from voxriva_sdk import Client, RetryPolicy, ValidationError, TransportError

# timeout is seconds per HTTPX operation; an httpx.Timeout is also accepted.
client = Client("http://localhost:8080", "<environment-key>", timeout=10,
                retry_policy=RetryPolicy(max_attempts=3, initial_delay=0.25, max_delay=30))
try:
    result = client.send("welcome", recipient="person@example.test", context={"name": "Ada"},
                         idempotency_key="welcome:customer-123")
except ValidationError as error:
    for issue in error.issues:
        print(issue.path, issue.code)
except TransportError as error:
    # Acceptance may already have happened. Persist/reuse error.idempotency_key and
    # the same request body on a later retry; never generate a replacement key here.
    print("Could not confirm acceptance")
finally:
    client.close()
```

At most three HTTP attempts by default, with exponential jitter. Network transport
failures and HTTP 408/429/500/502/503/504 may be retried. A send generates its key once
per method call (or uses your explicit key), encodes its body once, and reuses both on
every attempt. It never automatically starts a second notification after Failed/Unknown.
Repeating a business operation across calls/processes requires the same explicit key and
payload. Successful Accepted models and send exceptions expose `idempotency_key`.

Retry-After seconds and HTTP dates are honored. If a required wait exceeds `max_delay`,
the SDK raises the typed API error immediately instead of shortening that wait. Permanent
errors, including conflict 409 and validation 422, are not retried. The SDK does not log
keys, bodies or raw HTTP errors, and exception messages omit raw server response text.
Validation issues remain available as structured data. Redirects are never followed,
even with a supplied HTTPX client. The base URL is the installation root (optionally with
a reverse-proxy path prefix), not `/api/v1`; it cannot contain credentials/query/fragment.

Errors derive from `VoxrivaError`: `InputError`, `ProtocolError`, `TransportError`, and
`ApiError` with `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`,
`ConflictError`, `ValidationError`, `RateLimitError`, `ServiceUnavailableError`.
`ApiError` exposes `status_code`, `retryable`, `retry_after`, `attempts`, `issues` and the
send key. `ProtocolError` also retains the key if an acceptance response was malformed.

`client.liveness()` and `client.readiness()` use public health endpoints without the
API key. Readiness HTTP 503 returns a typed `status="unavailable"` report. Health methods
and read-only validation/status requests can be retried safely. Both clients support
context managers. If you supply an existing `httpx.Client`/`httpx.AsyncClient`, the SDK
does not close it; configure its TLS/proxy/transport explicitly. Default clients verify
TLS, ignore proxy environment variables and use bounded timeouts.

`Sent` confirms provider acceptance. `Delivered`/`Bounced` require verified provider events;
FCM Sent does not prove device receipt. Check notification status without sending again.
The authenticated dashboard URL is for a human signed into Voxriva, not a public status URL.

The frozen delivery v1 OpenAPI contract is bundled with the server source in
`contracts/delivery-v1.openapi.json`. Additive response fields are ignored by the SDK;
required field types and the current status set are validated.

### Phone context values

For a variable declared with `{"type":"string","format":"phone","x-voxriva-phone-version":1}`,
send E.164 text such as `context={"phone": "+12025550123"}`. National numbers, spaces
and extensions are rejected. No country is guessed and no value is normalized.
`Client.validate` / `AsyncClient.validate` use the same server rules as acceptance;
phone validity does not verify ownership or send an SMS. No client dependency is
needed. See [variable format rules](https://alexivanchyk.github.io/Voxriva/variable-formats/).

## Image values

Use `image_from_bytes(content: bytes, media_type: str)` in a context field declared as Image v1. It accepts PNG, JPEG or WebP up to 256 KiB; the server decodes and validates format/dimensions. See [the full image contract and examples](https://alexivanchyk.github.io/Voxriva/email-images/). Omit the field to use an explicit published runtime default. Synthetic fixtures never fill delivery context.

## License and distribution

The SDK own code uses [MIT](https://github.com/AlexIvanchyk/Voxriva/blob/main/sdk/python/LICENSE), attributed to Voxriva contributors. HTTPX
and its transitive dependencies retain their own upstream terms. See the server
source [third-party notices](https://github.com/AlexIvanchyk/Voxriva/blob/main/THIRD_PARTY_NOTICES.md) for redistribution
requirements. [Release status](https://alexivanchyk.github.io/Voxriva/release-status/) is the current
reference for package availability, platform scope and compatibility.
