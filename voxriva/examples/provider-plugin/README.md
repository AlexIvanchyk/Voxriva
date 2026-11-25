# Example external provider

This package registers `example_smtp` through the
`notification_platform.providers` entry-point group. It inherits the built-in SMTP
transport to demonstrate packaging without inventing a production transport.
It is not installed in the standard Voxriva image.

Install it alongside Voxriva at image-build time, then restart API and workers:

```dockerfile
ARG PYTHON_IMAGE
ARG VOXRIVA_IMAGE
FROM ${PYTHON_IMAGE} AS provider-builder
COPY examples/provider-plugin /src
RUN python -m pip install --no-deps --target /plugin /src

FROM ${VOXRIVA_IMAGE}
COPY --from=provider-builder /plugin/ /usr/local/lib/python3.13/site-packages/
```

Pass the approved runtime image as `--build-arg VOXRIVA_IMAGE=...` and the matching
Python 3.13 base digest from `build-inputs.env` as `--build-arg PYTHON_IMAGE=...`.
The production runtime omits pip/ensurepip; install trusted plugins in a build
stage and copy their package and entry-point metadata. Use this custom image for
API, relay, workers and migrations together, then repeat release scanning and smoke
checks. Plugin dependencies must also be pinned and included in the build stage.

The plugin appears in **Providers → Add provider** through registry metadata. Existing
SMTP validation, encrypted secrets, tests and channel bindings work without dashboard
changes. Use a unique key and implement `BaseProvider` interface version 1 for a new
transport. Keep configuration fields scalar and secrets `SecretStr`. Report only fixed
error codes through `ProviderError`. Set `uncertain=False` only when the transport can
prove the provider did not accept a message; otherwise the runtime records Unknown.
The durable worker owns retry policy, so disable hidden SDK message retries. Capability
flags control tests and delivery-confirmation labels; a flag alone never proves delivery.

The targeted cloud-provider tests build and install this package into a temporary Python
path, then verify that the authenticated dashboard metadata includes the installed plugin.
