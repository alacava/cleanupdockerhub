#!/usr/bin/env python3
"""
Unit tests for cleanupdockerhub.py

Run with:
    pip install -r requirements.txt
    python test_cleanupdockerhub.py
"""

import os
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import requests as req

# Provide dummy credentials so the module loads without raising on import
os.environ.setdefault("DOCKERHUB_USERNAME", "testuser")
os.environ.setdefault("DOCKERHUB_TOKEN", "testtoken")

import cleanupdockerhub as app  # noqa: E402  (must come after env setup)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_tag(name: str, age_days: int) -> dict:
    """Return a minimal tag dict with a realistic last_updated timestamp."""
    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    return {"name": name, "last_updated": ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")}


def make_http_error(status_code: int) -> req.exceptions.HTTPError:
    resp = MagicMock()
    resp.status_code = status_code
    exc = req.exceptions.HTTPError(response=resp)
    return exc


# ---------------------------------------------------------------------------
# evaluate_tag
# ---------------------------------------------------------------------------

class TestEvaluateTag(unittest.TestCase):

    def _eval(self, name, age_days, rank, keep=3, min_age=7, exclude=None):
        tag = make_tag(name, age_days)
        with (
            patch.object(app, "KEEP_LAST_N", keep),
            patch.object(app, "MIN_AGE_DAYS", min_age),
            patch.object(app, "EXCLUDE_TAGS", exclude or ["latest"]),
        ):
            return app.evaluate_tag(tag, rank)

    def test_within_keep_window_kept(self):
        delete, reason = self._eval("v3.0.0", age_days=90, rank=0)
        self.assertFalse(delete)
        self.assertIn("within", reason)

    def test_last_tag_in_keep_window_kept(self):
        # rank == KEEP_LAST_N - 1  →  still protected
        delete, _ = self._eval("v1.0.0", age_days=90, rank=2, keep=3)
        self.assertFalse(delete)

    def test_first_tag_outside_window_and_old_enough_deleted(self):
        # rank == KEEP_LAST_N  →  first candidate
        delete, reason = self._eval("v1.0.0", age_days=30, rank=3, keep=3, min_age=7)
        self.assertTrue(delete)
        self.assertIn("rank 4", reason)

    def test_outside_window_but_too_young_kept(self):
        delete, reason = self._eval("v0.9.0", age_days=3, rank=10, keep=3, min_age=7)
        self.assertFalse(delete)
        self.assertIn("only", reason)

    def test_excluded_tag_never_deleted_regardless_of_rank_and_age(self):
        delete, reason = self._eval("latest", age_days=3650, rank=9999)
        self.assertFalse(delete)
        self.assertIn("excluded", reason)

    def test_custom_excluded_tags(self):
        delete, _ = self._eval("stable", age_days=3650, rank=9999, exclude=["stable"])
        self.assertFalse(delete)

    def test_missing_timestamp_kept(self):
        tag = {"name": "v1.0.0", "last_updated": ""}
        with (
            patch.object(app, "KEEP_LAST_N", 1),
            patch.object(app, "MIN_AGE_DAYS", 1),
            patch.object(app, "EXCLUDE_TAGS", []),
        ):
            delete, reason = app.evaluate_tag(tag, rank=99)
        self.assertFalse(delete)
        self.assertIn("no last_updated", reason)

    def test_exact_min_age_boundary_deleted(self):
        # age == MIN_AGE_DAYS exactly  →  eligible
        delete, _ = self._eval("v1.0.0", age_days=7, rank=5, keep=3, min_age=7)
        self.assertTrue(delete)

    def test_one_day_under_min_age_kept(self):
        delete, _ = self._eval("v1.0.0", age_days=6, rank=5, keep=3, min_age=7)
        self.assertFalse(delete)


# ---------------------------------------------------------------------------
# get_token (retry logic)
# ---------------------------------------------------------------------------

class TestGetToken(unittest.TestCase):

    @patch("cleanupdockerhub.requests.post")
    def test_success_on_first_attempt(self, mock_post):
        ok = MagicMock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"token": "mytoken"}
        mock_post.return_value = ok

        self.assertEqual(app.get_token(), "mytoken")
        self.assertEqual(mock_post.call_count, 1)

    @patch("cleanupdockerhub.time.sleep")
    @patch("cleanupdockerhub.requests.post")
    def test_retries_on_503_then_succeeds(self, mock_post, mock_sleep):
        fail = MagicMock()
        fail.raise_for_status.side_effect = make_http_error(503)

        ok = MagicMock()
        ok.raise_for_status.return_value = None
        ok.json.return_value = {"token": "retried"}

        mock_post.side_effect = [fail, fail, ok]

        self.assertEqual(app.get_token(), "retried")
        self.assertEqual(mock_post.call_count, 3)
        self.assertEqual(mock_sleep.call_count, 2)  # slept between attempts, not after last

    @patch("cleanupdockerhub.time.sleep")
    @patch("cleanupdockerhub.requests.post")
    def test_no_retry_on_401(self, mock_post, mock_sleep):
        fail = MagicMock()
        fail.raise_for_status.side_effect = make_http_error(401)
        mock_post.return_value = fail

        with self.assertRaises(req.exceptions.HTTPError):
            app.get_token()

        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()

    @patch("cleanupdockerhub.time.sleep")
    @patch("cleanupdockerhub.requests.post")
    def test_exhausts_max_attempts_then_raises(self, mock_post, mock_sleep):
        fail = MagicMock()
        fail.raise_for_status.side_effect = make_http_error(500)
        mock_post.return_value = fail

        with self.assertRaises(req.exceptions.HTTPError):
            app.get_token()

        self.assertEqual(mock_post.call_count, app._MAX_LOGIN_ATTEMPTS)
        # Sleep called one fewer time than attempts (no sleep after last attempt)
        self.assertEqual(mock_sleep.call_count, app._MAX_LOGIN_ATTEMPTS - 1)

    @patch("cleanupdockerhub.time.sleep")
    @patch("cleanupdockerhub.requests.post")
    def test_retries_on_network_error(self, mock_post, mock_sleep):
        mock_post.side_effect = req.exceptions.ConnectionError("network down")

        with self.assertRaises(req.exceptions.ConnectionError):
            app.get_token()

        self.assertEqual(mock_post.call_count, app._MAX_LOGIN_ATTEMPTS)


# ---------------------------------------------------------------------------
# process_repo
# ---------------------------------------------------------------------------

class TestProcessRepo(unittest.TestCase):

    def _run(self, tags, keep=2, min_age=7, exclude=None, dry_run=True):
        with (
            patch.object(app, "KEEP_LAST_N", keep),
            patch.object(app, "MIN_AGE_DAYS", min_age),
            patch.object(app, "EXCLUDE_TAGS", exclude or ["latest"]),
            patch.object(app, "DRY_RUN", dry_run),
            patch("cleanupdockerhub.get_tags", return_value=tags),
            patch("cleanupdockerhub.delete_tag", return_value=True) as mock_delete,
        ):
            stats = app.process_repo("token", "myrepo")
        return stats, mock_delete

    def test_dry_run_counts_without_deleting(self):
        tags = [
            make_tag("v3.0", 1),    # rank 0 → kept (window)
            make_tag("v2.0", 5),    # rank 1 → kept (window)
            make_tag("v1.0", 30),   # rank 2 → would delete
            make_tag("v0.9", 3),    # rank 3 → kept (too young)
        ]
        stats, mock_delete = self._run(tags, dry_run=True)

        self.assertEqual(stats["checked"], 4)
        self.assertEqual(stats["deleted"], 1)   # v1.0 counted
        self.assertEqual(stats["kept"], 3)
        mock_delete.assert_not_called()         # nothing actually deleted

    def test_live_run_calls_delete_for_eligible_tags(self):
        tags = [
            make_tag("v2.0", 1),
            make_tag("v1.0", 30),   # rank 1 — beyond window (keep=1) + old enough
        ]
        stats, mock_delete = self._run(tags, keep=1, dry_run=False)

        mock_delete.assert_called_once_with("token", "myrepo", "v1.0")
        self.assertEqual(stats["deleted"], 1)
        self.assertEqual(stats["errors"], 0)

    def test_failed_delete_counted_as_error(self):
        tags = [
            make_tag("v2.0", 1),
            make_tag("v1.0", 30),
        ]
        with (
            patch.object(app, "KEEP_LAST_N", 1),
            patch.object(app, "MIN_AGE_DAYS", 7),
            patch.object(app, "EXCLUDE_TAGS", []),
            patch.object(app, "DRY_RUN", False),
            patch("cleanupdockerhub.get_tags", return_value=tags),
            patch("cleanupdockerhub.delete_tag", return_value=False),  # API failure
        ):
            stats = app.process_repo("token", "myrepo")

        self.assertEqual(stats["errors"], 1)
        self.assertEqual(stats["deleted"], 0)

    def test_empty_repo_produces_zero_stats(self):
        stats, _ = self._run([])
        self.assertEqual(stats, {"checked": 0, "deleted": 0, "kept": 0, "errors": 0})

    def test_all_tags_within_keep_window_nothing_deleted(self):
        tags = [make_tag(f"v{i}", 1) for i in range(3)]
        stats, mock_delete = self._run(tags, keep=5, dry_run=False)
        mock_delete.assert_not_called()
        self.assertEqual(stats["deleted"], 0)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main(verbosity=2)
