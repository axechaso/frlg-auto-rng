import unittest

import app_version


class AppVersionTests(unittest.TestCase):
    def test_release_contract(self):
        self.assertEqual(app_version.APP_VERSION, "0.2.1")
        self.assertEqual(app_version.APP_VERSION_CODE, 2026090301)
        self.assertEqual(app_version.UPDATE_SCHEMA, 1)
        self.assertEqual(app_version.GITHUB_REPOSITORY, "axechaso/frlg-auto-rng")
        self.assertEqual(
            app_version.version_payload(),
            {
                "version": "0.2.1",
                "version_code": 2026090301,
                "update_schema": 1,
                "repository": "axechaso/frlg-auto-rng",
            },
        )
