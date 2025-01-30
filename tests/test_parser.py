"""Module to test parser.py"""

from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from flywheel_gear_toolkit import GearToolkitContext
from pytest import raises

from fw_presidio_image_redactor.parser import (
    detect_and_unpack_zip,
    parse_config,
    remove_file_suffix,
    validate_assignees,
)


class TestParser(TestCase):
    def setUp(self):
        self.mock_context = MagicMock(spec=GearToolkitContext)
        self.mock_site_all_roles = [
            {
                "actions": ["action1"],
                "default_flywheel_role": "role1",
                "id": "id_string",
                "in_use": True,
                "label": "some_label",
            }
        ]

    @patch("fw_presidio_image_redactor.parser.zipfile.is_zipfile")
    @patch("fw_presidio_image_redactor.parser.Path.glob")
    @patch("fw_presidio_image_redactor.parser.Path")
    def test_detect_and_unpack_zip(self, mock_path, mock_glob, mock_is_zipfile):
        mock_is_zipfile.return_value = True
        mock_path.side_effect = [mock_path, Path("tmpdir/unpacked_file.txt")]

        mock_file = MagicMock()
        mock_file.is_file.return_value = True
        mock_file_path = Path("tmpdir/unpacked_file.txt")
        mock_file.return_value = mock_file_path

        mock_glob.return_value = [mock_file]

        # Function Run
        with patch("fw_presidio_image_redactor.parser.zipfile.ZipFile") as mock_zfile:
            input_files = detect_and_unpack_zip("a_fake_file.zip")

        mock_is_zipfile.assert_called_once_with("a_fake_file.zip")
        mock_zfile.return_value.__enter__().extractall.assert_called_once_with(
            mock_path
        )
        mock_glob.assert_called_once_with("**/*")
        self.assertEqual(input_files, [Path("tmpdir/unpacked_file.txt")])

    @patch("fw_presidio_image_redactor.parser.zipfile.is_zipfile")
    def test_detect_and_unpack_zip_without_zipfile(self, mock_is_zipfile):
        # Set up mocks
        mock_is_zipfile.return_value = False  # Simulate that the file is not a zip file

        # Function Run
        input_files = detect_and_unpack_zip(Path("test.txt"))

        # Assertions
        mock_is_zipfile.assert_called_once_with(Path("test.txt"))
        self.assertEqual(input_files, [Path("test.txt")])

    def test_remove_file_suffix(self):
        mock_file_names = "my_mock_file.dcm.zip"

        # Function Run
        file_name = remove_file_suffix(mock_file_names)

        self.assertEqual(file_name, "my_mock_file")

    @patch(
        "fw_presidio_image_redactor.parser.validate_assignees",
        return_value=["some_user_email", "another_user_email"],
    )
    def test_parse_config_no_debug_no_mode(self, mock_validate_assignees):
        mock_context = self.mock_context
        mock_context.config.get.side_effect = [
            None,
            None,
            "some_user_email, another_user_email",
            None,
        ]

        # Function Run
        with raises(SystemExit) as excinfo:
            with raises(
                ValueError,
                match="Invalid operating mode selected or none found, exiting...",
            ):
                tuple_return = parse_config(mock_context)

        mock_context.config.get.call_count == 3
        mock_context.config.get.assert_has_calls(
            [
                call("Debug", None),
                call("Assignees", None),
                call("Baseline Operating Mode", None),
            ]
        )
        mock_context.work_dir.__truediv__.assert_called_with("debug_output")
        mock_context.work_dir.mkdir.assert_not_called()
        self.assertEqual(excinfo.value.code, 1)
        try:
            tuple_return
        except UnboundLocalError:
            assert True

    @patch(
        "fw_presidio_image_redactor.parser.validate_assignees",
        return_value=["some_user_email", "another_user_email"],
    )
    def test_parse_config_bad_fill_string(self, mocke_validate_assignees):
        mock_context = self.mock_context
        mock_context.config.get.side_effect = [
            None,
            "/fake/dir/path",
            "some_user_email, another_user_email",
            "opMode",
            30,
            30,
            "red",
        ]

        # Function Run
        with raises(SystemExit) as excinfo:
            tuple_return = parse_config(mock_context)

        mock_context.config.get.call_count == 6
        mock_context.config.get.assert_has_calls(
            [
                call("Debug", None),
                call("Assignees", None),
                call("Baseline Operating Mode", None),
                call("Transformer Score Threshold", 30),
                call("Entity Frequency Threshold", 30),
                call("Bounding Box Fill", None),
            ]
        )
        self.assertEqual(excinfo.value.code, 1)
        try:
            tuple_return
        except UnboundLocalError:
            assert True

    @patch(
        "fw_presidio_image_redactor.parser.validate_assignees",
        return_value=["some_user_email", "another_user_email"],
    )
    def test_parse_config_no_entities(self, mocke_validate_assignees):
        self.mock_context.config.get.side_effect = [
            None,
            "/fake/dir/path",
            "some_user_email, another_user_email",
            "opMode",
            30,
            30,
            "contrast",
            "contrast",
            False,
            None,
        ]

        # Function Run
        with raises(SystemExit) as excinfo:
            tuple_return = parse_config(self.mock_context)

        self.mock_context.config.get.call_count == 6
        self.mock_context.config.get.assert_has_calls(
            [
                call("Debug", None),
                call("Assignees", None),
                call("Baseline Operating Mode", None),
                call("Transformer Score Threshold", 30),
                call("Entity Frequency Threshold", 30),
                call("Bounding Box Fill", None),
                call(
                    "Bounding Box Fill",
                ),
                call("Use Dicom Metadata", False),
                call("Entities to Find", None),
            ]
        )
        self.assertEqual(excinfo.value.code, 1)
        mocke_validate_assignees.assert_called_once()
        try:
            tuple_return
        except UnboundLocalError:
            assert True

    @patch("fw_presidio_image_redactor.parser.remove_file_suffix")
    @patch("fw_presidio_image_redactor.parser.detect_and_unpack_zip")
    @patch("fw_presidio_image_redactor.parser.json.load")
    @patch("fw_presidio_image_redactor.parser.validate_assignees")
    def test_parse_config_correct_input(
        self,
        mock_validate_assignees,
        mock_json_load,
        mock_detect_zip,
        mock_remove_suffix,
    ):
        mock_validate_assignees.return_value = ["some_user_email", "another_user_email"]
        mock_entities = MagicMock()
        mock_entities.split.return_value = ["entity1", "entity2", "entity3"]
        mock_debug_path = MagicMock()
        mock_debug_path.return_value = "/fake/debug/path"
        mock_debug_path.exists.return_value = False
        self.mock_context.work_dir.__truediv__.return_value = mock_debug_path
        self.mock_context.config.get.side_effect = [
            None,
            mock_debug_path,
            "some_user_email, another_user_email",
            "opMode",
            30,
            30,
            "contrast",
            "contrast",
            False,
            mock_entities,
        ]
        self.mock_context.get_input_path.side_effect = [
            "fake/file/path",
            [{}, {}, {}],
        ]

        self.mock_context.get_input_filename.return_value = "fake_file.zip"
        mock_remove_suffix.return_value = "fake_file"
        self.mock_context.get_input.return_value = {"key": "fake_api_key"}
        self.mock_context.get_input_file_object.return_value = {
            "file_id": "fake_file_id"
        }
        self.mock_context.output_dir = Path("/fake/out/path")
        mock_detect_zip.return_value = [Path("fake_file_path")]
        mock_json_load.return_value = {"job": {"id": "fake_job_id"}}

        # Function Run
        with patch("builtins.open", create=True) as mock_open:
            tuple_return = parse_config(self.mock_context)

        self.mock_context.config.get.call_count == 9
        mock_validate_assignees.assert_called_once()
        self.mock_context.config.get.assert_has_calls(
            [
                call("Debug", None),
                call("Assignees", None),
                call("Baseline Operating Mode", None),
                call("Transformer Score Threshold", 30),
                call("Entity Frequency Threshold", 30),
                call("Bounding Box Fill", None),
                call(
                    "Bounding Box Fill",
                ),
                call("Use Dicom Metadata", False),
                call("Entities to Find", None),
            ]
        )
        self.mock_context.get_input_path.assert_has_calls(
            [
                call(
                    "image_file",
                ),
                call(
                    "bbox_coords",
                ),
            ]
        )

        mock_detect_zip.assert_called_once()
        mock_remove_suffix.assert_called_once_with("fake_file.zip")
        self.mock_context.get_input_filename.assert_called_once_with("image_file")
        self.mock_context.get_input.assert_called_once_with("api-key")
        self.mock_context.get_input_file_object.assert_called_once_with("image_file")
        mock_open.assert_called_once()
        mock_debug_path.mkdir.assert_called_once()

        self.assertEqual(
            tuple_return,
            (
                mock_debug_path,
                [Path("fake_file_path")],
                "opMode",
                30,
                30,
                ["entity1", "entity2", "entity3"],
                False,
                "contrast",
                "fake_file",
                {"bbox_coords": [{}, {}, {}]},
                Path("/fake/out/path"),
                "fake_api_key",
                "fake_file_id",
                "fake_job_id",
                ["some_user_email", "another_user_email"],
                False,
            ),
        )

    def test_validate_assignees_bad_assignees(self):
        mock_context = self.mock_context
        mock_context.client.get_all_roles.return_value = self.mock_site_all_roles

        # Function Run
        mock_assignees = ""
        with raises(SystemExit) as excinfo:
            validated_assignees = validate_assignees(
                context=mock_context,
                assignees=mock_assignees,
                file_id="fake_file_id",
            )

        self.assertEqual(excinfo.value.code, 1)
        try:
            validated_assignees
        except UnboundLocalError:
            assert True

    def test_validate_assignees_not_on_project(self):
        mock_context = self.mock_context
        mock_context.client.get_all_roles.return_value = self.mock_site_all_roles

        mock_file_container = MagicMock()
        mock_project_container = {
            "permissions": [
                {"_id": "some_user_email", "role_ids": "id_string"},
                {"_id": "different_user_email", "role_ids": "id_string"},
            ]
        }
        mock_context.client.get_file.return_value = mock_file_container
        mock_context.client.get.return_value = mock_project_container
        mock_file_container.parents.get.return_value = "fake_project_id"

        mock_assignees = "some_user_email, another_user_email"

        # Function Run
        with raises(SystemExit) as excinfo:
            validated_assignees = validate_assignees(
                context=mock_context,
                assignees=mock_assignees,
                file_id="fake_file_id",
            )

        mock_context.client.get_file.assert_called_once_with("fake_file_id")
        mock_context.client.get.assert_called_once_with("fake_project_id")
        self.assertEqual(excinfo.value.code, 1)
        try:
            validated_assignees
        except UnboundLocalError:
            assert True

    def test_validate_assignees_insufficient_actions(self):
        mock_context = self.mock_context
        mock_context.client.get_all_roles.return_value = self.mock_site_all_roles

        mock_file_container = MagicMock()
        mock_project_container = {
            "permissions": [
                {"_id": "some_user_email", "role_ids": ["fake_id_string"]},
                {"_id": "another_user_email", "role_ids": ["bad_id_string"]},
            ]
        }
        mock_context.client.get_file.return_value = mock_file_container
        mock_context.client.get.return_value = mock_project_container
        mock_file_container.parents.get.return_value = "fake_project_id"
        mock_assignees = "some_user_email, another_user_email"
        mock_context.client.get_role.side_effect = [
            {
                "actions": [
                    "annotations_edit_others",
                    "annotations_manage",
                    "annotations_view_others",
                    "form_responses_view_others",
                    "reader_task_view",
                ],
                "in_use": True,
            },
            {
                "actions": [
                    "annotations_edit_others",
                    "annotations_manage",
                    "annotations_view_others",
                    "not_form_responses_view_others",
                    "not_reader_task_view",
                ],
                "in_use": True,
            },
        ]

        # Function Run
        with raises(SystemExit) as excinfo:
            validated_assignees = validate_assignees(
                context=mock_context,
                assignees=mock_assignees,
                file_id="fake_file_id",
            )

        mock_context.client.get_file.assert_called_once_with("fake_file_id")
        mock_context.client.get.assert_called_once_with("fake_project_id")
        self.assertEqual(excinfo.value.code, 1)
        try:
            validated_assignees
        except UnboundLocalError:
            assert True

    def test_validate_assignees_correct_input(self):
        mock_context = self.mock_context
        mock_context.client.get_all_roles.return_value = self.mock_site_all_roles

        mock_file_container = MagicMock()
        mock_project_container = {
            "permissions": [
                {"_id": "some_user_email", "role_ids": ["fake_id_string"]},
                {"_id": "another_user_email", "role_ids": ["bad_id_string"]},
            ]
        }
        mock_context.client.get_file.return_value = mock_file_container
        mock_context.client.get.return_value = mock_project_container
        mock_file_container.parents.get.return_value = "fake_project_id"
        mock_assignees = "some_user_email, another_user_email"
        mock_context.client.get_role.side_effect = [
            {
                "actions": [
                    "annotations_edit_others",
                    "annotations_manage",
                    "annotations_view_others",
                    "form_responses_view_others",
                    "reader_task_view",
                ],
                "in_use": True,
            },
            {
                "actions": [
                    "annotations_edit_others",
                    "annotations_manage",
                    "annotations_view_others",
                    "form_responses_view_others",
                    "reader_task_view",
                ],
                "in_use": True,
            },
        ]

        # Function Run
        validated_assignees = validate_assignees(
            context=mock_context,
            assignees=mock_assignees,
            file_id="fake_file_id",
        )

        mock_context.client.get_file.assert_called_once_with("fake_file_id")
        mock_context.client.get.assert_called_once_with("fake_project_id")
        self.assertEqual(validated_assignees, ["some_user_email", "another_user_email"])
