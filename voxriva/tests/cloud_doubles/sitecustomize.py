"""TEST ONLY: mounted into the isolated cloud-contract Compose stack, never the image."""

import os
from contextlib import contextmanager
from pathlib import Path

if os.environ.get("VOXRIVA_CLOUD_TEST_DOUBLES") == "1":
    from uuid import uuid4

    import httpx

    from backend.app.features.providers.adapters.fcm import FCMProvider
    from backend.app.features.providers.adapters.ses import SESProvider

    class FakeSES:
        def get_account(self):
            return {"SendingEnabled": True}

        def send_email(self, **kwargs):
            return {"MessageId": "local-ses-" + uuid4().hex}

        def close(self):
            pass

    SESProvider.client = lambda self, service="sesv2": FakeSES()
    FCMProvider.access_token = lambda self: "local-test-oauth"
    original_client = httpx.Client

    def respond(request):
        if (
            str(request.url)
            == "https://sns.eu-west-1.amazonaws.com/SimpleNotificationService-voxrivaE2E.pem"
            and request.method == "GET"
        ):
            return httpx.Response(
                200,
                content=Path("/sns-signing-cert.pem").read_bytes(),
                headers={"Content-Type": "application/x-pem-file"},
            )
        if request.url.host != "fcm.googleapis.com":
            raise RuntimeError(
                "The cloud test transport only accepts FCM and the fixed SNS signing certificate"
            )
        return httpx.Response(
            200, json={"name": "projects/firebase-demo/messages/local-" + uuid4().hex}
        )

    def test_client(**kwargs):
        return original_client(**kwargs, transport=httpx.MockTransport(respond))

    httpx.Client = test_client

    @contextmanager
    def test_stream(
        method, url, *, timeout=3, follow_redirects=False, trust_env=False, **kwargs
    ):
        # Mock only the remote certificate fetch. The application still validates
        # the SNS URL, certificate lifetime and actual cryptographic signature.
        with original_client(
            transport=httpx.MockTransport(respond),
            timeout=timeout,
            follow_redirects=follow_redirects,
            trust_env=trust_env,
        ) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    httpx.stream = test_stream
