"""Script creation of reader tasks & protocol, & addition of annotations."""

import json
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, Tuple

import flywheel
from flywheel_gear_toolkit import GearToolkitContext
from fw_client import FWClient

log = logging.getLogger(__name__)


class ReaderTaskCreator:
    def __init__(self, api_key: str, file_id: str, job_id: str, bot_key: bool) -> None:
        self.sdk_client = flywheel.Client(api_key)
        self.client = FWClient(
            api_key=api_key,
            read_timeout=120,
            connect_timeout=120,
        )

        self.file_container = self.sdk_client.get_file(file_id)
        self.file_id = file_id
        self.project_id = self.file_container.parents.get("project", None)

        job_run = self.sdk_client.get_job(job_id)
        user_type = job_run.origin.get("type", None)

        # If gear rule job, check if system or fw bot API key is being used
        if user_type != "system":
            try:
                user_id = job_run.origin.get("id")
                self.username = self.sdk_client.get_user(user_id).email
            except ValueError:
                log.error(
                    "Job origin not found to be System or user. Found user type: %s with ID: %s, exiting...",
                    user_type,
                    user_id,
                )
        else:
            if bot_key:
                self.username = self.sdk_client.get_current_user().id
            else:
                gear_rules = self.sdk_client.get_project_rules(self.project_id)
                for rule in gear_rules:
                    job_gear_id = job_run.get("gear_id", None)
                    if rule.get("gear_id", None) == job_gear_id:
                        last_modified_entry = rule.get("last_modified_by")
                        self.username = last_modified_entry.get("id")

    def create_form(
        self,
    ):
        with open(
            "/flywheel/v0/fw_presidio_image_redactor/utils/schemas/form_schema.json",
            "r",
        ) as fp:
            data = json.load(fp)
            res = self.client.post("/api/forms", json=data)
            return res._id

    def create_viewer_config(
        self,
    ):
        with open(
            "/flywheel/v0/fw_presidio_image_redactor/utils/schemas/viewer_config_schema.json",
            "r",
        ) as fp:
            data = json.load(fp)
            res = self.client.post("/api/viewerconfigs", json=data)
            return res._id

    def create_reader_protocol(
        self,
        name="presidio_default_protocol",
        description="The default reader protocol for the Presidio Image Redactor",
    ):
        # Fetch protocols for current project & check if protocol exists
        project_protocols = self.client.get("/api/read_task_protocols")
        protocol_results = project_protocols.results
        presidio_protocol = [
            protocol
            for protocol in protocol_results
            if protocol["label"] == name
            and protocol.get("parents", {}).get("project") == self.project_id
        ]
        if presidio_protocol:
            log.info("Reader protocol %s already exists", name)
            presidio_protocol = presidio_protocol[0]
            self.protocol_id = presidio_protocol.get("_id")
            self.form_id = presidio_protocol.get("form_id")
            self.viewer_config_id = presidio_protocol.get("viewer_config_id")
            return self.protocol_id
        else:
            log.info("Protocol not found, creating protocol %s...", name)
            self.form_id = self.create_form()
            self.viewer_config_id = self.create_viewer_config()
            protocol_data = {
                "label": name,
                "description": description,
                "form_id": self.form_id,
                "viewer_config_id": self.viewer_config_id,
                "parent": {
                    "type": "project",
                    "id": self.project_id,
                },
            }
            res = self.client.post("/api/read_task_protocols", json=protocol_data)
            log.info("Successfully created reader protocol %s", res.label)

            # Response may not have ID assigned to protocol
            self.protocol_id = [
                protocol._id
                for protocol in self.client.get("/api/read_task_protocols").results
                if protocol.label == name
                and protocol.get("parents", {}).get("project") == self.project_id
            ][0]
            return self.protocol_id

    def create_reader_task(self, assignees: str) -> None:
        """Creates reader tasks for a file object

        Args:
            assignee (str): Email of assignee from Flywheel
        """
        with open(
            "/flywheel/v0/fw_presidio_image_redactor/utils/schemas/reader_task.json",
            "r",
        ) as fp:
            data = json.load(fp)

        # Set modified data elements
        data["assignee"] = random.choice(assignees)
        data["parent"]["id"] = self.file_id
        data["form_id"] = self.form_id
        data["protocol_id"] = self.protocol_id
        data["viewer_config_id"] = self.viewer_config_id

        # Set due date to 1 week from now
        current_date_time = datetime.now(timezone.utc)
        new_date_obj = current_date_time + timedelta(days=7)
        new_due_date = new_date_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        data["due_date"] = new_due_date

        # Post & check response
        res = self.client.post("/api/readertasks", json=data)
        if res:
            log.info(f"ReaderTask created for file {self.file_container.name}")
            self.task_id = res._id

        return self.task_id

    def create_single_annotation(
        self,
        image_path: str,
        bbox_coords: Dict,
    ) -> None:
        """Creates annotations for a given task."""

        with open(
            "/flywheel/v0/fw_presidio_image_redactor/utils/schemas/annotation_schema.json",
            "r",
        ) as fp:
            annotation = json.load(fp)
        top_level_annotation_id = str(uuid.uuid4())
        annotation["_id"] = top_level_annotation_id

        annotation["origin"] = {
            "type": "user",
            "id": self.username,
        }
        annotation["file_id"] = self.file_id
        annotation["task_id"] = self.task_id
        annotation_data_id = str(uuid.uuid4())
        annotation["data"]["_id"] = annotation_data_id
        annotation["data"]["uuid"] = str(uuid.uuid4())
        image_path, slice_number = image_path.split("***")
        study_instance_uid, series_instance_uid, sop_instance_uid, frame_index = (
            image_path.split("$$$")
        )
        annotation["data"]["imagePath"] = image_path
        annotation["data"]["StudyInstanceUID"] = study_instance_uid
        annotation["data"]["SeriesInstanceUID"] = series_instance_uid
        annotation["data"]["SOPInstanceUID"] = sop_instance_uid
        annotation["sliceNumber"] = slice_number

        # Set frame index
        # NOTE: FrameIndex increments for each plane in multiframe,
        # as well as sliceNumber. For non-multiframe images, frameIndex is
        # 0 for all planes, but sliceNumber increments

        annotation["data"]["frameIndex"] = int(frame_index)
        # TODO: Update user information
        annotation["data"]["flywheelOrigin"] = {
            "type": "user",
            "id": self.username,
        }
        annotation["data"]["handles"] = {
            "start": {
                "x": bbox_coords["left"],
                "y": bbox_coords["top"],
                "highlight": True,
                "active": False,
            },
            "end": {
                "x": bbox_coords["width"],
                "y": bbox_coords["height"],
                "highlight": True,
                "active": False,
                "moving": False,
            },
            "textBox": {
                "x": bbox_coords["width"],
                "y": (bbox_coords["top"] + bbox_coords["height"]) / 2,
                "boundingBox": {
                    "width": 150.0,
                    "height": 50.0,
                    "left": (bbox_coords["top"] + bbox_coords["height"]) / 2,
                    "top": bbox_coords["width"],
                },
                "active": False,
                "hasMoved": False,
                "movesIndependently": False,
                "drawnIndependently": True,
                "allowedOutsideImage": True,
                "hasBoundingBox": True,
            },
            "initialRotation": 0,
        }

        _ = str(self.client.post("/api/annotations", json=annotation))

        return top_level_annotation_id

    def create_annotations(self, bbox_coords: Dict) -> Tuple[str, Dict]:
        """Iterates through bounding box coordinates and creates annotations.

        Args:
            bbox_coords (Dict): Dictionary of bounding box coordinates.

        Returns:
            Tuple[str, Dict]: Tuple of task_id and dictionary of annotations.
        """
        created_annotations = []
        for img_key, coords_list in bbox_coords.items():
            for coords in coords_list:
                temp_anno_id = self.create_single_annotation(img_key, coords)
                created_annotations.append(temp_anno_id)


if __name__ == "__main__":
    api_key = GearToolkitContext().get_input("api-key")["key"]
    fw_client = FWClient(
        api_key=api_key,
        read_timeout=120,
        connect_timeout=120,
    )
    fw = flywheel.Client(api_key)
    annotations = fw_client.get(
        "/api/annotations",
        params={"filter": "file_ref.file_id=<file_id>"},
    ).results
