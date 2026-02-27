# cleanupdockerhub

A lightweight Docker-based tool that removes old image tags from Docker Hub according to configurable retention policies.

A tag is only ever deleted when **both** conditions are satisfied:

1. It ranks **beyond** the most-recent `KEEP_LAST_N` tags for a repository, **and**
2. It is **at least** `MIN_AGE_DAYS` days old.

This dual guard means your newest images are always protected, and recently-pushed tags are never removed even if a repository has many of them.

---

## Table of Contents

- [How it works](#how-it-works)
- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Configuration reference](#configuration-reference)
- [Deletion logic in detail](#deletion-logic-in-detail)
- [Running with Docker Compose](#running-with-docker-compose)
- [Running locally without Docker](#running-locally-without-docker)
- [Publishing your own image (GitHub Actions)](#publishing-your-own-image-github-actions)
- [Scheduling](#scheduling)
- [Security notes](#security-notes)

---

## How it works

1. The tool authenticates with the Docker Hub API using your credentials.
2. It fetches every repository in your namespace (or a subset you specify).
3. For each repository it retrieves all tags, sorted newest-first by `last_updated`.
4. Each tag is evaluated against the retention policy (see below).
5. Eligible tags are deleted — or, in dry-run mode, simply logged.
6. A summary is printed at the end.

---

## Prerequisites

- A Docker Hub account.
- A Docker Hub **Personal Access Token** (PAT) with *Read, Write, Delete* permissions.
  Create one at <https://hub.docker.com/settings/security>.
- Docker (to run the containerised tool) **or** Python 3.10+ (to run locally).

---

## Quick start

```bash
# 1. Clone the repository
git clone https://github.com/your-username/cleanupdockerhub.git
cd cleanupdockerhub

# 2. Copy and edit the environment file
cp .env.example .env
#    Fill in DOCKERHUB_USERNAME, DOCKERHUB_TOKEN, and adjust the policy variables.

# 3. Run in dry-run mode first (default) to preview what would be deleted
docker run --rm --env-file .env your-dockerhub-username/cleanupdockerhub:latest

# 4. When satisfied, set DRY_RUN=false in .env and run again to delete for real
docker run --rm --env-file .env your-dockerhub-username/cleanupdockerhub:latest
```

---

## Configuration reference

All settings are provided via environment variables (or a `.env` file).

| Variable | Default | Description |
|---|---|---|
| `DOCKERHUB_USERNAME` | *(required)* | Your Docker Hub username. |
| `DOCKERHUB_TOKEN` | *(required)* | Docker Hub Personal Access Token or password. |
| `DOCKERHUB_NAMESPACE` | `$DOCKERHUB_USERNAME` | Namespace (user or organisation) whose repositories are cleaned. Defaults to `DOCKERHUB_USERNAME`. |
| `KEEP_LAST_N` | `5` | Number of most-recently-updated tags to keep unconditionally, per repository. |
| `MIN_AGE_DAYS` | `30` | Minimum age in days a tag must reach before it becomes eligible for deletion. |
| `REPOS_TO_CLEAN` | *(all repos)* | Comma-separated list of repository names to process. Omit or leave empty to process **all** repositories in the namespace. |
| `EXCLUDE_TAGS` | `latest` | Comma-separated list of tags that are **never** deleted regardless of age or rank. |
| `CRON_SCHEDULE` | *(empty)* | Standard 5-field cron expression (e.g. `0 3 * * 0`). When set, the container runs continuously on that schedule. When empty, the container runs once and exits. |
| `DRY_RUN` | `true` | When `true` the tool only logs what it *would* delete — nothing is removed. Set to `false` to perform real deletions. |

### Example `.env`

```dotenv
DOCKERHUB_USERNAME=myusername
DOCKERHUB_TOKEN=dckr_pat_xxxxxxxxxxxxxxxxxxxx

# Clean only these two repositories
REPOS_TO_CLEAN=my-api,my-worker

# Keep the 3 newest tags; delete tags older than 14 days that fall outside that window
KEEP_LAST_N=3
MIN_AGE_DAYS=14

# Never delete these tags
EXCLUDE_TAGS=latest,stable

# Preview mode — change to false when ready
DRY_RUN=true
```

---

## Deletion logic in detail

Tags in each repository are sorted **newest-first** by `last_updated`. Starting from position 0:

```
rank 0  → newest tag
rank 1  → second-newest tag
...
rank N-1 → Nth-newest tag  (last protected by KEEP_LAST_N)
rank N  → first candidate for deletion (if also old enough)
```

**A tag at rank ≥ KEEP_LAST_N is deleted only if its age ≥ MIN_AGE_DAYS.**

### Worked example

Settings: `KEEP_LAST_N=3`, `MIN_AGE_DAYS=7`, `EXCLUDE_TAGS=latest`

| Rank | Tag | Age | Decision |
|---|---|---|---|
| 0 | `v2.5.0` | 1 day | Kept — within KEEP_LAST_N window |
| 1 | `v2.4.0` | 5 days | Kept — within KEEP_LAST_N window |
| 2 | `v2.3.0` | 9 days | Kept — within KEEP_LAST_N window |
| 3 | `v2.2.0` | 12 days | **Deleted** — beyond window AND ≥ 7 days |
| 4 | `v2.1.0` | 6 days | Kept — beyond window but only 6 days old |
| 5 | `v2.0.0` | 30 days | **Deleted** — beyond window AND ≥ 7 days |
| — | `latest` | 1 day | Kept — in EXCLUDE_TAGS |

---

## Running with Docker Compose

```bash
cp .env.example .env
# Edit .env with your credentials and policy settings

docker compose up
```

The compose file uses `restart: "no"` so the container exits after the run completes — ideal for one-off or scheduled runs.

To build the image locally instead of pulling from Docker Hub, uncomment the `build` section in [docker-compose.yml](docker-compose.yml).

---

## Running locally without Docker

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Edit .env

python cleanupdockerhub.py
```

---

## Publishing your own image (GitHub Actions)

The included workflow at [.github/workflows/docker-publish.yml](.github/workflows/docker-publish.yml) builds a multi-platform image (`linux/amd64` + `linux/arm64`) and pushes it to Docker Hub automatically.

### Setup steps

1. **Add repository secrets** in *Settings → Secrets and variables → Actions*:

   | Secret | Value |
   |---|---|
   | `DOCKERHUB_USERNAME` | Your Docker Hub username |
   | `DOCKERHUB_TOKEN` | Your Docker Hub Personal Access Token |

2. **Push to `main`** — the workflow builds and tags the image as `:main` and `:sha-<short>`.

3. **Push a version tag** (e.g. `git tag v1.0.0 && git push --tags`) — the workflow additionally tags the image as `:1.0.0`, `:1.0`, and `:latest`.

### Tag strategy

| Git event | Image tags produced |
|---|---|
| Push to `main` | `:main`, `:sha-<short>` |
| Pull request | Image built but **not** pushed |
| Tag `v1.2.3` | `:1.2.3`, `:1.2`, `:latest`, `:sha-<short>` |

The workflow also **automatically updates the Docker Hub repository description** from this README on every push to `main`.

---

## Scheduling

### Built-in scheduler (recommended)

Set `CRON_SCHEDULE` in your `.env` to a standard 5-field cron expression. The container will run the cleanup immediately on start, then repeat on that schedule indefinitely.

```dotenv
# Run every Sunday at 03:00
CRON_SCHEDULE=0 3 * * 0
```

```bash
# The container stays alive and re-runs on the configured schedule
docker compose up -d
```

Field order: `minute  hour  day-of-month  month  day-of-week`

| Example | Meaning |
|---|---|
| `0 3 * * *` | Every day at 03:00 |
| `0 3 * * 0` | Every Sunday at 03:00 |
| `0 */6 * * *` | Every 6 hours |
| `30 2 1 * *` | 1st of every month at 02:30 |

Leave `CRON_SCHEDULE` empty (or unset) for a one-shot run — the container exits after completing.

### External cron on a server

If you prefer the host OS to control scheduling, leave `CRON_SCHEDULE` unset and use a host crontab:

```cron
0 3 * * 0   docker run --rm --env-file /opt/cleanupdockerhub/.env antlac1/cleanupdockerhub:latest
```

### Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanupdockerhub
spec:
  schedule: "0 3 * * 0"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: cleanupdockerhub
              image: antlac1/cleanupdockerhub:latest
              envFrom:
                - secretRef:
                    name: dockerhub-credentials
              env:
                - name: KEEP_LAST_N
                  value: "5"
                - name: MIN_AGE_DAYS
                  value: "30"
                - name: DRY_RUN
                  value: "false"
                # CRON_SCHEDULE is intentionally omitted here so the pod
                # runs once per job invocation and exits cleanly.
```

---

## Security notes

- **Never commit your `.env` file.** It is already listed in `.gitignore` (add it if you have not).
- Use a Docker Hub **Personal Access Token** with the minimum required permissions (*Read*, *Write*, *Delete*) rather than your account password.
- Always run in **dry-run mode first** to verify the policy behaves as expected before enabling live deletions.
- The `EXCLUDE_TAGS` list (`latest` by default) provides an extra safety net for tags that must never be removed.
