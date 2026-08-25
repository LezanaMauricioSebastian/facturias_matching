"""Regresión: ok del import no se fuerza a True solo porque hubo trabajo."""
import unittest
from unittest.mock import patch

from facturia_matching.odoo.import_.create import import_rows_to_odoo


def _valid_row(doc: str = "00001-00000001") -> dict:
    return {
        "partner_id": "1",
        "journal_id": "2",
        "l10n_latam_document_number": doc,
        "invoice_date": "15/01/2024",
        "invoice_line_ids/name": "Item",
        "invoice_line_ids/quantity": "1",
        "invoice_line_ids/price_unit": "10",
        "invoice_line_ids/account_id": "10",
        "__comprobante_idx": 0,
    }


class TestImportOkFlag(unittest.TestCase):
    @patch("facturia_matching.odoo.import_.create.sync_move_taxes_from_group")
    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.create._prepare_rows_for_import")
    @patch("facturia_matching.odoo.import_.create.get_odoo_uid_from_config", return_value=7)
    @patch("facturia_matching.odoo.import_.create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.import_.create.get_odoo_import_config",
        return_value={"db": "demo", "base_url": "https://odoo.example"},
    )
    def test_ok_false_when_create_ok_but_tax_sync_fails(
        self,
        _cfg,
        _ready,
        _uid,
        mock_prep,
        mock_rpc,
        mock_sync,
    ):
        row = _valid_row()
        mock_prep.return_value = ([ [row] ], [])
        mock_rpc.return_value = 101  # account.move.create
        mock_sync.side_effect = ValueError("factura no está en borrador")

        out = import_rows_to_odoo([row], skip_duplicates=False)

        self.assertFalse(out["ok"], msg="ok must be false when errors mixed with created")
        self.assertEqual(len(out["created"]), 1)
        self.assertEqual(len(out["errors"]), 1)
        self.assertNotIn("uid", out)

    @patch("facturia_matching.odoo.import_.create.sync_move_taxes_from_group")
    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.create._prepare_rows_for_import")
    @patch("facturia_matching.odoo.import_.create.get_odoo_uid_from_config", return_value=7)
    @patch("facturia_matching.odoo.import_.create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.import_.create.get_odoo_import_config",
        return_value={"db": "demo", "base_url": "https://odoo.example"},
    )
    def test_ok_true_when_no_errors(
        self,
        _cfg,
        _ready,
        _uid,
        mock_prep,
        mock_rpc,
        mock_sync,
    ):
        row = _valid_row()
        mock_prep.return_value = ([ [row] ], [])
        mock_rpc.return_value = 202
        mock_sync.return_value = {
            "move_id": 202,
            "name": "BILL/1",
            "state": "draft",
            "tax_lines_updated": 0,
        }

        out = import_rows_to_odoo([row], skip_duplicates=False)

        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], [])
        self.assertNotIn("uid", out)


if __name__ == "__main__":
    unittest.main()
