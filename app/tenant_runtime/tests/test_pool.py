"""Runtime pool (Service Trust ST-3, decision S1). No database: the pool reads /etc/group and /etc/passwd."""

import unittest
from unittest.mock import patch

from cloud_agents.subprocess import run_as_argv
from tenant_runtime import pool


class TestRunAsArgv(unittest.TestCase):
    def test_no_user_runs_as_is(self):
        self.assertEqual(run_as_argv(None, ["claude", "-p"]), ["claude", "-p"])

    def test_user_switches_with_noninteractive_sudo(self):
        self.assertEqual(
            run_as_argv("mxr-1", ["/usr/local/bin/claude", "-p"]),
            ["sudo", "-n", "-H", "-u", "mxr-1", "--", "/usr/local/bin/claude", "-p"],
        )


class TestPickFreeUser(unittest.TestCase):
    def test_skips_users_in_use(self):
        picked = pool.pick_free_user(["mxr-1", "mxr-2"], {"mxr-1"}, groups_of=lambda _n: {"mixtape-runtimes"})
        self.assertEqual(picked, "mxr-2")

    def test_never_assigns_a_user_in_a_forbidden_group(self):
        groups = {"mxr-1": {"mixtape-runtimes", "mixtape"}, "mxr-2": {"mixtape-runtimes"}}
        picked = pool.pick_free_user(["mxr-1", "mxr-2"], set(), groups_of=groups.get)
        self.assertEqual(picked, "mxr-2")

    def test_none_when_all_taken(self):
        self.assertIsNone(pool.pick_free_user(["mxr-1"], {"mxr-1"}, groups_of=lambda _n: set()))


class TestAssignUser(unittest.TestCase):
    def test_no_pool_group_is_a_clear_error(self):
        with patch.object(pool, "pool_members", return_value=[]):
            with self.assertRaises(pool.PoolError):
                pool.assign_user()

    def test_assigns_first_free_member_with_its_home(self):
        with patch.object(pool, "pool_members", return_value=["mxr-1", "mxr-2"]), \
                patch.object(pool, "users_in_use", return_value={"mxr-1"}), \
                patch.object(pool, "_groups_of", return_value={"mixtape-runtimes"}), \
                patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"):
            self.assertEqual(pool.assign_user(), ("mxr-2", "/home/mxr-2"))

    def test_reuses_the_persons_existing_user_for_another_provider(self):
        with patch.object(pool, "pool_members", return_value=["mxr-1", "mxr-2"]), \
                patch.object(pool, "users_in_use", return_value={"mxr-1"}), \
                patch.object(pool, "_groups_of", return_value={"mixtape-runtimes"}), \
                patch.object(pool, "home_of", side_effect=lambda n: f"/home/{n}"):
            self.assertEqual(pool.assign_user(existing_user="mxr-1"), ("mxr-1", "/home/mxr-1"))

    def test_existing_user_that_left_the_pool_is_refused(self):
        with patch.object(pool, "pool_members", return_value=["mxr-2"]):
            with self.assertRaises(pool.PoolError):
                pool.assign_user(existing_user="mxr-1")

    def test_exhausted_pool(self):
        with patch.object(pool, "pool_members", return_value=["mxr-1"]), \
                patch.object(pool, "users_in_use", return_value={"mxr-1"}), \
                patch.object(pool, "_groups_of", return_value=set()):
            with self.assertRaises(pool.PoolError):
                pool.assign_user()
