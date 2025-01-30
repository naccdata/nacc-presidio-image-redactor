"""Takes results and adds to Flywheel."""

import json
import logging
import os

import pandas as pd
from flywheel_gear_toolkit import GearToolkitContext

log = logging.getLogger(__name__)


def output_to_fw(
    analyzer_results: dict,
    bbox_coords: dict,
    context: GearToolkitContext,
    annotation_coords: dict,
) -> int:
    """Parses outputs and pushes results to Flywheel.

    Args:
        analyzer_results (dict): Dictionary containing image specific analyzer results
        bbox_coords (dict): Dictionary containing bbox coordinates for each image
        context (GearToolkitContext): Flywheels GearToolkit class

    Returns:
        int: Return code

    """
    # Write dataframe to csv file
    final_df = create_df_list_and_concat(analyzer_results)
    file_name = f"PHI_Info.{context.manifest['name']}.{context.manifest['version']}"
    df_to_csv(final_df, file_name, context)

    # Write analysis results and bbox_coords as json outputs
    bbox_output_filepath = f"bbox_coords_{context.manifest['version']}.json"
    anno_output_filepath = f"annotation_coords_{context.manifest['version']}.json"
    create_custom_data(bbox_coords, bbox_output_filepath, context)
    create_custom_data(annotation_coords, anno_output_filepath, context)

    # Add PHI tag to containers
    add_phi_tags(context)

    return 0


def create_df_list_and_concat(analyzer_results: dict) -> pd.DataFrame:
    """Creates dataframe from Presidio analyzer results.

    Utility function that creates a list of dataframes from each dictionary key
    provided by the input argument.

    Args:
        analyzer_results (dict): A dictionary containing the identified PHI from the
        image(s) passed into the gear.

    Returns:
        pd.DataFrame: Dataframe created from concatenating list of melt dataframes
        containing all identified PHI.

    """
    df_list = []
    for key, value in analyzer_results.items():
        if len(value) > 0:
            analyzer_results_dict = {i: value[i].to_dict() for i in range(len(value))}

            df = pd.DataFrame.from_dict(analyzer_results_dict).transpose()
            df = df.drop(columns=["analysis_explanation", "recognition_metadata"])
            df["image_name"] = key
            df.index.name = "id"
            melt_df = pd.melt(
                df.reset_index(), id_vars="id", value_vars=df.columns
            ).sort_values(by="id")

            df_list.append(melt_df)

    final_df = pd.concat(df_list)

    return final_df


def df_to_csv(
    dataframe: pd.DataFrame, file_name: str, context: GearToolkitContext
) -> None:
    """Saves dataframe to csv file.

    Args:
        dataframe (pd.DataFrame): Pandas dataframe object
        file_name (str): String for name of the output file
        context (GearToolkitContext): FW gear context for directing output dir

    Returns:
        None

    """
    with context.open_output(f"{file_name}.csv") as fp:
        dataframe.to_csv(fp, index=False, header=True)


def add_phi_tags(context: GearToolkitContext, tag: str = "PHI-Found") -> None:
    """Applies 'PHI-Found' tag to acquisition & file containers on FW.

    Args:
        context (GearToolkitContext): FW GearToolkitContext

    Returns:
        None
    """
    # Get current parent container tags to not overwrite them
    dest_container = context.client.get(context.destination.get("id"))
    current_tags_parent = dest_container.tags if dest_container.tags else []
    tags_to_add = [tag, "presidio-image-redactor"]
    for fw_tag in tags_to_add:
        if fw_tag not in current_tags_parent:
            current_tags_parent.append(fw_tag)
    parent_metadata_to_update = {"tags": current_tags_parent}

    # Get current file containe tags to not overwrite them
    current_file_tags = context.get_input_file_object("image_file").get("tags")
    for fw_tag in tags_to_add:
        if fw_tag not in current_file_tags:
            current_file_tags.append(fw_tag)
    file_metadata_to_update = {"tags": current_file_tags}

    # Add PHI tag to acquisition container
    context.metadata.update_container(
        container_type=context.destination.get("type"), **parent_metadata_to_update
    )

    # Add tags to file container
    file_name = context.get_input("image_file").get("location").get("name")
    context.metadata.update_file(file_name, **file_metadata_to_update)

    log.info(
        "Tagged %s and %s containers with '%s'",
        context.destination.get("type"),
        file_name,
        tag,
    )

    # Add tag to redacted files
    prefix = "redacted"
    for file in os.listdir(context.output_dir):
        if file.startswith(prefix):
            context.metadata.update_file(file, tags=["presidio-redacted"])
            log.info("Tagged %s with 'presidio-redacted'", file)


def create_custom_data(
    bbox_coords: dict, output_path: str, context: GearToolkitContext
) -> None:
    """Dumps bounding box coordinate dict into json to be uploaded as custom data.

    Args:
        bbox_coords (dict): Dictionary with bounding box coordinates
        output_path (str): String filepath
        context (GearToolkitContext): FW GearToolkitContext

    Returns:
        None
    """
    for img_name, coords_list in bbox_coords.items():
        for coord_dict in coords_list:
            coord_dict["score"] = str(coord_dict["score"])
    with context.open_output(output_path) as bbox_p:
        json.dump(bbox_coords, bbox_p)
