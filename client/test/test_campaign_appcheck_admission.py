"""Only actual prior CREATE refusals can stop an otherwise optional integration."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from moneymin import appcheck, config, upload
from moneymin.campaign_types import AccountSpec
from moneymin.delivery import admission


class CreateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.account = AccountSpec("fixture@example.invalid", "org-a")
        self.refusal = {"account_email": self.account.email, "org_key": self.account.org_key,
                        "state": "failed", "phase": "create", "upload_id": None,
                        "updated_at": "2026-10-10T12:00:00.000Z",
                        "error": "POST /uploads falhou (429): serviço recusou [bloqueio: app_check]"}

    def test_exact_create_refusal_scoped_to_account_and_org(self):
        self.assertEqual(admission.rejected_create_owners([self.account], [self.refusal]),
                         {self.account.email})
        for changes in ({"org_key": "org-b"}, {"account_email": "other@example.invalid"},
                        {"phase": "complete"}, {"state": "done"},
                        {"error": "HTTP 429 documentação app_check"},
                        {"error": "POST /uploads falhou (429): [bloqueio: rate_limit]"},
                        {"updated_at": "invalid"}):
            with self.subTest(changes=changes):
                self.assertEqual(admission.rejected_create_owners([self.account],
                                 [{**self.refusal, **changes}]), set())

    def test_later_remote_receipt_clears_previous_refusal_regardless_of_list_order(self):
        receipt = {**self.refusal, "upload_id": "remote-upload-id", "state": "transport",
                   "phase": "transport", "updated_at": "2026-10-10T12:01:00Z", "error": None}
        for rows in ([receipt, self.refusal], [self.refusal, receipt]):
            self.assertEqual(admission.rejected_create_owners([self.account], rows), set())
        receipt["updated_at"] = "2026-10-10T11:59:00Z"
        self.assertEqual(admission.rejected_create_owners([self.account], [receipt, self.refusal]),
                         {self.account.email})

    def test_admission_renews_before_consulting_prior_refusal(self):
        rows = [deepcopy(self.refusal)]
        renewed = {"token_available": True, "configured": True, "source": "device"}
        with patch.object(appcheck, "ensure_app_check_fresh", return_value=renewed) as ensure, \
             patch.object(upload, "list_sidecars") as read:
            blocker = admission.campaign_create_blocker([self.account])
        self.assertIsNone(blocker)
        ensure.assert_called_once_with()
        read.assert_not_called()
        self.assertEqual(rows, [self.refusal])

    def test_known_remote_refusal_blocks_only_after_renewal_still_unavailable(self):
        rows = [deepcopy(self.refusal)]
        unavailable = {"token_available": False, "configured": True, "source": None}
        with patch.object(appcheck, "ensure_app_check_fresh", return_value=unavailable) as ensure, \
             patch.object(admission, "_has_journal_files", return_value=True), \
             patch.object(upload, "list_sidecars", return_value=rows):
            blocker = admission.campaign_create_blocker([self.account])
        self.assertIn("último CREATE", blocker)
        self.assertIn("nenhum preparo", blocker)
        ensure.assert_called_once_with()
        self.assertEqual(rows, [self.refusal])

    def test_mint_failure_alone_never_makes_appcheck_mandatory(self):
        status = {"token_available": False, "configured": True,
                  "diagnostic": {"category": "attestation_failed"}}
        with patch.object(appcheck, "ensure_app_check_fresh", return_value=status), \
             patch.object(upload, "list_sidecars", return_value=[]):
            self.assertIsNone(admission.campaign_create_blocker([self.account]))

    def test_available_token_does_not_claim_remote_acceptance(self):
        with patch.object(appcheck, "ensure_app_check_fresh",
                          return_value={"token_available": True}) as ensure, \
             patch.object(upload, "list_sidecars") as read:
            self.assertIsNone(admission.campaign_create_blocker([self.account]))
        ensure.assert_called_once_with()
        read.assert_not_called()

    def test_empty_profile_probe_does_not_create_locks_directories_or_read_receipts(self):
        unavailable = {"token_available": False, "configured": False}
        with TemporaryDirectory() as folder, \
             patch.multiple(config, DATA_DIR=Path(folder) / "data", MEDIA_DATA_DIR=Path(folder) / "media"), \
             patch.object(appcheck, "ensure_app_check_fresh", return_value=unavailable), \
             patch.object(upload, "list_sidecars") as read:
            self.assertIsNone(admission.campaign_create_blocker([self.account]))
            self.assertEqual(list(Path(folder).iterdir()), [])
            read.assert_not_called()
