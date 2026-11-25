# Push integration (FCM)

Push uses the same acceptance, environment idempotency, version pinning and
history contracts as email. Replace `recipient` with `device_token`, supply a
published/deployed push template and bind an FCM provider revision for the target
environment. The push worker consumes a separate channel queue.

## External prerequisites

A live FCM request needs a Firebase project, a real registration token and
credentials with `cloudmessaging.messages.create` in that project. Configure
encrypted service-account JSON or workload credentials (Google Application
Default Credentials) available to the API and push worker. The standard image
contains no cloud keys. Caller-supplied non-Google auth endpoints are rejected.

Connection testing obtains an OAuth token without proving send permission.
Provider test-push defaults to `validate_only: true`; selecting actual delivery
is an explicit external send. These provider tests do not create queued runtime
notification history. Local transport doubles cover request/error contracts,
not live device receipt. The isolated first-email example has no FCM binding.

## Request contract

Use your actual deployed push key and token; `order-ready` below is an example
contract requiring `order_id`, not a preconfigured first-email fixture.

```python
import os
from voxriva_sdk import Client

with Client(os.environ["VOXRIVA_URL"], os.environ["VOXRIVA_API_KEY"]) as client:
    payload = {"order_id": "example-42"}
    client.validate(
        "order-ready", device_token=os.environ["FCM_TEST_DEVICE_TOKEN"],
        locale="en", context=payload,
    )
    accepted = client.send(
        "order-ready", device_token=os.environ["FCM_TEST_DEVICE_TOKEN"],
        locale="en", context=payload, idempotency_key="order-ready:example-42",
    )
    print(accepted.id, client.get_notification(accepted.id).status.value)
```

Exactly one target is required, matching the template channel. Push title/body
must be nonempty and data values render as strings. The entire serialized FCM
request must fit 4096 bytes, including token and envelope. A displayed body-byte
count alone is insufficient. Tokens are encrypted in runtime storage and hidden
from history, audit and metrics.

## Outcome handling

Sent means FCM accepted the request, not that a device received/displayed it.
There is no trusted per-message FCM receipt webhook in this implementation, so
it never synthesizes Delivered/Bounced. Permanent unregistration fails without
retry; replace the token in your application. Quota/temporary responses honor
provider retry guidance; ambiguous acceptance becomes Unknown. Replay after
runtime expiry requires a fresh target and explicit context. See
[delivery semantics](operate.md) and [FCM provider details](../delivery-guide.md#firebase-cloud-messaging).
