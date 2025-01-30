"""Module to test output.py"""

# import json
# import unittest
# from io import StringIO
# from unittest.mock import MagicMock, patch

# import pandas as pd
# import presidio_image_redactor
# from flywheel_gear_toolkit import GearToolkitContext

# from fw_presidio_image_redactor.output import (
#     check_add_phi_tags,
#     create_custom_data,
#     create_df_list_and_concat,
#     df_to_csv,
# )


# class TestOutput(unittest.TestCase):
#     def setUp(self):
#         self.context = MagicMock(spec=GearToolkitContext)
#         self.test_df = pd.DataFrame({"A": [1, 2, 3], "B": [4, 5, 6]})
#         self.test_filename = "Test_FileName"
#         self.bbox_coords = {
#             "Test_ImgName": {"top": 5, "left": 10, "height": 15, "width": 20}
#         }

#     @patch("io.StringIO", new_callable=StringIO)
#     def test_df_to_csv(self, mock_strIO):
#         # Mock output
#         self.context.open_output.return_value.__enter__.return_value = mock_strIO

#         # Run function
#         df_to_csv(self.test_df, self.test_filename, self.context)

#         # Check results
#         expected_results = self.test_df.to_csv(index=False)
#         actual_results = mock_strIO.getvalue()
#         self.assertEqual(expected_results, actual_results)

#         # Check commands ran
#         self.context.open_output.assert_called_once()

#     @patch("io.StringIO", new_callable=StringIO)
#     def test_create_custom_data(self, mock_strIO):
#         # Mock output
#         self.context.open_output.return_value.__enter__.return_value = mock_strIO

#         # Run function
#         create_custom_data(self.bbox_coords, self.test_filename, self.context)

#         # Check results
#         mock_file_output = StringIO()
#         json.dump(self.bbox_coords, mock_file_output)
#         self.assertEqual(mock_file_output.getvalue(), mock_strIO.getvalue())

#         # Check command ran
#         self.context.open_output.assert_called_once()

#     def test_check_add_phi_tags(self):
#         # Mock output
#         mock_fw_container = MagicMock()
#         mock_fw_container.tags.return_value = ["Giant_Tree", "Pink_Frog"]
#         self.context.metadata = MagicMock()
#         check_add_phi_tags(mock_fw_container, self.context)

#         # Check add_file_tags called w/ correct args
#         self.context.metadata.add_file_tags.assert_called_with(
#             mock_fw_container, "PHI-Found"
#         )

#     @patch("fw_presidio_image_redactor.output.pd.DataFrame.from_dict")
#     @patch.object(presidio_image_redactor, "entities")
#     def test_create_df_list_and_concat(
#         self, mock_sub_analyzer_result, mock_df_from_dict
#     ):
#         # Mock input
#         mock_df = pd.DataFrame(
#             {
#                 "column1": [1, 2, 3, 4, 5],
#                 "column2": ["a", "b", "c", "d", "e"],
#                 "analysis_explanation": [0, 0, 0, 0, 0],
#                 "recognition_metadata": [0, 0, 0, 0, 0],
#             }
#         ).transpose()
#         mock_df_from_dict.return_value = mock_df
#         mock_image_recognizer_result = MagicMock()
#         mock_sub_analyzer_result.image_recognizer_results.ImageRecognizerResult = (
#             mock_image_recognizer_result
#         )
#         mock_analyzer_results = {"fake_scan_slice": [mock_sub_analyzer_result]}

#         # Run function, .image_recognizer_results.ImageRecognizerResult
#         mock_output_df = create_df_list_and_concat(mock_analyzer_results)

#         # Check output
#         self.assertIsInstance(mock_output_df, pd.DataFrame)
#         self.assertIn("variable", mock_output_df.columns)
#         self.assertNotIn("recognition_metadata", mock_output_df.columns)

# if __name__ == "__main__":
#     unittest.main()
