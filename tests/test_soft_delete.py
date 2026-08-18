"""Tests for process lookup and soft-delete (baja lógica)."""

import unittest
from unittest.mock import MagicMock, patch

from facturia_matching.persistence.back_check import get_process


class TestGetProcessSoftDelete(unittest.TestCase):
    @patch("facturia_matching.persistence.back_check.get_mysql_connection")
    @patch("facturia_matching.persistence.back_check.get_mysql_table_columns")
    def test_get_process_excludes_deleted_at(self, mock_cols, mock_conn):
        mock_cols.return_value = [
            "id",
            "process_number",
            "company_id",
            "deleted_at",
            "json_data",
        ]
        cur = MagicMock()
        cur.fetchone.return_value = None
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conn.return_value = conn

        out = get_process(123, empresa=1)
        self.assertIsNone(out)
        sql = cur.execute.call_args[0][0]
        self.assertIn("deleted_at", sql)
        self.assertIn("IS NULL", sql)
        self.assertIn("process_number", sql)

    @patch("facturia_matching.persistence.back_check.get_mysql_connection")
    @patch("facturia_matching.persistence.back_check.get_mysql_table_columns")
    def test_get_process_without_deleted_at_column(self, mock_cols, mock_conn):
        mock_cols.return_value = ["id", "process_number", "company_id", "json_data"]
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1, "process_number": 9}
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conn.return_value = conn

        out = get_process(9)
        self.assertEqual(out["process_number"], 9)
        sql = cur.execute.call_args[0][0]
        self.assertNotIn("deleted_at", sql)


class TestFetchRecentExcludesSoftDeleted(unittest.TestCase):
    @patch("facturia_matching.persistence.product_label_memory.get_mysql_connection")
    @patch(
        "facturia_matching.persistence.product_label_memory.get_conversion_template_id",
        return_value=99,
    )
    def test_sql_joins_process_and_filters_deleted_at(self, _mock_tid, mock_conn):
        from facturia_matching.persistence.product_label_memory import (
            fetch_recent_conversion_row_lists,
        )

        cur = MagicMock()
        cur.fetchall.return_value = []
        conn = MagicMock()
        conn.cursor.return_value = cur
        mock_conn.return_value = conn

        fetch_recent_conversion_row_lists(1, template_id=99, limit=10)
        sql = cur.execute.call_args[0][0]
        self.assertIn("INNER JOIN", sql)
        self.assertIn("process", sql.lower())
        self.assertIn("deleted_at IS NULL", sql)


if __name__ == "__main__":
    unittest.main()
