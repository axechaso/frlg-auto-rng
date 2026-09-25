import unittest

import app_version


class AppVersionTests(unittest.TestCase):
    def test_release_contract(self):
        self.assertEqual(app_version.APP_VERSION, "0.9.4")
        self.assertEqual(app_version.APP_VERSION_CODE, 2026092501)
        self.assertEqual(app_version.UPDATE_SCHEMA, 1)
        self.assertEqual(app_version.GITHUB_REPOSITORY, "axechaso/frlg-auto-rng")
        self.assertEqual(
            app_version.GITEE_REPOSITORY,
            "dazzling-night-scales/frlg-auto-rng",
        )
        self.assertEqual(
            app_version.version_payload(),
            {
                "version": "0.9.4",
                "version_code": 2026092501,
                "update_schema": 1,
                "repository": "axechaso/frlg-auto-rng",
            },
        )
