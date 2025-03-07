"""Main module."""

import json
import logging
import pathlib
import shutil
from typing import List, Optional, Tuple

from fw_presidio_image_redactor.fw_scan_and_redact import FwScanRedactEngine
from fw_presidio_image_redactor.utils.reader_tasks import ReaderTaskCreator

log = logging.getLogger(__name__)


def run(
    debug_path: Optional[str],
    input_files: List[pathlib.PosixPath],
    operating_mode: str,
    transformer_score_threshold: int,
    entity_frequency_threshold: int,
    selected_entities: List[str],
    use_metadata: bool,
    bbox_fill: str,
    original_filename: str,
    prior_scan_inputs: dict,
    output_path: pathlib.PosixPath,
    api_key: str,
    file_id: str,
    job_id: str,
    task_assignees: List[str],
    bot_key: bool,
) -> Tuple[int, bool, dict, list]:
    """Redacts PII entities from dicom images.

    Args:
        debug_path (Optional[str]): Flag for triggering save of debug output files
        input_files (List[pathlib.PosixPath]): List of pathlib objects for input file paths
        scan_flag (bool): Bool flag for directing gear to scan or redact images
        bbox_images_flag (bool): Bool flag dictating if bounding box images to be created
        transformer_score_threshold (int): Threshold for NER transformer model
        entity_frequency_threshold (int): Threshold for entity frequency in multi-frame dicoms
        selected_entities (List[str]): List of entities to inspect
        use_metadata (bool): Bool flag for using metadata in scan
        bbox_fill (str): String for bounding box fill type
        original_filename (str): Original filename of input file
        prior_scan_inputs (dict): Dictionary containing the results of a previous run
        output_path (pathlib.PosixPath): Path object for output file path
        api_key (str): API key for Flywheel
        file_id (str): File ID for Flywheel
        job_id (str): Job ID for gear run
        task_assignees (List[str]): List of assignees for ReaderTask
        bot_key (bool): Flag for if FW bot API key is being used

    Returns:
        Tuple[int,bool,dict,list]: Returns exit code, phi found flag, and findings dicts

    """
    if len(input_files) < 1:
        raise ValueError("No input files provided...")
    if debug_path:
        shutil.make_archive(
            base_name=debug_path.stem, format="zip", root_dir=debug_path.parent
        )

    phi_found, analyzer_results, bbox_coords, annotation_coords = False, {}, {}, {}

    # Check for pixel data
    pixel_data_found = FwScanRedactEngine.check_pixel_data(input_files=input_files)
    if not pixel_data_found:
        log.info("No pixel data found in input images, skipping scan and redaction...")

        return 0, phi_found, analyzer_results, bbox_coords, annotation_coords

    # Engine init
    engine = FwScanRedactEngine(
        debug_output_path=debug_path,
        input_files=input_files,
        selected_entities=selected_entities,
        transformer_score_threshold=transformer_score_threshold,
        entity_frequency_threshold=entity_frequency_threshold,
        use_metadata=use_metadata,
        bbox_fill=bbox_fill,
        original_filename=original_filename,
        redact_all_text=False,
    )

    # Detection Only
    if operating_mode == "Detection Only":
        log.info("Detection Only flag encountered...")

        # Scan input images
        analyzer_results, bbox_coords, phi_found, annotation_coords = (
            engine.scan_dicoms_for_phi(
                gen_bbox_images=True,
                output_path=output_path,
            )
        )

    # Detection w/ ReaderTasks
    elif operating_mode == "Detection+ReaderTasks":
        log.info("Detection+ReaderTasks flag encountered...")

        # Scan input images
        (analyzer_results, bbox_coords, phi_found, annotation_coords) = (
            engine.scan_dicoms_for_phi(
                gen_bbox_images=False,  # No bbox images w/ ReaderTasks
                output_path=output_path,
            )
        )
        if phi_found:
            # Create ReaderProtocol,task, & annotations from scan results
            PresidioReaderTaskCreator = ReaderTaskCreator(
                api_key=api_key, file_id=file_id, job_id=job_id, bot_key=bot_key
            )
            protocol_id = PresidioReaderTaskCreator.create_reader_protocol()
            task_id = PresidioReaderTaskCreator.create_reader_task(
                assignees=task_assignees
            )
            PresidioReaderTaskCreator.create_annotations(annotation_coords)
            log.info(
                "ReaderTask created from protocol {%s} and task {%s}",
                protocol_id,
                task_id,
            )
        else:
            log.info("No PHI found, ReaderTask not created...")

    # Dynamic PHI Redaction
    elif operating_mode == "Dynamic PHI Redaction":
        log.info("Dynamic Redaction flag encountered...")

        # No scan inputs, run scan
        if not prior_scan_inputs.get("bbox_coords"):
            analyzer_results, bbox_coords, phi_found, annotation_coords = (
                engine.scan_dicoms_for_phi()
            )

        # Prior scan, user inputs used
        else:
            phi_found = False
            analyzer_results = {}
            with open(prior_scan_inputs.get("bbox_coords")) as fp:
                bbox_coords = json.load(fp)

        # Redact phi
        no_coords_present = sum([len(value) for value in bbox_coords.values()]) < 1
        if no_coords_present:
            log.info("No bounding box coordinates found, skipping redaction...")
        else:
            engine.redact_dicom_phi(output_path, bbox_coords, double_wash=True)

    # Redact All Text
    elif operating_mode == "RedactAllText":
        log.info("Complete redaction flag encountered...")
        engine.redact_all_text = True

        # Not checking for prior scan inputs from user since redacting all text
        analyzer_results, bbox_coords, phi_found, annotation_coords = (
            engine.scan_dicoms_for_phi()
        )

        # Redact phi
        no_coords_present = sum([len(value) for value in bbox_coords.values()]) < 1
        if no_coords_present:
            log.info("No bounding box coordinates found, skipping redaction...")
        else:
            engine.redact_dicom_phi(output_path, bbox_coords, double_wash=True)

    return 0, phi_found, analyzer_results, bbox_coords, annotation_coords
