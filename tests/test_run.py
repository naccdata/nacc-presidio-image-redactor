"""Unit tests for run.py."""

from unittest import TestCase
from unittest.mock import MagicMock, patch

from flywheel_gear_toolkit import GearToolkitContext
from pytest import raises

from run import main


@patch("run.parse_config")
@patch("run.run")
@patch("run.output_to_fw")
@patch("run.add_phi_tags")
class TestRun(TestCase):
    def setUp(self):
        self.mock_context = MagicMock(spec=GearToolkitContext)

    def test_main_phi_found(
        self, mock_add_tags, mock_output, mock_run, mock_parse_config
    ):
        mock_context = self.mock_context
        mock_parse_return_tuple = (
            "fake/debug/path",
            ["fake_input_file"],
            "fakeOpMode",
            30,
            30,
            ["fake_entity"],
            False,
            "fake_bbox_fill",
            "fake_original_filename",
            "fake_prior_scan_inputs",
            "fake_output_path",
            "fake_api_key",
            "fake_file_id",
            "fake_job_id",
            ["validated_user"],
            False,
        )
        mock_parse_config.return_value = mock_parse_return_tuple

        mock_run_return_tuple = (
            0,
            True,
            [{"fake_analyzer_results": [{}, {}, {}]}],
            [{"fake_bbox_coords": [{}, {}, {}]}],
            [{"fake_annotation_coords": [{}, {}, {}]}],
        )
        mock_run.return_value = mock_run_return_tuple

        with raises(SystemExit) as execinfo:
            main(mock_context)

        mock_parse_config.assert_called_once_with(mock_context)
        mock_run.assert_called_once_with(*mock_parse_return_tuple)
        mock_output.assert_called_once()
        mock_add_tags.assert_not_called()
        self.assertEqual(execinfo.value.code, 0)

    def test_main_phi_not_found(
        self, mock_add_tags, mock_output, mock_run, mock_parse_config
    ):
        mock_context = self.mock_context
        mock_parse_return_tuple = (
            "fake/debug/path",
            ["fake_input_file"],
            "fakeOpMode",
            30,
            30,
            ["fake_entity"],
            False,
            "fake_bbox_fill",
            "fake_original_filename",
            "fake_prior_scan_inputs",
            "fake_output_path",
            "fake_api_key",
            "fake_file_id",
            "fake_job_id",
            ["validated_user"],
            False,
        )
        mock_parse_config.return_value = mock_parse_return_tuple

        mock_run_return_tuple = (
            0,
            False,
            [{"fake_analyzer_results": [{}, {}, {}]}],
            [{"fake_bbox_coords": [{}, {}, {}]}],
            [{"fake_annotation_coords": [{}, {}, {}]}],
        )
        mock_run.return_value = mock_run_return_tuple
        with raises(SystemExit) as execinfo:
            main(mock_context)

        mock_parse_config.assert_called_once_with(mock_context)
        mock_run.assert_called_once_with(*mock_parse_return_tuple)
        mock_output.assert_not_called()
        mock_add_tags.assert_called_once()
        self.assertEqual(execinfo.value.code, 0)
