import unittest
from unittest.mock import patch

from facturia_matching.infra.db_resolve import (
    mysql_connect_kwargs,
    resolved_pg_dbname,
)


class TestResolvedPgDbname(unittest.TestCase):
    def test_explicit_db_name(self):
        self.assertEqual(resolved_pg_dbname("mydb", "user"), "mydb")

    def test_fallback_to_user_when_discovery_empty(self):
        with patch(
            "facturia_matching.infra.db_resolve._discover_single_pg_database",
            return_value=None,
        ):
            self.assertEqual(
                resolved_pg_dbname(
                    "",
                    "app_user",
                    host="h",
                    port="5432",
                    password="p",
                ),
                "app_user",
            )

    @patch("facturia_matching.infra.db_resolve._discover_single_pg_database")
    def test_discover_when_no_name(self, mock_discover):
        mock_discover.return_value = "only_db"
        self.assertEqual(
            resolved_pg_dbname(
                "",
                "app_user",
                host="h",
                port="5432",
                password="p",
            ),
            "only_db",
        )
        mock_discover.assert_called_once()


class TestMysqlConnectKwargs(unittest.TestCase):
    def test_without_database(self):
        self.assertEqual(
            mysql_connect_kwargs("h", "u", "p", 3306, None),
            {"host": "h", "user": "u", "password": "p", "port": 3306},
        )

    def test_with_database(self):
        self.assertEqual(
            mysql_connect_kwargs("h", "u", "p", 3306, "sudataco_app")["database"],
            "sudataco_app",
        )


class TestProcessSchema(unittest.TestCase):
    def test_default_process_schema(self):
        from facturia_matching.infra.config import resolve_process_schema

        self.assertEqual(resolve_process_schema(""), "sudataco_facturia")

    def test_staging_process_schema(self):
        from facturia_matching.infra.config import resolve_process_schema

        self.assertEqual(resolve_process_schema("sudataco_staging"), "sudataco_staging")


if __name__ == "__main__":
    unittest.main()
