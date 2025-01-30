"""Parser module to parse gear config.json."""

import json
import logging
import pathlib
import sys
import zipfile
from pathlib import Path
from typing import List, Tuple, Union

from flywheel_gear_toolkit import GearToolkitContext
from .utils.parameter_store.parameter_store import ParameterStore

log = logging.getLogger(__name__)

STD_FILE_EXTS = [".dicom.zip", ".zip", ".dcm", ".dicom", ".dcm.zip"]


def parse_config(
    context: GearToolkitContext,
) -> Tuple[
    Union[str, None],
    list,
    str,
    int,
    int,
    list,
    bool,
    str,
    str,
    dict,
    pathlib.PosixPath,
    str,
    str,
    str,
    bool,
]:
    """Parses flywheel GearContext class object to pull relevant configuration and user inputs.

    Args:
        context (GearToolkitContext): Class object for interacting with Flywheel gear & instance options.

    Returns:
        Tuple[Union[str,None],list,str,int,int,list,bool,str,str,dict,pathlib.PosixPath,str,str,str,bool]: Parsed parameters for gear operations
    """
    if context.config.get("apikey_path_prefix", None):
        ParamStore = ParameterStore.create_from_environment()
        api_key = ParamStore.get_api_key(
            path_prefix=context.config.get("apikey_path_prefix")
        )
        bot_key = True
    else:
        api_key = context.get_input("api-key")["key"]
        bot_key = False

    # debug setup
    debug = context.config.get("Debug", None)
    debug_path = context.work_dir / "debug_output"
    if debug and not debug_path.exists():
        debug_path.mkdir()
    else:
        debug_path = None

    assignees = context.config.get("Assignees", None)
    file_id = context.get_input_file_object("image_file").get("file_id")
    validated_assignees = validate_assignees(context, assignees, file_id)

    try:
        operating_mode = context.config.get("Baseline Operating Mode", None)
        if operating_mode is None:
            raise ValueError(
                "Invalid operating mode selected or none found, exiting..."
            )
    except ValueError as e:
        log.error(e)
        sys.exit(1)

    file_path = context.get_input_path("image_file")
    prior_scan_inputs = {"bbox_coords": context.get_input_path("bbox_coords")}
    transformer_score_threshold = context.config.get("Transformer Score Threshold", 30)
    entity_frequency_threshold = context.config.get("Entity Frequency Threshold", 30)
    allowed_fill_strings = ["contrast", "background"]
    if context.config.get("Bounding Box Fill", None) in allowed_fill_strings:
        bbox_fill = context.config.get("Bounding Box Fill")
    else:
        log.error(
            "Invalid bounding box fill string provided, please use one of %s",
            allowed_fill_strings,
        )
        sys.exit(1)
    use_metadata = context.config.get("Use Dicom Metadata", False)
    original_filename = context.get_input_filename("image_file")
    base_filename = remove_file_suffix(original_filename)
    output_path = context.output_dir

    entities_string = context.config.get("Entities to Find", None)
    if entities_string:
        selected_entities = entities_string.split(",")
    else:
        log.error("No entities were provided, exiting...")
        sys.exit(1)

    with open("/flywheel/v0/config.json", "r") as fp:
        config_dict = json.load(fp)
        job_id = config_dict.get("job").get("id")

    # Check for zipped files, format hierarchy accordingly
    input_files = detect_and_unpack_zip(file_path=file_path)

    return (
        debug_path,
        input_files,
        operating_mode,
        transformer_score_threshold,
        entity_frequency_threshold,
        selected_entities,
        use_metadata,
        bbox_fill,
        base_filename,
        prior_scan_inputs,
        output_path,
        api_key,
        file_id,
        job_id,
        validated_assignees,
        bot_key,
    )


def detect_and_unpack_zip(file_path: pathlib.PosixPath) -> List[pathlib.PosixPath]:
    """Determine if file provided is a zip file, if so unpack & return list of files.

    Args:
        file_path (pathlib.PosixPath): File path of input file

    Returns:
        List[pathlib.PosixPath]: List of the files to be used as input downstream
    """
    if zipfile.is_zipfile(file_path):
        tmpdir = Path("tmpdir")
        tmpdir.mkdir(exist_ok=False)
        with zipfile.ZipFile(file_path, mode="r") as zfile:
            zfile.extractall(tmpdir)

        input_files = [Path(x) for x in tmpdir.glob("**/*") if x.is_file()]

    else:
        input_files = [Path(file_path)]

    return input_files


def remove_file_suffix(file_name: str) -> str:
    """Remove the file suffix from a given file name.

    Args:
        file_name (str): File name to remove suffix from

    Returns:
        str: File name without suffix
    """
    # Sort file extensions by longest first so '.zip' isn't before '.dcm.zip'
    file_exts = sorted(STD_FILE_EXTS, key=len, reverse=True)
    for ext in file_exts:
        if file_name.endswith(ext):
            clean_file_name = file_name.removesuffix(ext)
            break
    return clean_file_name


def validate_assignees(
    context: GearToolkitContext, assignees: str, file_id: str
) -> List[str]:
    required_user_actions = [
        "annotations_edit_others",
        "annotations_manage",
        "annotations_view_others",
        "form_responses_view_others",
        "reader_task_view",
    ]

    # Check 1, validate string passed by user
    assignee_list = [email.strip() for email in assignees.split(",")]
    correct_op_mode = (
        context.config.get("Baseline Operating Mode", None) == "Detection+ReaderTasks"
    )
    if not correct_op_mode:
        if not assignee_list or (len(assignee_list) == 1 and assignee_list[0] == ""):
            log.error("No assignees provided, exiting...")
            sys.exit(1)

    # Check 2, validate user exists in the project
    # Use project permissions vs site or user roles, uses better data structure
    file_container = context.client.get_file(file_id)
    project_id = file_container.parents.get("project", None)
    project_container = context.client.get(project_id)
    project_perms = project_container.get("permissions", None)
    found_users = {}
    for user_email in assignee_list:
        for perm in project_perms:
            if perm.get("_id") == user_email:
                found_users[user_email] = perm.get("role_ids")

    if user_email not in found_users.keys():
        log.error("User (%s) not found in project, exiting...", user_email)
        sys.exit(1)

    # Check 3, validate user has role w/ required permissions
    validated_users = []
    for user, roles in found_users.items():
        for role_id in roles:
            role = context.client.get_role(role_id)
            actions = role.get("actions", None)
            actions_set = set(actions)
            role_has_required_actions = all(
                action in actions_set for action in required_user_actions
            )
            if role_has_required_actions:
                break
        if role_has_required_actions:
            validated_users.append(user)

    non_validated_users = set(found_users.keys()) - set(validated_users)
    if non_validated_users:
        log.error(
            "Assignees %s do not have the required permissions: %s, exiting...",
            non_validated_users,
            required_user_actions,
        )
        sys.exit(1)

    return validated_users
