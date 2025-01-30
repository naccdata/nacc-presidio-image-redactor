#!/usr/bin/env python
"""The run script."""

import logging
import sys

from flywheel_gear_toolkit import GearToolkitContext

from fw_presidio_image_redactor.main import run
from fw_presidio_image_redactor.output import add_phi_tags, output_to_fw
from fw_presidio_image_redactor.parser import parse_config

logging.captureWarnings(True)
# Suppress "warnings" from especially noisy packages
noisy_packages = [
    "presidio-analyzer",
    "easyocr.easyocr",
    "py.warnings",
    "torch",
    "PIL.PngImagePlugin",
    "matplotlib.pyplot",
    "transformers",
]
for package in noisy_packages:
    logging.getLogger(package).setLevel(logging.ERROR)
log = logging.getLogger(__name__)


def main(context: GearToolkitContext) -> None:
    """Executes parser and main module of FWE Gear.

    Args:
        context (GearToolkitContext): Flywheel GearToolkit class

    Returns:
        None

    """
    (
        debug_path,
        input_files,
        operating_mode,
        transformer_score_threshold,
        entity_frequency_threshold,
        selected_entities,
        use_metadata,
        bbox_fill,
        original_filename,
        prior_scan_inputs,
        output_path,
        api_key,
        file_id,
        job_id,
        validated_assignees,
        bot_key,
    ) = parse_config(context)

    e_code, phi_found, analyzer_results, bbox_coords, annotation_coords = run(
        debug_path,
        input_files,
        operating_mode,
        transformer_score_threshold,
        entity_frequency_threshold,
        selected_entities,
        use_metadata,
        bbox_fill,
        original_filename,
        prior_scan_inputs,
        output_path,
        api_key,
        file_id,
        job_id,
        validated_assignees,
        bot_key,
    )

    if phi_found:
        log.info("PHI identified. Creating report... ")
        output_to_fw(analyzer_results, bbox_coords, context, annotation_coords)

    else:
        log.info("No PHI identified...")
        log.info("No CSV or bounding box images created...")
        add_phi_tags(context=context, tag="PHI-Not-Found")

    sys.exit(e_code)


if __name__ == "__main__":
    with GearToolkitContext() as gear_context:
        gear_context.init_logging()
        main(gear_context)
