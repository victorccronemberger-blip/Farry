import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('publisher', Path(__file__).resolve().parents[1] / 'tools/github_release.py')
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def test_repeated_and_older_versions_are_blocked(self):
        for version in ('1.0.63', '1.0.62'):
            with self.subTest(version=version), patch.object(publisher, 'request', return_value={'tag_name': 'v1.0.63'}):
                with self.assertRaises(RuntimeError):
                    publisher.check_remote_version(version)

    def test_numerical_version_order_and_first_release(self):
        for latest in (None, {'tag_name': 'v1.0.9'}):
            with self.subTest(latest=latest), patch.object(publisher, 'request', side_effect=[latest, None]) as request:
                publisher.check_remote_version('1.0.10')
                self.assertTrue(all(call.kwargs == {'missing_ok': True} for call in request.call_args_list))

    def test_existing_tag_and_invalid_latest_fail_closed(self):
        for responses in ([None, {'draft': False}], [None, {'draft': True}], [{'tag_name': 'invalid'}]):
            with self.subTest(responses=responses), patch.object(publisher, 'request', side_effect=responses):
                with self.assertRaises(RuntimeError):
                    publisher.check_remote_version('1.0.64')

    def test_only_explicit_draft_resume_is_allowed(self):
        with patch.object(publisher, 'request', side_effect=[None, {'draft': True}]):
            publisher.check_remote_version('1.0.64', existing_draft=True)

    def test_network_failure_blocks_publication(self):
        with patch.object(publisher, 'request', side_effect=RuntimeError('GitHub HTTP 503')):
            with self.assertRaises(RuntimeError):
                publisher.check_remote_version('1.0.64')


if __name__ == '__main__':
    unittest.main()
