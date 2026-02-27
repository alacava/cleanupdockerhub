#!/usr/bin/env python3
"""
Docker Hub Image Cleanup Tool

Removes old Docker Hub image tags based on configurable retention policies.
A tag is only deleted when BOTH conditions are met:
  - It ranks beyond the KEEP_LAST_N most recently updated tags
  - Its age meets or exceeds MIN_AGE_DAYS
"""

import os
import sys
import logging
from datetime import datetime, timezone
from typing import List, Tuple

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration from environment variables
# ---------------------------------------------------------------------------
DOCKERHUB_USERNAME: str = os.getenv("DOCKERHUB_USERNAME", "")
DOCKERHUB_TOKEN: str = os.getenv("DOCKERHUB_TOKEN", "")
DOCKERHUB_NAMESPACE: str = os.getenv("DOCKERHUB_NAMESPACE", DOCKERHUB_USERNAME)
KEEP_LAST_N: int = int(os.getenv("KEEP_LAST_N", "5"))
MIN_AGE_DAYS: int = int(os.getenv("MIN_AGE_DAYS", "30"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() in ("true", "1", "yes")
REPOS_TO_CLEAN: List[str] = [
    r.strip() for r in os.getenv("REPOS_TO_CLEAN", "").split(",") if r.strip()
]
EXCLUDE_TAGS: List[str] = [
    t.strip() for t in os.getenv("EXCLUDE_TAGS", "latest").split(",") if t.strip()
]
# Standard 5-field cron expression (min hour dom month dow).
# Leave empty to run once and exit.
# Example: "0 3 * * 0"  →  every Sunday at 03:00
CRON_SCHEDULE: str = os.getenv("CRON_SCHEDULE", "").strip()

DOCKERHUB_API = "https://hub.docker.com/v2"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docker Hub API helpers
# ---------------------------------------------------------------------------

def get_token() -> str:
    """Authenticate with Docker Hub and return a JWT token."""
    resp = requests.post(
        f"{DOCKERHUB_API}/users/login",
        json={"username": DOCKERHUB_USERNAME, "password": DOCKERHUB_TOKEN},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["token"]


def paginate(url: str, token: str) -> List[dict]:
    """Fetch every page from a paginated Docker Hub API endpoint."""
    results: List[dict] = []
    headers = {"Authorization": f"Bearer {token}"}
    while url:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        results.extend(data.get("results", []))
        url = data.get("next")
    return results


def get_repositories(token: str) -> List[str]:
    """Return all repository names for the configured namespace."""
    url = f"{DOCKERHUB_API}/repositories/{DOCKERHUB_NAMESPACE}/?page_size=100"
    repos = paginate(url, token)
    return [r["name"] for r in repos]


def get_tags(token: str, repo: str) -> List[dict]:
    """Return tags for a repository sorted newest-first by last_updated."""
    url = (
        f"{DOCKERHUB_API}/repositories/{DOCKERHUB_NAMESPACE}/{repo}"
        f"/tags/?page_size=100"
    )
    tags = paginate(url, token)
    return sorted(tags, key=lambda t: t.get("last_updated", ""), reverse=True)


def delete_tag(token: str, repo: str, tag: str) -> bool:
    """Delete a tag from Docker Hub. Returns True on success (HTTP 204)."""
    url = (
        f"{DOCKERHUB_API}/repositories/{DOCKERHUB_NAMESPACE}/{repo}/tags/{tag}/"
    )
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.delete(url, headers=headers, timeout=30)
    return resp.status_code == 204


# ---------------------------------------------------------------------------
# Deletion logic
# ---------------------------------------------------------------------------

def evaluate_tag(tag: dict, rank: int) -> Tuple[bool, str]:
    """
    Decide whether a tag should be deleted.

    Parameters
    ----------
    tag:  Raw tag dict from the Docker Hub API.
    rank: 0-based position in the newest-first sorted list.

    Returns (should_delete, human-readable reason).

    Deletion requires BOTH:
      - rank >= KEEP_LAST_N  (not within the protected most-recent window)
      - age  >= MIN_AGE_DAYS (old enough to be safe to remove)
    """
    name = tag.get("name", "")

    if name in EXCLUDE_TAGS:
        return False, f"excluded tag '{name}'"

    last_updated_str = tag.get("last_updated", "")
    if not last_updated_str:
        return False, "no last_updated timestamp — skipping to be safe"

    last_updated = datetime.fromisoformat(last_updated_str.replace("Z", "+00:00"))
    age_days = (datetime.now(timezone.utc) - last_updated).days

    beyond_keep = rank >= KEEP_LAST_N
    old_enough = age_days >= MIN_AGE_DAYS

    if beyond_keep and old_enough:
        return (
            True,
            f"rank {rank + 1} (beyond keep={KEEP_LAST_N}), age {age_days}d (>= {MIN_AGE_DAYS}d)",
        )
    if not beyond_keep:
        return False, f"rank {rank + 1} — within keep-last-{KEEP_LAST_N} window"
    return (
        False,
        f"rank {rank + 1} beyond window but only {age_days}d old (min {MIN_AGE_DAYS}d)",
    )


# ---------------------------------------------------------------------------
# Per-repository processing
# ---------------------------------------------------------------------------

def process_repo(token: str, repo: str) -> dict:
    """Evaluate and (if not dry-run) delete eligible tags in one repository."""
    log.info(f"  Repository: {DOCKERHUB_NAMESPACE}/{repo}")
    tags = get_tags(token, repo)
    stats = {"checked": len(tags), "deleted": 0, "kept": 0, "errors": 0}

    for rank, tag in enumerate(tags):
        name = tag.get("name", "unknown")
        should_delete, reason = evaluate_tag(tag, rank)

        if should_delete:
            if DRY_RUN:
                log.info(f"    [DRY RUN] would delete  {repo}:{name}  ({reason})")
                stats["deleted"] += 1
            else:
                log.info(f"    Deleting {repo}:{name}  ({reason})")
                if delete_tag(token, repo, name):
                    log.info(f"    Deleted  {repo}:{name}")
                    stats["deleted"] += 1
                else:
                    log.error(f"    Failed to delete {repo}:{name}")
                    stats["errors"] += 1
        else:
            log.debug(f"    Keeping  {repo}:{name}  ({reason})")
            stats["kept"] += 1

    log.info(
        f"    checked={stats['checked']}  "
        f"{'would delete' if DRY_RUN else 'deleted'}={stats['deleted']}  "
        f"kept={stats['kept']}"
        + (f"  errors={stats['errors']}" if stats["errors"] else "")
    )
    return stats


# ---------------------------------------------------------------------------
# Core cleanup run (called once per execution, or by the scheduler)
# ---------------------------------------------------------------------------

def run_cleanup() -> None:
    divider = "=" * 60
    log.info(divider)
    log.info("Docker Hub Image Cleanup")
    log.info(divider)
    log.info(f"Namespace      : {DOCKERHUB_NAMESPACE}")
    log.info(f"Keep last N    : {KEEP_LAST_N}")
    log.info(f"Min age (days) : {MIN_AGE_DAYS}")
    log.info(f"Exclude tags   : {', '.join(EXCLUDE_TAGS) or '(none)'}")
    log.info(f"Repos filter   : {', '.join(REPOS_TO_CLEAN) or '(all repos)'}")
    log.info(f"Dry run        : {DRY_RUN}")
    log.info(divider)

    token = get_token()

    repos = REPOS_TO_CLEAN if REPOS_TO_CLEAN else get_repositories(token)
    log.info(f"Processing {len(repos)} repositor{'y' if len(repos) == 1 else 'ies'}")
    log.info(divider)

    totals: dict = {"checked": 0, "deleted": 0, "kept": 0, "errors": 0}
    for repo in repos:
        stats = process_repo(token, repo)
        for key in totals:
            totals[key] += stats[key]

    log.info(divider)
    log.info("Summary")
    log.info(f"  Tags checked : {totals['checked']}")
    log.info(
        f"  Tags {'would be ' if DRY_RUN else ''}deleted : {totals['deleted']}"
    )
    log.info(f"  Tags kept    : {totals['kept']}")
    if totals["errors"]:
        log.warning(f"  Errors       : {totals['errors']}")
    log.info(divider)

    if DRY_RUN:
        log.info("Dry-run complete — set DRY_RUN=false to perform actual deletions.")


# ---------------------------------------------------------------------------
# Entry point — one-shot or scheduled
# ---------------------------------------------------------------------------

def safe_run_cleanup() -> None:
    """Run cleanup and catch all exceptions so the scheduler is never killed."""
    try:
        run_cleanup()
    except Exception as exc:
        log.error(f"Cleanup run failed: {exc}")
        log.info("Will retry on the next scheduled tick.")


def main() -> None:
    if not DOCKERHUB_USERNAME or not DOCKERHUB_TOKEN:
        log.error("DOCKERHUB_USERNAME and DOCKERHUB_TOKEN must be set.")
        sys.exit(1)

    if not CRON_SCHEDULE:
        # One-shot mode: let exceptions propagate so the exit code reflects failure.
        run_cleanup()
        return

    # Validate the cron expression before starting the scheduler
    try:
        trigger = CronTrigger.from_crontab(CRON_SCHEDULE)
    except ValueError as exc:
        log.error(f"Invalid CRON_SCHEDULE '{CRON_SCHEDULE}': {exc}")
        sys.exit(1)

    log.info(f"Cron mode — schedule: '{CRON_SCHEDULE}'")
    log.info("Running cleanup immediately, then waiting for next scheduled time...")

    # Run once right away so there is no silent wait on first start.
    # Use safe_run_cleanup so a transient error doesn't abort cron mode.
    safe_run_cleanup()

    scheduler = BlockingScheduler()
    scheduler.add_job(safe_run_cleanup, trigger)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
