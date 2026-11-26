ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.13-slim-trixie@sha256:7249d5587b78209a006dc4a3b5340678f84ea729239193aa559962cd8c1fce50
FROM ${NODE_IMAGE} AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS frontend-notices
WORKDIR /license-tools
COPY scripts/collect-third-party.py ./
COPY scripts/licenses/ licenses/
COPY frontend/package-lock.json /frontend/package-lock.json
COPY --from=frontend /build/node_modules/ /frontend/node_modules/
RUN python collect-third-party.py npm --root /frontend --output /third-party/frontend

FROM ${PYTHON_IMAGE} AS sdk
WORKDIR /sdk
COPY sdk/python/ ./
RUN pip wheel --no-deps --wheel-dir /dist .

FROM ${PYTHON_IMAGE} AS runtime
ARG VERSION=0.1.1
ARG REVISION=unknown
LABEL org.opencontainers.image.title="Voxriva" org.opencontainers.image.version=$VERSION org.opencontainers.image.revision=$REVISION io.voxriva.own-code.license="MIT" io.voxriva.third-party-notices="/app/release-metadata/third-party"
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VOXRIVA_VERSION=$VERSION
WORKDIR /app
# Keep dependency installation cached while application code changes.
COPY requirements-runtime.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-compile -r requirements-runtime.lock setuptools==80.9.0
COPY pyproject.toml LICENSE THIRD_PARTY_NOTICES.md ./
COPY backend/ backend/
COPY scripts/collect-third-party.py /license-tools/
COPY scripts/licenses/ /license-tools/licenses/
RUN pip install --no-cache-dir --no-compile --no-build-isolation --no-deps . \
    && mkdir -p /app/release-metadata \
    && pip freeze --all > /app/release-metadata/python-resolved.txt \
    && pip inspect > /app/release-metadata/python-packages.json \
    && python /license-tools/collect-third-party.py python --requirements requirements-runtime.lock \
        --base-runtime --output /app/release-metadata/third-party/python \
    && pip uninstall -y pip setuptools \
    && rm -rf /usr/local/lib/python3.13/ensurepip /license-tools \
    && useradd --uid 10001 --create-home voxriva
# Use the renderer preparation verified in Dockerfile.mcp. Explicit compilation
# includes its stdlib import graph and preserves the existing sandbox CPU limit.
RUN python -c "import sys, py_compile; from backend.app.features.templates.rendering import DraftContent, _render; from backend.app.features.templates.authoring import diagnostics; draft=DraftContent(subject='Synthetic',text='Synthetic'); diagnostics('email',draft.model_dump()); _render('email',draft,{}); [py_compile.compile(path,doraise=True) for module in list(sys.modules.values()) if isinstance(path:=getattr(module,'__file__',None),str) and path.endswith('.py')]"
COPY alembic.ini ./
COPY migrations/ migrations/
COPY --from=frontend /build/dist/ frontend/dist/
COPY --from=frontend-notices /third-party/frontend/ /app/release-metadata/third-party/frontend/
COPY --from=sdk /dist/voxriva_sdk-0.1.1-py3-none-any.whl frontend/dist/downloads/
COPY contracts/delivery-v1.openapi.json frontend/dist/downloads/
USER 10001
EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
