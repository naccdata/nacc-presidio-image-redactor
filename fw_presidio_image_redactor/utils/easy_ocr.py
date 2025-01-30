"""Class for implementing EasyOCR for use in Presidio."""

import json
import logging
import os
import pathlib
import sys
from pathlib import Path
from typing import Dict, List, Union

import easyocr
from PIL import Image, ImageDraw
from presidio_image_redactor import OCR

# Init logging
log = logging.getLogger(__name__)


class EasyOCR(OCR):
    """Class for implementing EasyOCR for use in Presidio."""

    def __init__(
        self, reader_language: List[str] = ["en"], debug_path: pathlib.PosixPath = None
    ) -> None:
        """Initialize EasyOCR class.

        Inherits from Presidio's OCR abstract class and replaces methods for
        functionality with EasyOCR and for Flywheel needs.

        Args:
            reader_language (list[str], optional): language for character detection.
            Defaults to ["en"].
            debug_path (pathlib.PosixPath) = Path to direct debug output. Defaults to None.

        Returns:
            None

        """
        self.reader_language = reader_language
        self.debug_path = debug_path
        if self.debug_path:
            self.debug_path = debug_path / "EasyOCR"
            if not self.debug_path.exists():
                self.debug_path.mkdir()

    def perform_ocr(self, file_path: str, **kwargs) -> Dict[str, List[Union[int, str]]]:
        """Runs EasyOCR on a given file path.

        Args:
            file_path (str): File path to run OCR on
            kwargs: Additional arguments to pass to EasyOCR

        Returns:
            List[List]: [Left, Top, Width, Height, Conf, Text]


        """
        # EasyOCR has obnoxious print progress bar, silence it
        current_stdout = sys.stdout
        sys.stdout = open(os.devnull, "w")

        # Call EasyOCR
        reader = easyocr.Reader(self.reader_language)

        # Restore stdout
        sys.stdout = current_stdout

        # Perform OCR & process results
        result = reader.readtext(
            file_path,
            width_ths=0.7,  # default 0.5, increased to better group entity bboxes
            add_margin=0.0,  # default 0.1
            contrast_ths=0.1,  # default 0.1
            adjust_contrast=0.5,  # default 0.5
            beamWidth=10,  # default 5
        )

        # If text is found, format results. Else pass empty List
        if len(result) >= 1:
            elements_to_keep = []
            for idx, ele in enumerate(result):
                if ele[2] > 0.6:
                    elements_to_keep.append(ele)
            result = elements_to_keep
            if len(result) > 0:
                formatted_result = self._easy_result_format(result, file_path)

            else:
                formatted_result = {}
                return formatted_result

            # Check for EasyOCR debug directory. If found, save outputs accordingly
            if self.debug_path:
                raw_ocr_file = self.debug_path / f"{Path(file_path).stem}_raw_ocr.json"
                with open(raw_ocr_file, "w") as fp:
                    json.dump(formatted_result["text"], fp)

        else:
            formatted_result = {}

            if self.debug_path:
                raw_ocr_file = self.debug_path / f"{Path(file_path).stem}_raw_ocr.json"
                with open(raw_ocr_file, "w") as fp:
                    json.dump("NO TEXT FOUND", fp)

        return formatted_result

    def _easy_result_format(
        self, easy_result: list, file_path: str
    ) -> Dict[str, List[Union[int, str]]]:
        """Format EasyOCR results into a dictionary.

        Mapping of EasyOCR results performed to mirror expected output that Presidio
        expects from using Tesseract OCR.

        Args:
            easy_result (List): List of EasyOCR results

        Returns:
            dict[str, str]: EasyOCR results formatted for use with Presidio

        """
        image_width, image_height = Image.open(file_path).size

        mid_width = image_width // 2
        mid_height = image_height // 2

        left = []
        top = []
        width = []
        height = []
        text = []
        conf_score = []
        quadrant = []  # 1 = top-left, 2 = top-right, 3 = bottom-left, 4 = bottom-right
        for entry in easy_result:
            bounding_boxes = entry[0]
            text.append(entry[1])
            conf_score.append(entry[2])
            x_min = min(coordinate[0] for coordinate in bounding_boxes)
            x_max = max(coordinate[0] for coordinate in bounding_boxes)

            # Find min and max of y values
            y_min = min(coordinate[1] for coordinate in bounding_boxes)
            y_max = max(coordinate[1] for coordinate in bounding_boxes)

            # Explicitly typecast to int to avoid int64 json serialization error
            width.append(int(x_max))
            left.append(int(x_min))
            top.append(int(y_min))
            height.append(int(y_max))
            tmp_quadrant = self.get_quadrant(x_min, y_min, mid_width, mid_height)
            quadrant.append(int(tmp_quadrant))

        # Sort parallel lists by quadrant
        combined = list(zip(quadrant, left, top, width, height, text, conf_score))
        sorted_combined = sorted(combined, key=lambda x: x[0])
        quadrant, left, top, width, height, text, conf_score = map(
            list, zip(*sorted_combined)
        )

        formatted_output = {
            "left": left,
            "top": top,
            "width": width,
            "height": height,
            "text": text,
            "conf": conf_score,
            "quadrants": quadrant,
        }

        return formatted_output

    def get_text_from_ocr_dict(self, ocr_result: dict, separator: str = " ") -> str:
        """Combine the text from the OCR dict to full text.

        :param ocr_result: dictionary containing the ocr results per word
        :param separator: separator to use when joining the words

        return: str containing the full extracted text as string
        """
        if not ocr_result:
            return ""
        else:
            return separator.join(ocr_result["text"]).lower()

    def _save_test_image(
        self, image_path: str, bbox_results: List[Dict[str, int]]
    ) -> None:
        """Save an image with bounding boxes drawn on it.

        Args:
            image_path (str): Path to image
            bbox_results (List[Dict[str, int]]): List of bounding box coordinates

        """
        image = Image.open(image_path)
        draw = ImageDraw.Draw(image)

        for result_list in bbox_results:
            bounding_box = result_list[0]
            flattened_box = [
                coordinate for point in bounding_box for coordinate in point
            ]
            draw.polygon(flattened_box, outline="red")

        output_path = "/flywheel/v0/output/test_image.png"
        image.save(output_path)

    def get_quadrant(self, left: int, top: int, mid_x: int, mid_y: int) -> str:
        if top < mid_y:
            if left < mid_x:
                return 1
            else:
                return 2
        elif left < mid_x:
            return 3
        else:
            return 4
