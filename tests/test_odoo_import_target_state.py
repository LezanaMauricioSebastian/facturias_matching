"""target_state=posted publica solo después de un sync ok."""
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


def _patches(rpc, sync, prep):
    row = _valid_row()
    prep.return_value = ([[row]], [])
    sync.return_value = {
        "move_id": 202,
        "name": "BILL/1",
        "state": "draft",
        "tax_lines_updated": 0,
    }
    return row


class TestImportTargetState(unittest.TestCase):
    @patch("facturia_matching.odoo.import_.create.sync_move_taxes_from_group")
    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.create._prepare_rows_for_import")
    @patch("facturia_matching.odoo.import_.create.get_odoo_uid_from_config", return_value=7)
    @patch("facturia_matching.odoo.import_.create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.import_.create.get_odoo_import_config",
        return_value={"db": "demo", "base_url": "https://odoo.example"},
    )
    def test_draft_does_not_post(self, _cfg, _ready, _uid, mock_prep, mock_rpc, mock_sync):
        _patches(mock_rpc, mock_sync, mock_prep)
        mock_rpc.return_value = 202

        out = import_rows_to_odoo([_valid_row()], skip_duplicates=False, target_state="draft")

        self.assertTrue(out["ok"])
        self.assertEqual(out["created"][0]["state"], "draft")
        methods = [call.args[2] for call in mock_rpc.call_args_list]
        self.assertNotIn("action_post", methods)

    @patch("facturia_matching.odoo.import_.create.sync_move_taxes_from_group")
    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.create._prepare_rows_for_import")
    @patch("facturia_matching.odoo.import_.create.get_odoo_uid_from_config", return_value=7)
    @patch("facturia_matching.odoo.import_.create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.import_.create.get_odoo_import_config",
        return_value={"db": "demo", "base_url": "https://odoo.example"},
    )
    def test_posted_calls_action_post_after_sync(
        self, _cfg, _ready, _uid, mock_prep, mock_rpc, mock_sync
    ):
        _patches(mock_rpc, mock_sync, mock_prep)

        def _rpc(_config, _model, method, args, kwargs=None):
            if method == "create":
                return 202
            if method == "action_post":
                return True
            raise AssertionError(method)

        mock_rpc.side_effect = _rpc

        out = import_rows_to_odoo([_valid_row()], skip_duplicates=False, target_state="posted")

        self.assertTrue(out["ok"])
        self.assertEqual(out["created"][0]["state"], "posted")
        self.assertEqual(out["updated_taxes"][0]["state"], "posted")
        methods = [call.args[2] for call in mock_rpc.call_args_list]
        self.assertEqual(methods, ["create", "action_post"])
        self.assertEqual(mock_rpc.call_args_list[1].args[3], [[202]])
        mock_sync.assert_called_once()

    @patch("facturia_matching.odoo.import_.create.sync_move_taxes_from_group")
    @patch("facturia_matching.odoo.import_.create.odoo_execute_kw_with_config")
    @patch("facturia_matching.odoo.import_.create._prepare_rows_for_import")
    @patch("facturia_matching.odoo.import_.create.get_odoo_uid_from_config", return_value=7)
    @patch("facturia_matching.odoo.import_.create.is_odoo_config_ready", return_value=True)
    @patch(
        "facturia_matching.odoo.import_.create.get_odoo_import_config",
        return_value={"db": "demo", "base_url": "https://odoo.example"},
    )
    def test_posted_skips_action_post_when_sync_fails(
        self, _cfg, _ready, _uid, mock_prep, mock_rpc, mock_sync
    ):
        row = _valid_row()
        mock_prep.return_value = ([[row]], [])
        mock_rpc.return_value = 101
        mock_sync.side_effect = ValueError("factura no está en borrador")

        out = import_rows_to_odoo([row], skip_duplicates=False, target_state="posted")

        self.assertFalse(out["ok"])
        self.assertEqual(out["created"][0]["state"], "draft")
        methods = [call.args[2] for call in mock_rpc.call_args_list]
        self.assertNotIn("action_post", methods)


if __name__ == "__main__":
    unittest.main()
