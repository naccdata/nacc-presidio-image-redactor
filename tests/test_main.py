"""Module to test main.py"""

import pathlib
from pathlib import Path
from unittest import TestCase
from unittest.mock import mock_open, patch

from pytest import raises

from fw_presidio_image_redactor.main import run


@patch("shutil.make_archive")
@patch("fw_presidio_image_redactor.main.FwScanRedactEngine")
class TestMain(TestCase):
    def setUp(self):
        self.input_args = {
            "debug_path": Path("/some/debug/path"),
            "input_files": [Path("input_files")],
            "operating_mode": "Detection Only",
            "transformer_score_threshold": 0.3,
            "entity_frequency_threshold": 0.3,
            "selected_entities": ["PERSON"],
            "use_metadata": True,
            "bbox_fill": "contrast",
            "original_filename": "original_testfile",
            "prior_scan_inputs": {},
            "output_path": pathlib.Path("output_path"),
            "api_key": "fake-api-key",
            "file_id": "123456789",
            "job_id": "987654321",
            "task_assignees": ["validated_assignees"],
            "bot_key": False,
        }
        self.engine_inputs = {
            "debug_path": Path("/some/debug/path"),
            "input_files": [Path("input_files")],
            "selected_entities": ["PERSON"],
            "transformer_score_threshold": 0.3,
            "entity_frequency_threshold": 0.3,
            "use_metadata": True,
            "bbox_fill": "contrast",
            "original_filename": "original_testfile",
            "redact_all_text": False,
        }

    def test_detection_only(self, mock_fw_engine, mock_make_archive):
        """
        Returns:
            Tuple[int,bool,dict,list]: exit code, phi found flag, bbox_coords, & annotation_coords
        """
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {},
            False,
            {},
        )

        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )
        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(bbox_coords, {})
        self.assertEqual(annotation_coords, {})

    @patch("fw_presidio_image_redactor.main.ReaderTaskCreator")
    def test_detection_reader_tasks(
        self, mock_reader_tasks, mock_fw_engine, mock_make_archive
    ):
        """
        Returns:
            Tuple[int,bool,dict,list]: exit code, phi found flag, bbox_coords, & annotation_coords
        """
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {},
            True,
            {},
        )

        mock_creator = mock_reader_tasks.return_value
        mock_creator.create_reader_protocol.return_value = "fake_protocol_id"
        mock_creator.create_reader_task.return_value = "fake_task_id"
        mock_creator.create_annotations.return_value = "fake_annotations"

        self.input_args["operating_mode"] = "Detection+ReaderTasks"
        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        mock_fw_engine.return_value.redact_dicom_phi.assert_not_called()
        mock_reader_tasks.assert_called_once()
        mock_creator.create_reader_protocol.assert_called_once()
        mock_creator.create_reader_task.assert_called_once()
        mock_creator.create_annotations.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertTrue(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(bbox_coords, {})
        self.assertEqual(annotation_coords, {})

    @patch("fw_presidio_image_redactor.main.ReaderTaskCreator")
    def test_no_phi_reader_tasks(
        self, mock_reader_tasks, mock_fw_engine, mock_make_archive
    ):
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {},
            False,
            {},
        )

        mock_creator = mock_reader_tasks.return_value

        self.input_args["operating_mode"] = "Detection+ReaderTasks"
        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        mock_creator.create_reader_protocol.assert_not_called()
        mock_creator.create_reader_task.assert_not_called()
        mock_creator.create_annotations.assert_not_called()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(bbox_coords, {})
        self.assertEqual(annotation_coords, {})

    def test_dynamic_phi_redaction(self, mock_fw_engine, mock_make_archive):
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {
                "bbox_coords": [{}, {}, {}],  # Representing 3 bounding boxes
            },
            False,
            {},
        )

        self.input_args["operating_mode"] = "Dynamic PHI Redaction"
        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        mock_fw_engine.return_value.redact_dicom_phi.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(
            bbox_coords,
            {
                "bbox_coords": [{}, {}, {}],
            },
        )
        self.assertEqual(annotation_coords, {})

    def test_dynamic_and_user_boxes(self, mock_fw_engine, mock_make_archive):
        mock_fw_engine.check_pixel_data.return_value = True

        self.input_args["prior_scan_inputs"] = {"bbox_coords": [{}, {}, {}]}
        self.input_args["operating_mode"] = "Dynamic PHI Redaction"

        with patch("builtins.open", mock_open(read_data="{}")) as mock_file:
            with patch(
                "json.load", return_value={"bbox_coords": [{}, {}, {}]}
            ) as mock_json:
                e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = (
                    run(**self.input_args)
                )

        mock_make_archive.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_not_called()
        mock_file.assert_called_once()
        mock_json.assert_called_once()
        mock_fw_engine.return_value.redact_dicom_phi.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(
            bbox_coords,
            {
                "bbox_coords": [{}, {}, {}],
            },
        )
        self.assertEqual(annotation_coords, {})

    def test_dynamic_bad_user_boxes(self, mock_fw_engine, mock_make_archive):
        mock_fw_engine.check_pixel_data.return_value = True

        self.input_args["prior_scan_inputs"] = {"bbox_coords": [{}, {}, {}]}
        self.input_args["operating_mode"] = "Dynamic PHI Redaction"

        with patch("builtins.open", mock_open(read_data="{}")) as mock_file:
            with patch("json.load", return_value={"bbox_coords": []}) as mock_json:
                e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = (
                    run(**self.input_args)
                )

        mock_make_archive.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_not_called()
        mock_file.assert_called_once()
        mock_json.assert_called_once()
        mock_fw_engine.return_value.redact_dicom_phi.assert_not_called()
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {},
            False,
            {},
        )

    def test_redact_all_text(self, mock_fw_engine, mock_make_archive):
        """
        Returns:
            Tuple[int,bool,dict,list]: exit code, phi found flag, bbox_coords, & annotation_coords
        """
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {"bbox_coords": [{}, {}, {}]},
            False,
            {},
        )

        self.input_args["operating_mode"] = "RedactAllText"
        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(
            bbox_coords,
            {
                "bbox_coords": [{}, {}, {}],
            },
        )
        self.assertEqual(annotation_coords, {})

    def test_redact_all_no_phi(self, mock_fw_engine, mock_make_archive):
        mock_fw_engine.check_pixel_data.return_value = True
        mock_fw_engine.return_value.scan_dicoms_for_phi.return_value = (
            {},
            {"bbox_coords": []},
            False,
            {},
        )

        self.input_args["operating_mode"] = "RedactAllText"
        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        mock_fw_engine.assert_called_once()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(
            bbox_coords,
            {
                "bbox_coords": [],
            },
        )
        self.assertEqual(annotation_coords, {})

    def test_no_pixel_data(self, mock_fw_engine, mock_make_archive):
        mock_fw_engine.check_pixel_data.return_value = False

        e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
            **self.input_args
        )

        mock_make_archive.assert_called_once()
        mock_fw_engine.check_pixel_data.assert_called_once()
        self.assertEqual(e_code, 0)
        self.assertFalse(phi_found)
        self.assertEqual(analyzer_results, {})
        self.assertEqual(bbox_coords, {})
        self.assertEqual(annotation_coords, {})
        mock_fw_engine.assert_not_called()

    def test_missing_input_files(self, mock_fw_engine, mock_make_archive):
        self.input_args["input_files"] = []

        with raises(ValueError, match="No input files provided..."):
            e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
                **self.input_args
            )
        mock_make_archive.assert_not_called()
        mock_fw_engine.check_pixel_data.assert_not_called()
        mock_fw_engine.assert_not_called()
        mock_fw_engine.return_value.scan_dicoms_for_phi.assert_not_called()
        mock_fw_engine.return_value.redact_dicom_phi.assert_not_called()
