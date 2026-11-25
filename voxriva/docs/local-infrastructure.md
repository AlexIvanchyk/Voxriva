# Local infrastructure

Commands run from `voxriva/`. Use [PRODUCTION.md](../PRODUCTION.md) for coordinated
database/keyring backup, install, restore and upgrades.

## System health and infrastructure

Compose includes the API, PostgreSQL, Redis, one-shot migration and credential-key setup jobs,
a local Mailpit inbox and an isolated collector. PostgreSQL data persists in a volume. The collector is the only service with
Docker socket access, runs without network and writes an allowlisted project snapshot
to a volume read-only for the API. A socket provides privileged daemon access even with
a read-only mount. For custom sockets, set `VOXRIVA_DOCKER_SOCKET`.

Container monitoring is enabled by default. Set
`VOXRIVA_CONTAINER_MONITORING_ENABLED=false` on the API and collector to disable it
(`true` re-enables it; restart the affected processes after changing the setting).
The API returns `monitoring: {"status": "disabled", "snapshot": null}` without reading
snapshot files, and the collector exits successfully before inspecting Docker or
writing snapshots. Existing snapshots are ignored. **System Health** displays an
informational disabled message; API liveness and dependency readiness checks remain active.

For Kubernetes or other deployments without container inspection permissions, set this
variable to `"false"` on the API and omit the collector workload and its socket/snapshot
mounts. No Kubernetes API or container runtime permissions are needed for readiness checks.
For Compose on a host without Docker socket access, also scale the collector to zero
so Compose does not attempt its socket mount before Python starts:

```sh
export VOXRIVA_CONTAINER_MONITORING_ENABLED=false
docker compose up -d --scale collector=0
```

Keep that scale option on subsequent Compose starts while monitoring is disabled.
To restore monitoring, set the variable to `true` and run
`docker compose up -d --scale collector=1` with a valid Docker socket.

**System Health** shows container lifecycle, configured health, restart count and last
observation. Migration success appears as **Completed**. The collector and dashboard
poll every three seconds; snapshots become stale after twelve seconds. Dependency probes
remain distinct from container health. Exercise the real state transitions with:

```sh
docker compose stop redis
docker compose start redis
docker compose stop collector
docker compose start collector
```

`/health/live` remains live during a dependency failure; `/health/ready` returns unavailable.
The open dashboard retains its last snapshot marked stale if API connectivity is lost.
Reloading a stopped API's dashboard requires the API to recover. `docker compose down`
preserves data; `docker compose down --volumes` erases this local database and snapshots.

