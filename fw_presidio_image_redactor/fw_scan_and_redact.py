"""Inheritance from Presidio DicomImageRedactorEngine."""

# Standard imports
import json
import logging
import os
import pathlib
import shutil
import sys
import tempfile
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pydicom
import yaml
from flywheel_gear_toolkit.utils.zip_tools import zip_output
from fw_file.dicom.utils import generate_uid
from PIL import Image

# Presidio required imports
from presidio_analyzer import (
    AnalyzerEngine,
    EntityRecognizer,
    PatternRecognizer,
    RecognizerRegistry,
    RecognizerResult,
)
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import SpacyRecognizer
from presidio_image_redactor import (
    ContrastSegmentedImageEnhancer,
    DicomImageRedactorEngine,
    ImageAnalyzerEngine,
    ImageRescaling,
)
from presidio_image_redactor.entities import ImageRecognizerResult

from fw_presidio_image_redactor.nlp_configs.recognizer_config import (
    BERT_DEID_CONFIGURATION,
)

from .utils.alg_progress_tracking import ProgressTracker
from .utils.bbox_fuser import BboxFuser

# Flywheel custom imports
from .utils.easy_ocr import EasyOCR
from .utils.pretrained_transformer import get_pretrained_transformer_model
from .utils.transformer_recognizer import TransformersRecognizer

log = logging.getLogger(__name__)

# Default parameters
DEFAULT_PADDING_SIZE = 25  # Padding applied to all sides of image
DEFAULT_CROP_RATIO = 0.75  # Crop ratio for image processing
TRANSFORMERS_CONFIG_FILE = "fw_presidio_image_redactor/nlp_configs/transformers.yaml"
MODEL_PATH = "obi/deid_roberta_i2b2"
DEFAULT_PRESIDIO_ENTITIES = [
    "AGE",
    "ZIP",
    "PROFESSION",
    "ORGANIZATION",
    "ID",
    "PERSON",
    "DATE_TIME",
    "PHONE_NUMBER",
    "USERNAME",
    "EMAIL",
    "LOCATION",
]


class FwScanRedactEngine(DicomImageRedactorEngine):
    """Inherits from the DicomImageRedactorEngine, adds additional functionality.

    Args:
        DicomImageRedactorEngine (Class): Microsoft presidio class for manipulating and
        redacting DICOM images

    """

    def __init__(
        self,
        input_files: List[pathlib.PosixPath],
        selected_entities: List[str],
        debug_output_path: Optional[str] = None,
        transformer_score_threshold: int = 30,
        entity_frequency_threshold: int = 30,
        use_metadata: bool = True,
        bbox_fill: str = "contrast",
        original_filename: str = None,
        redact_all_text: bool = False,
    ) -> None:
        """Initializes the Flywheel Scan and Redact Engine.

        Args:
            debug_output_path (Optional[str]): Path for saving debug output
            input_files (List[pathlib.PosixPath]): List of input files
            selected_entities (List[str]): Entities to be searched for by engine
            transformer_score_threshold (int, optional): Confidence score threshold for given entity. Defaults to 30.
            entity_frequency_threshold (int, optional): Percentage of images entity found in to be kept. Defaults to 30.
            use_metadata (bool, optional): Option to use metadata. Defaults to True.
            bbox_fill (str): Fill type for bounding boxes. Default: "contrast".
            original_filename (str): Original filename of input file
            redact_all_text: Flag for redaction of all text, supersedes redact/scan flags

        Returns:
            None
        """
        super().__init__()
        self.transformer_score_threshold = transformer_score_threshold / 100
        self.entity_frequency_threshold = entity_frequency_threshold / 100
        self.ner_entities = []
        self.selected_entities = selected_entities
        self.use_metadata = use_metadata
        self.fill = bbox_fill
        self.original_filename = original_filename
        self.redact_all_text = redact_all_text
        self.original_num_frames = None  # These 3 variables only used for MF
        self.original_num_bytes = []
        self.first_pass_flag = True
        self.entity_counter = 0

        # Init debugging tracking
        self.debug_output_path = Path(debug_output_path) if debug_output_path else None

        # Default image processing values
        self.padding = DEFAULT_PADDING_SIZE
        self.crop_ratio = DEFAULT_CROP_RATIO

        # Initialize analyzer engine using Flywheel tailoring
        self.image_analyzer_engine = None
        self._initialize_image_analyzer_engine()

        # Detect if multi-frame images passed
        self.original_input_files = input_files
        self.input_files, self.multiframe_detected = self.detect_multiframe(
            input_files=input_files
        )

    def _initialize_image_analyzer_engine(
        self,
    ) -> None:
        """Initializes image analyzer engine with Flywheel specific methods."""

        # Set up NLP engine
        get_pretrained_transformer_model()  # ToDo: check influence on model operation
        provider = NlpEngineProvider(
            conf_file=TRANSFORMERS_CONFIG_FILE,
        )
        nlp_engine = provider.create_engine()

        # Create transformer recognizer for use in analyzer engine
        if len(self.selected_entities) < 1:
            raise ValueError("No entities selected for recognition...")

        entities_to_ignore = [
            entity
            for entity in DEFAULT_PRESIDIO_ENTITIES
            if entity not in self.selected_entities
        ]

        if not self.redact_all_text:
            BERT_DEID_CONFIGURATION["LABELS_TO_IGNORE"] = entities_to_ignore
        else:
            BERT_DEID_CONFIGURATION["LABELS_TO_IGNORE"] = []
        transformers_recognizer = TransformersRecognizer(
            model_path=MODEL_PATH,
            supported_entities=self.selected_entities,
        )

        self.spacy_recognizer = SpacyRecognizer()
        self.spacy_recognizer.analyze = self.mod_spacy_analyze

        # Loads previously downloaded model. If none found, download as specified by
        # config. Approx. (~500Mb)
        transformers_recognizer.load_transformer(**BERT_DEID_CONFIGURATION)

        # Add transformers model to the registry & remove spacy recognizer
        registry = RecognizerRegistry(
            recognizers=[
                transformers_recognizer,  # Removed due to redundancy
                self.spacy_recognizer,
            ]
        )

        # Modifications to image_analyzer_engine inheritance & class calls
        self.image_analyzer_engine = ImageAnalyzerEngine(
            analyzer_engine=AnalyzerEngine(
                nlp_engine=nlp_engine,
                supported_languages=["en"],
                registry=registry,
            ),
            image_preprocessor=ContrastSegmentedImageEnhancer(
                image_rescaling=ImageRescaling(factor=2)
            ),
            ocr=EasyOCR(debug_path=self.debug_output_path),
        )

        # Set custom methods
        self.image_analyzer_engine.image_preprocessor.preprocess_image = (
            self.preprocess_image
        )
        self.image_analyzer_engine.map_analyzer_results_to_bounding_boxes = (
            self._map_analyzer_results_to_bounding_boxes
        )
        self.image_analyzer_engine.analyze = self.image_nlp_analyze
        self.image_analyzer_engine.analyzer_engine.analyze = self.nlp_analyze

    def create_phi_recognizer(
        self, dicom_image: pydicom.FileDataset
    ) -> List[PatternRecognizer]:
        """Uses dicom metadata and input entities making a deny list for PHI entities.

        Args:
            dicom_image (pydicom.FileDataset): Pydicom read of dicom image

        Returns:
            List[PatternRecognizer]: List of PHI entities as PatternRecognizer objects

        """
        original_metadata, is_name, is_patient = self._get_text_metadata(dicom_image)
        phi_list = self._make_phi_list(original_metadata, is_name, is_patient)
        deny_recognizer = PatternRecognizer(
            supported_entity="METADATA", deny_list=phi_list
        )

        return [deny_recognizer]

    def add_phi_bounding_boxes(
        self, dicom_instance: pydicom.FileDataset, bbox_coords: List[dict]
    ) -> pydicom.FileDataset:
        """Burns bounding boxes capturing identified PII into dicom pixel data.

        Args:
            dicom_instance (pydicom.FileDataset): DICOM instance to add bounding boxes on
            bbox_coords (list): List containing bounding box coordinate locations

        Returns:
            pydicom.FileDataset: DICOM instance with modified pixel data

        """
        # Create copy
        temp_instance = deepcopy(dicom_instance)

        # Select masking box color

        if self._check_if_greyscale(temp_instance):
            box_color = self._get_most_common_pixel_value(
                temp_instance, self.crop_ratio, self.fill
            )
        else:
            box_color = self._set_bbox_color(temp_instance, self.fill)

        # Apply mask
        array_height, array_width = temp_instance.pixel_array.shape[:2]

        for bbox in bbox_coords:
            top = max(0, bbox["top"])
            left = max(0, bbox["left"])
            right = min(bbox["width"], array_width - 1)
            bottom = min(bbox["height"], array_height - 1)

            # Width of bounding boxes edges increased by 1 for better human readability
            temp_instance.pixel_array[top : top + 1, left:right] = box_color
            temp_instance.pixel_array[bottom - 1 : bottom, left:right] = box_color
            temp_instance.pixel_array[top:bottom, left : left + 1] = box_color
            temp_instance.pixel_array[top:bottom, right - 1 : right] = box_color

        temp_instance.PixelData = temp_instance.pixel_array.tobytes()

        return temp_instance

    def gen_bbox_images(
        self, output_path: pathlib.PosixPath, bbox_coords: dict
    ) -> None:
        """Uses generated bounding box coordinates & overlays boxes onto identified PII.

        Args:
            output_path (pathlib.PosixPath): Location for bounding box images to be saved
            bbox_coords (dict): List of bounding box coordinates

        """
        # Set output location
        bbox_output_path = Path(f"{output_path}/bbox/")
        if not bbox_output_path.exists():
            bbox_output_path.mkdir()

        self._validate_input_files(self.input_files[0])

        # Gen new uid
        uid = generate_uid()

        # Generate bbox images
        for image_path in self.input_files:
            if self.multiframe_detected:
                for multiframe_image_path in image_path:
                    bbox_instance = self.gen_bbox(
                        multiframe_image_path,
                        bbox_coords[multiframe_image_path.stem],
                        uid,
                    )
                    bbox_instance.save_as(
                        f"{bbox_output_path}/bbox_phi_{multiframe_image_path.name}"
                    )
            else:
                bbox_instance = self.gen_bbox(
                    image_path, bbox_coords[image_path.stem], uid
                )
                bbox_instance.save_as(f"{bbox_output_path}/bbox_phi_{image_path.name}")

        if len(self.input_files) > 1 and not self.multiframe_detected:
            zip_output(
                bbox_output_path.parent,
                bbox_output_path,
                f"{bbox_output_path.stem}.dicom.zip",
            )
            shutil.rmtree(bbox_output_path)
        elif self.multiframe_detected:
            self.recompile_multiframe_files(bbox_output_path)

    def gen_bbox(
        self, image_path: pathlib.PosixPath, bbox_coords: List[dict], uid: str
    ) -> pydicom.FileDataset:
        """Calls for bounding boxes to be added to DICOM instance.

        Args:
            image_path (pathlib.PosixPath): File path for image instance
            bbox_coords (List[dict]): Bounding box coordinates to be applied to image
            uid (str): Instance UID for DICOM image

        Returns:
            (pydicom.FileDataset): Dicom instance with bounding boxes applied

        """
        instance = pydicom.dcmread(image_path)
        instance.SeriesInstanceUID = uid
        bbox_instance = self.add_phi_bounding_boxes(instance, bbox_coords)

        return bbox_instance

    def scan_dicoms_for_phi(
        self, gen_bbox_images: bool = False, output_path: pathlib.PosixPath = None
    ) -> Tuple[dict, dict, bool, dict]:
        """Scans input_files for phi and provides output for phi redaction downstream.

        Args:
            gen_bbox_images (bool): Flag to generate bounding boxes. Default=False.
            output_path (pathlib.PosixPath): Path for bounding box images to be saved

        Raises:
            AttributeError: Checks DICOM images for acceptable pixel data

        Returns:
            Tuple[dict,dict, bool, dict]: Dict containing analyzer results with key to image
            name, dict containing bounding box coordinates with image name key, and bool
            indicating if phi found

        """
        # Verify the given paths
        self._validate_input_files(self.input_files[0])
        analyzer_dict = {}
        bbox_coords_dict = {}
        annotation_coords = {}
        total_images = len(self.input_files)

        # Init iteration progress tracking
        FileProgressTracker = ProgressTracker(total_images)
        file_markers = FileProgressTracker.find_quartiles()

        input_file_count = 0
        for _, image_path in enumerate(self.input_files):
            if self.multiframe_detected:
                num_mf_images = len(image_path)
                MfProgressTracker = ProgressTracker(num_mf_images)
                mf_markers = MfProgressTracker.find_quartiles()

                mf_file_count = 0
                for _, multiframe_image_path in enumerate(image_path):
                    (analyzer_results, bbox_coords, instance_metadata) = (
                        self.scan_image(multiframe_image_path)
                    )
                    analyzer_dict[str(multiframe_image_path.stem)] = analyzer_results
                    bbox_coords_dict[str(multiframe_image_path.stem)] = (
                        bbox_coords  # bbox_coords
                    )
                    annotation_coords[instance_metadata["imagePath"]] = bbox_coords

                    mf_file_count += 1
                    if mf_file_count in mf_markers:
                        mf_percentage = mf_markers.get(mf_file_count)
                        log.info("Multiframe scanning progress: %s%%", mf_percentage)

                # Apply common bboxes
                self.apply_common_bboxes(annotation_coords)

            else:
                analyzer_results, bbox_coords, instance_metadata = self.scan_image(
                    image_path
                )
                analyzer_dict[str(image_path.stem)] = analyzer_results
                bbox_coords_dict[str(image_path.stem)] = bbox_coords  # bbox_coords
                annotation_coords[instance_metadata["imagePath"]] = bbox_coords

            input_file_count += 1
            if input_file_count in file_markers:
                file_progress_percent = file_markers.get(input_file_count)
                log.info("Scanning progress: %s%%", file_progress_percent)

            # Save analyzer results for debug
            if self.debug_output_path:
                debug_analyzer_results = (
                    self.debug_output_path / "analyzer_results.yaml"
                )
                with open(debug_analyzer_results, "w") as fp:
                    yaml.dump(analyzer_results, fp, sort_keys=False)

        # Apply common bboxes
        self.apply_common_bboxes(annotation_coords)

        phi_found = any(
            len(phi_check) >= 1 for phi_check in list(analyzer_dict.values())
        )

        if gen_bbox_images and phi_found:
            self.gen_bbox_images(output_path, bbox_coords_dict)

        return analyzer_dict, bbox_coords_dict, phi_found, annotation_coords

    def scan_image(
        self, image_path: pathlib.PosixPath
    ) -> Tuple[List[ImageRecognizerResult], List[dict]]:
        """Scans a single image for PHI entities and returns the results.

        Args:
            image_path (pathlib.PosixPath): Path to image file

        Raises:
            AttributeError: Check if pixel data in DICOM is present

        Returns:
            (Tuple[List[ImageRecognizerResult], List[dict]]): List of analyzer results
            and list of bounding box coordinates
        """
        # Load instance
        instance = pydicom.dcmread(image_path)

        #! Add parallel list alongside analyzer_results_dict containing image metadata elements
        slice_number = instance.get("InstanceNumber", 0)
        study_instance_uid = instance.get("StudyInstanceUID", "")
        series_instance_uid = instance.get("SeriesInstanceUID", "")
        sop_instance_uid = instance.get("SOPInstanceUID", "")
        frame_index = instance.get("frameIndex", 0)
        annotation_metadata = {
            "study_instance_uid": study_instance_uid,
            "series_instance_uid": series_instance_uid,
            "sop_instance_uid": sop_instance_uid,
            "imagePath": f"{study_instance_uid}$$${series_instance_uid}$$${sop_instance_uid}$$${frame_index}***{slice_number}",
        }

        # Check for pixel data
        try:
            instance.PixelData
        except AttributeError:
            raise AttributeError("Provided DICOM file lacks pixel data.")

        # Load image for processing
        with tempfile.TemporaryDirectory() as tmpdirname:
            # Convert DICOM to PNG and add padding for OCR (during analysis)
            _, is_greyscale = self._convert_dcm_to_png(
                image_path, output_dir=tmpdirname
            )
            png_filepath = f"{tmpdirname}/{image_path.stem}.png"
            loaded_image = Image.open(png_filepath)
            image = self._add_padding(loaded_image, is_greyscale, self.padding)
            image.save(png_filepath)

            # Create phi recognizers and analyze
            text_analyzer_kwargs = {
                "score_threshold": self.transformer_score_threshold,
                "return_decision_process": True,
                "entities": self.selected_entities,
            }
            if self.use_metadata:
                text_analyzer_kwargs["ad_hoc_recognizers"] = self.create_phi_recognizer(
                    instance
                )

            # Prevent Noisy print statements from engines & recognizers
            current_stdout = sys.stdout
            sys.stdout = open(os.devnull, "w")

            # Call analyzer, see image_nlp_analyze method for more details
            analyzer_results = self.image_analyzer_engine.analyze(
                png_filepath, **text_analyzer_kwargs
            )

            # Restore stdout
            sys.stdout = current_stdout

        # Remove ignored entities
        unwanted_entities = []
        for i, result in enumerate(analyzer_results):
            if result.entity_type == "O":
                unwanted_entities.append(i)
        analyzer_results = [
            item
            for idx, item in enumerate(analyzer_results)
            if idx not in unwanted_entities
        ]

        # Get bounding boxes utilizing recognized phi
        analyzer_bboxes = self.bbox_processor.get_bboxes_from_analyzer_results(
            analyzer_results
        )

        bbox_coords = self.bbox_processor.remove_bbox_padding(
            analyzer_bboxes, self.padding
        )
        for bbox_dict in bbox_coords:
            bbox_dict["index"] = self.entity_counter
            self.entity_counter += 1
            bbox_dict["slice_number"] = int(slice_number)

        # Presidio `.remove_bbox_padding` method returns only coords
        # Need to add the confidence score back to bbox_coords
        # Iterate over dictionaries in list1 and list2
        for dict1 in analyzer_bboxes:
            for dict2 in bbox_coords:
                # Check if 'entity_type' matches
                if dict1.get("entity_type") == dict2.get("entity_type"):
                    # Add the 'score' key and value from dict1 to dict2
                    dict2["score"] = dict1["score"]

        # Ensures removing padding doesn't return negative values after adjusting scale
        for box_item in bbox_coords:
            box_item["height"] = max(0, box_item["height"] - self.padding)
            box_item["width"] = max(0, box_item["width"] - self.padding)

        return analyzer_results, bbox_coords, annotation_metadata

    def redact_dicom_phi(
        self,
        output_path: pathlib.PosixPath,
        bbox_coords: list,
        double_wash: bool = True,
    ) -> pathlib.PosixPath:
        """Intakes arguments from scanning functions and redacts pixel data accordingly.

        Args:
            output_path (pathlib.PosixPath): Path for redacted DICOM images to be saved
            bbox_coords (list): List of bounding box coordinates
            double_wash (bool): Flag for double washing of redacted images

        Returns:
            pathlib.PosixPath: Path object for redacted DICOM image
        """
        # Verify the given paths
        self._validate_input_files(self.input_files[0])
        redacted_file_paths = []

        # Set output location
        redact_output_path = Path(f"{output_path}/redacted/")
        if not redact_output_path.exists():
            redact_output_path.mkdir()

        # Gen uid
        uid = generate_uid()

        # Init iteration progress tracking
        total_images = len(self.input_files)
        FileProgressTracker = ProgressTracker(total_images)
        file_markers = FileProgressTracker.find_quartiles()

        input_file_count = 0
        for input_files_idx, image_path in enumerate(self.input_files):
            if self.multiframe_detected:
                # Init multiframe progress tracking
                num_mf_images = len(image_path)
                MfProgressTracker = ProgressTracker(num_mf_images)
                mf_markers = MfProgressTracker.find_quartiles()

                mf_file_count = 0
                for mf_files_idx, multiframe_image_path in enumerate(image_path):
                    redacted_file_path = self.redact(
                        multiframe_image_path,
                        bbox_coords[multiframe_image_path.stem],
                        uid,
                        redact_output_path,
                    )
                    redacted_file_paths.append(redacted_file_path)

                    mf_file_count += 1
                    if mf_file_count in mf_markers:
                        mf_percentage = mf_markers.get(mf_file_count)
                        log.info("Multiframe Redaction progress: %s%%", mf_percentage)
            else:
                redacted_file_path = self.redact(
                    image_path,
                    bbox_coords[image_path.stem],
                    uid,
                    redact_output_path,
                )
                redacted_file_paths.append(redacted_file_path)

            input_file_count += 1
            if input_file_count in file_markers:
                redaction_progress = file_markers.get(input_file_count)
                log.info("Redaction progress: %s%%", redaction_progress)

        # Redacted input files will need to be re-split
        if double_wash:
            self.first_pass_flag = False
            if self.multiframe_detected:
                redacted_file_paths, _ = self.detect_multiframe(redacted_file_paths)
                self.input_files = redacted_file_paths
            else:
                self.input_files = redacted_file_paths

            dw_analyzer_results, dw_bbox_coords, dw_phi_found, annotation_coords = (
                self.scan_dicoms_for_phi()
            )

            # If any additional PHI was found, run redaction again
            coords_present = sum([len(value) for value in dw_bbox_coords.values()]) > 1

            # Second redaction will occur with the overwritten set of files
            if coords_present:
                redact_output_path = self.redact_dicom_phi(
                    output_path, dw_bbox_coords, double_wash=False
                )

            # Zip if series
            if len(self.input_files) > 1 and not self.multiframe_detected:
                zip_output(
                    redact_output_path.parent,
                    redact_output_path,
                    f"redacted_{self.original_filename}.dicom.zip",
                )
                shutil.rmtree(redact_output_path)

            elif self.multiframe_detected:
                self.recompile_multiframe_files(redact_output_path)

        return redact_output_path

    def redact(
        self,
        image_path: pathlib.PosixPath,
        bbox_coords: dict,
        uid: str,
        redact_output_path: pathlib.PosixPath,
    ):
        """Redacts the pixel data of a DICOM image based on bounding box coordinates.

        Args:
            image_path (pathlib.PosixPath): Path to DICOM image
            bbox_coords (dict): Bounding box coordinates
            uid (str): Dicom instance UID
            redact_output_path (pathlib.PosixPath): Path to output
        """
        # Read image
        instance = pydicom.dcmread(image_path)
        instance.SeriesInstanceUID = uid

        # Redact and save
        redacted_dicom_instance = self._add_redact_box_flywheel(
            instance, bbox_coords, self.crop_ratio, self.fill
        )
        if "redacted_" in image_path.name:
            redacted_dicom_path = f"{redact_output_path}/{image_path.name}"
        else:
            redacted_dicom_path = f"{redact_output_path}/redacted_{image_path.name}"
        redacted_dicom_instance.save_as(redacted_dicom_path)

        return Path(redacted_dicom_path)

    def run_ocr(self, input_file_path: pathlib.PosixPath) -> list:
        """Utilized for debug for checking the output of the tesseract ocr results.

        Args:
            input_file_path (pathlib.PosixPath): Input file path

        Returns:
            list: list of text identified from running ocr
        """
        instance = pydicom.dcmread(input_file_path)
        ocr_results = self.image_analyzer_engine.ocr.perform_ocr(instance)

        return ocr_results

    def _validate_input_files(self, input_file: pathlib.PosixPath):
        """Validates an input file.

        If the data is multiframe, the input_file should be a list. Otherwise, it should
        be a pathlib.PosixPath object.

        Args:
            input_file (pathlib.PosixPath): file path of an input file

        Raises:
            TypeError: Raises error type if incorrect typing encountered on input
        """
        if not self.multiframe_detected:
            if not isinstance(input_file, pathlib.PosixPath):
                raise TypeError(
                    "Incorrect argument passed. %s is not allowed", type(input_file)
                )
        elif not isinstance(input_file, list):
            raise TypeError(
                "Incorrect argument passed with multi-frame flag. %s is not allowed",
                type(input_file),
            )

    def detect_multiframe(
        self, input_files: List[pathlib.PosixPath]
    ) -> Tuple[List[Union[pathlib.PosixPath, List[pathlib.PosixPath]]], bool]:
        """Detects multi-frame images from input files and parses into separate files.

        Args:
            input_files (List[pathlib.PosixPath]): List of pathlib.PosixPath objects for
            input file paths, or list of lists of pathlib.PosixPath objects

        Returns:
            Tuple[List[pathlib.PosixPath], bool]: Either the original input list, or a
            list of nested lists containing file paths
        """
        # Storage for split us images
        us_dir = Path("separated_us_images")
        if not us_dir.exists():
            us_dir.mkdir(exist_ok=False)
        else:
            shutil.rmtree(us_dir)
            us_dir.mkdir()

        # Iterated through original multi-frame array and separate into separate dcm files
        separated_us_files = []
        total_bytes = 0
        for file in input_files:
            dcm = pydicom.dcmread(file)

            # TODO: This will need to be updated to account for multiple MF files.
            if self.first_pass_flag:  # Checking for first pass
                # During first pass, mf dcm files contain whole multiframe array
                self.original_num_bytes.append(len(dcm.get("PixelData")))

                file_name_stem = f"{us_dir}/{file.stem}"
                file_clips = self.separate_multiframe_array_to_files(
                    dcm=dcm, file_name_stem=file_name_stem
                )

                if len(file_clips) > 0:
                    separated_us_files.append(file_clips)

            else:
                # Second pass, mulfiframes already separated into files
                separated_us_files.append(file)
                total_bytes += len(dcm.get("PixelData"))

        self.separated_us_bytes = total_bytes
        if len(separated_us_files) > 0:
            multiframe_detected = True
            if total_bytes == 0:  #  If var remains 0, second pass not started
                log.info("Multi-frame images detected...")
                return separated_us_files, multiframe_detected

            else:
                return [separated_us_files], multiframe_detected

        else:
            multiframe_detected = False
            return input_files, multiframe_detected

    def separate_multiframe_array_to_files(
        self, dcm: pydicom.Dataset, file_name_stem: pathlib.PosixPath
    ) -> List[pathlib.PosixPath]:
        """Separates multi-frame array into separate files.

        Args:
            dcm (pydicom.Dataset): DICOM instance of interest
            file_name_stem (pathlib.PosixPath): Stem of file name matching original file

        Returns:
            List[pathlib.PosixPath]: List of separated files as pathlib.PosixPath
            objects
        """
        file_clips = []
        keywords = [elem.keyword for elem in dcm]
        if "NumberOfFrames" in keywords:
            if not self.original_num_frames:  # None indicates first pass
                self.original_num_frames = dcm.get("NumberOfFrames")
            else:
                # Second pass needs to have number of original frames reset
                dcm.NumberOfFrames = self.original_num_frames

            if dcm.get("NumberOfFrames", 0) > 1:
                for idx, clip in enumerate(dcm.pixel_array):
                    file_name = f"{file_name_stem}_{idx}.dcm"
                    tmp_dcm = deepcopy(dcm)
                    tmp_dcm.PixelData = clip.tobytes()
                    tmp_dcm.NumberOfFrames = "1"
                    tmp_dcm.save_as(file_name)
                    file_clips.append(Path(file_name))

            return file_clips

        return file_clips

    def recompile_multiframe_files(self, output_path: pathlib.PosixPath) -> None:
        """Takes separated multi-frame files' arrays and recompiles back into original.

        Args:
            output_path (pathlib.PosixPath): Path to output directory

        Raises:
            ValueError: Raised if pixel array shapes are mismatched

        Returns:
            None

        """
        # Iterate through original list of files
        for idx, file in enumerate(self.original_input_files):
            dcm = pydicom.dcmread(file)
            sop_instance_uid = dcm["SOPInstanceUID"].value
            original_pixel_array_shape = dcm.pixel_array.shape
            tmp_pixel_array = []

            # Iterate through separated files
            sorted_separated_files = sorted(output_path.glob("*"))
            for single_frame_file in sorted_separated_files:
                separated_dcm = pydicom.dcmread(single_frame_file)
                separated_sop_instance_uid = separated_dcm["SOPInstanceUID"].value

                # append pixel array if SOP matches
                if not sop_instance_uid == separated_sop_instance_uid:
                    log.warning(
                        "Unexpected SOPInstanceUID found for single frame file %s",
                        "Expected: %s; found: %s \n",
                        single_frame_file,
                        sop_instance_uid,
                        separated_sop_instance_uid,
                    )
                    continue
                (output_path / single_frame_file.name).unlink()
                tmp_pixel_array.append(separated_dcm.pixel_array)
                if len(os.listdir(output_path)) < 1:
                    output_path.rmdir()

            # Check pixel array shape
            tmp_pixel_array = np.array(tmp_pixel_array)
            if tmp_pixel_array.shape != original_pixel_array_shape:
                raise ValueError(
                    f"Pixel array shape mismatch. {tmp_pixel_array.shape} != {original_pixel_array_shape}"
                )
            else:
                uid = generate_uid()
                dcm.PixelData = tmp_pixel_array.tobytes()
                dcm.SeriesInstanceUID = uid
                dcm.NumberOfFrames = self.original_num_frames
                dcm.save_as(
                    Path(f"{output_path.parent}/{output_path.name}_{file.name}")
                )

    def preprocess_image(self, image_path: Image.Image) -> Tuple[Image.Image, dict]:
        """Preprocess the image to be analyzed.

        :param image: Loaded PIL image.

        :return: The processed image and metadata (background color, scale percentage,
        contrast level, and C value).
        """
        image = Image.open(image_path)
        image = self.image_analyzer_engine.image_preprocessor.convert_image_to_array(
            image
        )

        # Apply bilateral filtering
        (
            filtered_image,
            _,
        ) = self.image_analyzer_engine.image_preprocessor.bilateral_filter.preprocess_image(
            image
        )

        # Convert to grayscale
        pil_filtered_image = Image.fromarray(np.uint8(filtered_image))
        pil_grayscale_image = pil_filtered_image.convert("L")
        grayscale_image = np.asarray(pil_grayscale_image)

        # Improve contrast
        (
            adjusted_image,
            _,
            adjusted_contrast,
        ) = self.image_analyzer_engine.image_preprocessor._improve_contrast(
            grayscale_image
        )
        # Taken out due to clashing performance w/ EasyOCR
        # Adaptive Thresholding
        # adaptive_threshold_image, _ = (
        #     self.image_analyzer_engine.image_preprocessor.adaptive_threshold.preprocess_image(
        #         adjusted_image
        #     )
        # )

        # Temporarily taken out to view impact on performance
        # # Increase contrast
        # _, adjusted_image = cv2.threshold(
        #     np.asarray(adjusted_image),
        #     0,
        #     255,
        #     cv2.THRESH_BINARY | cv2.THRESH_OTSU,
        # )
        # Rescale image
        (
            rescaled_image,
            scale_metadata,
        ) = self.image_analyzer_engine.image_preprocessor.image_rescaling.preprocess_image(
            adjusted_image,
        )

        # If debug flag is set, save processed images
        if self.debug_output_path:
            processed_imgs_path = self.debug_output_path / "processed_imgs"
            if not processed_imgs_path.exists():
                processed_imgs_path.mkdir()
            rescaled_image.save(f"{processed_imgs_path}/{Path(image_path).stem}.png")

        rescaled_image.save(image_path)
        return image_path, scale_metadata

    def _map_analyzer_results_to_bounding_boxes(
        self,
        text_analyzer_results: List[RecognizerResult],
        ocr_result: dict,
        text: str,
        allow_list: Optional[List[str]] = None,
    ) -> List[ImageRecognizerResult]:
        """Map the analyzer results to bounding boxes.

        Method taken from ImageAnalyzerEngine.map_analyzer_results_to_bounding_boxes.
        Removed excess processing that was requried when using Tesseract OCR

        Args:
            text_analyzer_results (List[RecognizerResult]): Results from Analyzer
            ocr_result (dict): OCR results
            text (str): Ocr results as single string
            allow_list (Optional[List[str]]): List of words to allow, kept for
            compatibility with original method

        Returns:
            List[ImageRecognizerResult]: List of found entity with associated bbox

        """
        if self.redact_all_text:
            # Only want to keep ImageRecognizerResults w/ highest score
            unique_bboxes = defaultdict(lambda: None)

            # Iterate through the results and update the dictionary
            for index, word in enumerate(ocr_result["text"]):
                bbox = ImageRecognizerResult(
                    f"OCR Result: {index+1}",
                    0,  # Dummy start index value
                    1,  # Dummy end index value
                    ocr_result["conf"][index],  # ocr confidence score
                    ocr_result["left"][index],
                    ocr_result["top"][index],
                    ocr_result["width"][index],
                    ocr_result["height"][index],
                )
                key = f"OCR Result: {index+1}"
                unique_bboxes[key] = bbox

        else:
            # Only want to keep ImageRecognizerResults w/ highest score
            unique_bboxes = defaultdict(lambda: None)

            # Iterate through the results and update the dictionary
            for index, word in enumerate(ocr_result["text"]):
                for element in text_analyzer_results:
                    entity_type_split = element.entity_type.split(", ")
                    entity_type_check = (
                        entity_type_split[1]
                        if len(entity_type_split) > 1
                        else element.entity_type
                    )
                    if (
                        text[element.start : element.end].lower() in word.lower()
                        or word.lower() in entity_type_check
                    ):
                        bbox = ImageRecognizerResult(
                            element.entity_type,
                            element.start,
                            element.end,
                            element.score,
                            ocr_result["left"][index],
                            ocr_result["top"][index],
                            ocr_result["width"][index],
                            ocr_result["height"][index],
                        )
                        key = bbox.entity_type
                        if (
                            unique_bboxes[key] is None
                            or bbox.score > unique_bboxes[key].score
                        ):
                            unique_bboxes[key] = bbox

        # Convert the dictionary values back to a list
        bboxes = list(unique_bboxes.values())

        return bboxes

    #! Method might be causing redaction of the image itself
    # TODO: Review this method & ensure proper retention of coordinates

    def apply_common_bboxes(
        self, bbox_coords: Dict[str, List[Dict]]
    ) -> Dict[str, List[Dict]]:
        """Applies common bounding boxes to all frames.

        Identified PHI that were identified in at least 30% (of threshold specified)
        number of images are added to bounding box coordinates for all images.

        Args:
            bbox_coords (Dict[str, List[Dict]]): Dictionary containing bboxes for associated image file

        Returns:
            Dict[str, List[Dict]]: Returns the bbox_coords with common bboxes added to all dicts that
            didn't have them

        """
        # Flatten all nested dicts
        all_nested_dicts = [
            value_list
            for keys, dict_values in bbox_coords.items()
            for value_list in dict_values
        ]

        FwBboxFuser = BboxFuser()
        fused_boxes = FwBboxFuser.fuse_similar_bboxes(all_nested_dicts)

        for img_name, coord_list in bbox_coords.items():
            new_coord_values = []
            slice_match = int(img_name.split("***")[1])
            for bounding_box in fused_boxes:
                if slice_match in bounding_box[5]:
                    temp_dict = {
                        "left": bounding_box[0],
                        "top": bounding_box[1],
                        "width": bounding_box[2],
                        "height": bounding_box[3],
                        "score": bounding_box[4],
                    }
                    new_coord_values.append(temp_dict)
            bbox_coords[img_name] = new_coord_values

        return bbox_coords

    def _add_redact_box_flywheel(
        self,
        instance: pydicom.dataset.FileDataset,
        bounding_boxes_coordinates: list,
        crop_ratio: float,
        fill: str = "contrast",
    ) -> pydicom.dataset.FileDataset:
        """Add redaction bounding boxes on a DICOM instance.

        :param instance: A single DICOM instance.
        :param bounding_boxes_coordinates: Bounding box coordinates.
        :param crop_ratio: Portion of image to consider when selecting
        most common pixel value as the background color value.
        :param fill: Determines how box color is selected.
        'contrast' - Masks stand out relative to background.
        'background' - Masks are same color as background.

        :return: A new dicom instance with redaction bounding boxes.
        """
        # Copy instance
        redacted_instance = deepcopy(instance)
        is_compressed = self._check_if_compressed(redacted_instance)
        has_image_icon_sequence = self._check_if_has_image_icon_sequence(
            redacted_instance
        )

        # Select masking box color
        is_greyscale = self._check_if_greyscale(instance)
        if is_greyscale:
            box_color = self._get_most_common_pixel_value(instance, crop_ratio, fill)
        else:
            box_color = self._set_bbox_color(redacted_instance, fill)

        # Apply mask
        for i in range(0, len(bounding_boxes_coordinates)):
            bbox = bounding_boxes_coordinates[i]
            top = bbox["top"]
            left = bbox["left"]
            width = bbox["width"]
            height = bbox["height"]
            redacted_instance.pixel_array[top:height, left:width] = box_color

        redacted_instance.PixelData = redacted_instance.pixel_array.tobytes()

        # If original pixel data is compressed, recompress after redaction
        if is_compressed or has_image_icon_sequence:
            # Temporary "fix" to manually set all YBR photometric interp as YBR_FULL
            if "YBR" in redacted_instance.PhotometricInterpretation:
                redacted_instance.PhotometricInterpretation = "YBR_FULL"
            redacted_instance = self._compress_pixel_data(redacted_instance)

        return redacted_instance

    def nlp_analyze(
        self,
        text: str,
        language: str,
        entities: Optional[List[str]] = None,
        correlation_id: Optional[str] = None,
        score_threshold: Optional[float] = None,
        return_decision_process: Optional[bool] = False,
        ad_hoc_recognizers: Optional[List[EntityRecognizer]] = None,
        context: Optional[List[str]] = None,
        allow_list: Optional[List[str]] = None,
        nlp_artifacts: Optional[NlpArtifacts] = None,
    ) -> List[RecognizerResult]:
        """
        Find PII entities in text using different PII recognizers for a given language.

        :param text: the text to analyze
        :param language: the language of the text
        :param entities: List of PII entities that should be looked for in the text.
        If entities=None then all entities are looked for.
        :param correlation_id: cross call ID for this request
        :param score_threshold: A minimum value for which
        to return an identified entity
        :param return_decision_process: Whether the analysis decision process steps
        returned in the response.
        :param ad_hoc_recognizers: List of recognizers which will be used only
        for this specific request.
        :param context: List of context words to enhance confidence score if matched
        with the recognized entity's recognizer context
        :param allow_list: List of words that the user defines as being allowed to keep
        in the text
        :param nlp_artifacts: precomputed NlpArtifacts
        :return: an array of the found entities in the text

        :example:

        >>> from presidio_analyzer import AnalyzerEngine

        >>> # Set up the engine, loads the NLP module (spaCy model by default)
        >>> # and other PII recognizers
        >>> analyzer = AnalyzerEngine()

        >>> # Call analyzer to get results
        >>> results = analyzer.analyze(text='My phone number is 212-555-5555', entities=['PHONE_NUMBER'], language='en') # noqa D501
        >>> print(results)
        [type: PHONE_NUMBER, start: 19, end: 31, score: 0.85]
        """
        all_fields = not entities

        recognizers = (
            self.image_analyzer_engine.analyzer_engine.registry.get_recognizers(
                language=language,
                entities=entities,
                all_fields=all_fields,
                ad_hoc_recognizers=ad_hoc_recognizers,
            )
        )

        if all_fields:
            # Since all_fields=True, list all entities by iterating
            # over all recognizers
            entities = (
                self.image_analyzer_engine.analyzer_engine.get_supported_entities(
                    language=language
                )
            )

        # run the nlp pipeline over the given text, store the results in
        # a NlpArtifacts instance
        if not nlp_artifacts:
            nlp_artifacts = (
                self.image_analyzer_engine.analyzer_engine.nlp_engine.process_text(
                    text, language
                )
            )

        if self.image_analyzer_engine.analyzer_engine.log_decision_process:
            self.image_analyzer_engine.analyzer_engine.app_tracer.trace(
                correlation_id, "nlp artifacts:" + nlp_artifacts.to_json()
            )

        results = []
        for recognizer in recognizers:
            # Lazy loading of the relevant recognizers
            if not recognizer.is_loaded:
                recognizer.load()
                recognizer.is_loaded = True

            # analyze using the current recognizer and append the results
            current_results = recognizer.analyze(
                text=text, entities=entities, nlp_artifacts=nlp_artifacts
            )
            if current_results:
                # add recognizer name to recognition metadata inside results
                # if not exists
                self.image_analyzer_engine.analyzer_engine._AnalyzerEngine__add_recognizer_id_if_not_exists(
                    current_results, recognizer
                )
                results.extend(current_results)

        results = self.image_analyzer_engine.analyzer_engine._enhance_using_context(
            text, results, nlp_artifacts, recognizers, context
        )

        if self.image_analyzer_engine.analyzer_engine.log_decision_process:
            self.image_analyzer_engine.analyzer_engine.app_tracer.trace(
                correlation_id,
                json.dumps([str(result.to_dict()) for result in results]),
            )

        # Remove duplicates or low score results
        results = EntityRecognizer.remove_duplicates(results)
        results = self.image_analyzer_engine.analyzer_engine._AnalyzerEngine__remove_low_scores(
            results, score_threshold
        )

        if allow_list:
            results = self.image_analyzer_engine.analyzer_engine._remove_allow_list(
                results, allow_list, text
            )

        if not return_decision_process:
            results = (
                self.image_analyzer_engine.analyzer_engine.__remove_decision_process(
                    results
                )
            )

        return results

    def mod_spacy_analyze(self, text: str, entities, nlp_artifacts=None):  # noqa D102
        results = []
        if not nlp_artifacts:
            log.warning("Skipping SpaCy, nlp artifacts not provided...")
            return results

        ner_entities = nlp_artifacts.entities
        ner_scores = nlp_artifacts.scores

        for ner_entity, ner_score in zip(ner_entities, ner_scores):
            if ner_entity.label_ not in entities:
                log.debug(
                    f"Skipping entity {ner_entity.label_} "
                    f"as it is not in the supported entities list"
                )
                continue

            textual_explanation = self.spacy_recognizer.DEFAULT_EXPLANATION.format(
                ner_entity.label_
            )
            explanation = self.spacy_recognizer.build_explanation(
                ner_score, textual_explanation
            )
            spacy_result = RecognizerResult(
                entity_type=f"{ner_entity.label_}, {ner_entity.text}",
                start=ner_entity.start_char,
                end=ner_entity.end_char,
                score=ner_score,
                analysis_explanation=explanation,
                recognition_metadata={
                    RecognizerResult.RECOGNIZER_NAME_KEY: self.spacy_recognizer.name,
                    RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.spacy_recognizer.id,
                },
            )
            results.append(spacy_result)

        return results

    def image_nlp_analyze(
        self, image: object, ocr_kwargs: Optional[dict] = None, **text_analyzer_kwargs
    ) -> List[ImageRecognizerResult]:
        """Analyse method to analyse the given image.

        :param image: PIL Image/numpy array or file path(str) to be processed.
        :param ocr_kwargs: Additional params for OCR methods.
        :param text_analyzer_kwargs: Additional values for the analyze method
        in AnalyzerEngine.

        :return: List of the extract entities with image bounding boxes.
        """
        # Perform OCR
        perform_ocr_kwargs, ocr_threshold = (
            self.image_analyzer_engine._parse_ocr_kwargs(ocr_kwargs)
        )
        image, preprocessing_metadata = (
            self.image_analyzer_engine.image_preprocessor.preprocess_image(image)
        )
        ocr_result = self.image_analyzer_engine.ocr.perform_ocr(
            image, **perform_ocr_kwargs
        )

        # No processing needed if no text is found
        if not bool(ocr_result):
            return []

        else:
            ocr_result = self.image_analyzer_engine.remove_space_boxes(ocr_result)
            # Apply OCR confidence threshold if it is passed in
            if ocr_threshold:
                ocr_result = self.image_analyzer_engine.threshold_ocr_result(
                    ocr_result, ocr_threshold
                )

            bboxes = []
            analyzer_result = []
            quadrants = list(set(ocr_result.get("quadrants", None)))

            # If redacting all text, no need for formatting context into quadrants
            if self.redact_all_text:
                # * IDs being found a lot, may need to decrease their score
                # Map the analyzer results to bounding boxes
                full_text = self.image_analyzer_engine.ocr.get_text_from_ocr_dict(
                    ocr_result, separator=", "
                )
                # Get allow list from text_analyzer_kwargs
                allow_list = self.image_analyzer_engine._check_for_allow_list(
                    text_analyzer_kwargs
                )

                if preprocessing_metadata and (
                    "scale_factor" in preprocessing_metadata
                ):
                    ocr_result = self.image_analyzer_engine._scale_bbox_results(
                        ocr_result, preprocessing_metadata["scale_factor"]
                    )
                bboxes = (
                    self.image_analyzer_engine.map_analyzer_results_to_bounding_boxes(
                        text_analyzer_results=analyzer_result,
                        ocr_result=ocr_result,
                        text=full_text,
                        allow_list=allow_list,
                    )
                )

            # To improve the performance of the transformer, text is split into quadrants as relevant medical information is often grouped together
            else:
                for quadrant in quadrants:
                    # Grabbing all ocr identified entities in the relevant quadrant
                    indices = [
                        idx
                        for idx, val in enumerate(ocr_result["quadrants"])
                        if val == quadrant
                    ]

                    # Retain only the relevant data for the quadrant for all results
                    subset_data = {
                        key: [value[i] for i in indices]
                        for key, value in ocr_result.items()
                    }
                    text = self.image_analyzer_engine.ocr.get_text_from_ocr_dict(
                        subset_data, separator=", "
                    )

                    # Get allow list from text_analyzer_kwargs
                    allow_list = self.image_analyzer_engine._check_for_allow_list(
                        text_analyzer_kwargs
                    )

                    if preprocessing_metadata and (
                        "scale_factor" in preprocessing_metadata
                    ):
                        subset_data = self.image_analyzer_engine._scale_bbox_results(
                            subset_data, preprocessing_metadata["scale_factor"]
                        )

                    # Defines English as default language, if not specified
                    if "language" not in text_analyzer_kwargs:
                        text_analyzer_kwargs["language"] = "en"
                    tmp_analyzer_result = (
                        self.image_analyzer_engine.analyzer_engine.analyze(
                            text=text, **text_analyzer_kwargs
                        )
                    )
                    # analyzer_result.extend(tmp_analyzer_result)

                    tmp_bboxes = self.image_analyzer_engine.map_analyzer_results_to_bounding_boxes(
                        text_analyzer_results=tmp_analyzer_result,
                        ocr_result=subset_data,
                        text=text,
                        allow_list=allow_list,
                    )
                    bboxes.extend(tmp_bboxes)

        return bboxes

    @staticmethod
    def check_pixel_data(input_files: List[pathlib.PosixPath]) -> bool:
        """Determines if there is pixel data in the DICOM files.

        Args:
            input_files (List[pathlib.PosixPath]): List of input files

        Returns:
            bool: True if pixel data is present, False otherwise
        """
        for file in input_files:
            dcm_instance = pydicom.dcmread(file)
            try:
                dcm_instance.PixelData
            except AttributeError:
                return False

        return True


if __name__ == "__main__":
    pass
