# N0JCG-ROC development and deployment playbook

This project adapts the workspace-level `DEVELOPMENT_DEPLOYMENT_PLAYBOOK.md`
to the Ubuntu ROC server. The original Pluto-specific firmware, IIO, lighttpd,
ARM, and Docker procedures do not apply here. Its development guardrails,
checked-in scripting, layered validation, credential handling, ownership, and
rollback rules do apply.

## Application model

1. The dependency-free browser files live in `web/`.
2. The standard-library Python service owns the ROC API and static delivery.
3. systemd owns the persistent server process.
4. Future RF adapters own their specific USB/audio/SDR device and expose
   normalized status to the ROC.
5. Host-side scripts perform preflight, deployment, installation, validation,
   and narrowly scoped removal.

The ROC is a coordinator and UI. It does not directly claim every remote RF
device, and a receive-only adapter must contain no transmit operation.

## Required workflow

Use MSYS2 UCRT64 with an explicit path:

```bash
export PATH="/ucrt64/bin:/usr/bin:/bin:$PATH"
cd /home/jim/sdrdev/N0JCG-ROC
```

Run work in this order:

1. Inspect `git status` and preserve all user-owned work.
2. Edit checked-in source or scripts; avoid nested PowerShell/Bash/SSH logic.
3. Run `make test` locally.
4. Run the relevant `--check-only` preflight.
5. Make the narrowly scoped deployment or package change.
6. Run the same tests on the server.
7. Verify the served HTML, JavaScript, API health, systemd state, and transmit
   interlock from the development host.
8. Preserve an exact, application-specific rollback path.

The final served-state gate is:

```bash
./deploy/validate_deployed.sh
```

It compares served HTML and JavaScript hashes with local source, validates live
API invariants, and verifies the ROC systemd service and failed-unit state.

## Credentials

Use `deploy/setup_server_auth.sh` to install a project-specific Ed25519 key.
The password may be supplied transiently through `ROC_PASS`; it must never be
written into Git, `.server.env`, browser storage, deployed assets, or logs.
`.server.env` may contain non-secret host, user, port, path, and key settings.

## Package installation

`config/base-packages.txt` is the canonical package manifest.

```bash
./deploy/install_base_tools_remote.sh --check-only
ROC_SUDO_PASS='<transient>' ./deploy/install_base_tools_remote.sh
```

The package installer installs tooling only. It does not start Direwolf, create
a modem configuration, claim a USB device, load an RF frequency, or enable
transmission. Hardware-specific configuration begins only after the device is
physically present and identified by stable serial or USB path.

## Deployment

```bash
./deploy/deploy.sh --check-only
ROC_SUDO_PASS='<transient>' ./deploy/deploy.sh
```

Deployment uses a temporary local staging directory, synchronizes only project
files, preserves the untracked remote `config/station.toml`, validates the
remote source, restarts only `n0jcg-roc.service`, then checks both loopback and
LAN-served assets. A free port or the existing ROC-owned listener is required.

## Rollback

Stop without deletion:

```bash
ROC_SUDO_PASS='<transient>' ./deploy/undeploy.sh --stop-only
```

Full removal requires `CONFIRM_REMOVE=YES` and targets only the literal ROC
service file and `/home/n0jcg/sdrdev/N0JCG-ROC`. It does not remove packages,
credentials, unrelated services, or other projects.

## Validation layers

1. Python, shell, and optional JavaScript syntax.
2. Dependency-free architectural and safety tests.
3. Local API/static smoke tests.
4. Read-only SSH, package, port, and service preflight.
5. Remote tests after synchronization.
6. systemd enabled/active and restart evidence.
7. Served HTML/JavaScript/API verification from the host.
8. Live receive validation only after hardware is attached.
9. Separately guarded transmit validation only after coordination and physical
   safety requirements are satisfied.
