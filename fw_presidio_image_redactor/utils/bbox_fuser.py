"""KD Tree data structure for aggregating bboxes by distance."""

import logging
from typing import Dict, List

import numpy as np
from sklearn.neighbors import KDTree

log = logging.getLogger(__name__)


class BboxFuser:
    def __init__(self) -> None:
        pass

    def convert_coords_to_array(self, bboxes: dict) -> np.array:
        """Convert bounding box coordinates to a numpy array.

        Args:
            coordinates (dict): A dictionary of bounding box coordinates.

        Returns:
            np.array: A numpy array of bounding box coordinates.

        """
        bounding_boxes = []
        for item in bboxes:
            x1 = item["left"]
            y1 = item["top"]
            x2 = item["width"]
            y2 = item["height"]
            confidence = item["score"]
            idx = item["index"]
            slice_number = item["slice_number"]

            bounding_boxes.append([x1, y1, x2, y2, confidence, idx, slice_number])

        # Convert bounding boxes and confidence scores to numpy arrays
        bbox_array = np.array(bounding_boxes)

        return bbox_array

    def build_kd_tree(self, bbox_array: np.array) -> KDTree:
        """Build a KD-Tree using only the bounding box coordinates.

        Args:
            bbox_array (np.array): A numpy array of bounding box coordinates.

        Returns:
            KDTree: A KD-Tree built using the bounding box coordinates.
        """
        # Build KD-Tree using only the bounding box coordinates (ignoring the
        # confidence for spatial search)
        bounding_boxes = bbox_array[:, :4]  # Extract coordinates
        confidence_score = bbox_array[:, 4]
        slice_numbers = bbox_array[:, 6]
        centers = np.array(
            [[(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] for box in bounding_boxes]
        )
        kd_tree = KDTree(centers)

        return kd_tree, bounding_boxes, confidence_score, centers, slice_numbers

    def get_neighbors(
        self, kd_tree: KDTree, centers: np.array, radius: float = 0.1
    ) -> np.array:
        # Set a radius for spatial proximity and query the KD-Tree
        neighbors = kd_tree.query_radius(centers, r=radius)

        return neighbors

    def calculate_iou(self, box1, box2):
        x1_inter = max(box1[0], box2[0])
        y1_inter = max(box1[1], box2[1])
        x2_inter = min(box1[2], box2[2])
        y2_inter = min(box1[3], box2[3])

        intersection_area = max(0, x2_inter - x1_inter) * max(0, y2_inter - y1_inter)

        box1_area = (box1[2] - box1[0]) * (box1[3] - box1[1])
        box2_area = (box2[2] - box2[0]) * (box2[3] - box2[1])

        union_area = box1_area + box2_area - intersection_area

        return intersection_area / union_area if union_area > 0 else 0

    def is_proximate_iou(self, box1, box2, threshold=0.70):
        # Check if the overlap is significant enough
        iou = self.calculate_iou(box1, box2)
        return iou > threshold

    # Function to compute Weighted Box Fusion (WBF)
    def weighted_box_fusion(
        self,
        bboxes: List,
        cluster_indices: List,
        confidence_scores: List,
        slice_numbers: List,
    ):
        """

        Returns:
            fused_bbox [float,float,float,float,float, List]
        """
        cluster_boxes = bboxes[cluster_indices]
        cluster_confidences = confidence_scores[cluster_indices]
        total_confidence = np.sum(cluster_confidences)
        avg_confidence = total_confidence / len(cluster_confidences)

        # Get only unique slice numbers where fused box was aggregated from
        slice_numbers = list(set(slice_numbers))  # Set shortcut, no order needed

        # Weighted average of bounding box coordinates
        x1_avg = int(
            np.sum(cluster_boxes[:, 0] * cluster_confidences) / total_confidence
        )
        y1_avg = int(
            np.sum(cluster_boxes[:, 1] * cluster_confidences) / total_confidence
        )
        x2_avg = int(
            np.sum(cluster_boxes[:, 2] * cluster_confidences) / total_confidence
        )
        y2_avg = int(
            np.sum(cluster_boxes[:, 3] * cluster_confidences) / total_confidence
        )

        return [x1_avg, y1_avg, x2_avg, y2_avg, avg_confidence, slice_numbers]

    def join_bboxes(
        self, bboxes: List, clusters: List, conf_scores: List, slice_numbers: List
    ) -> List:
        """Join bounding boxes in clusters based on proximity&confidence scores.

        Args:
            bboxes (List): List of bounding boxes
            clusters (List): List of clustered bbox neighbors
            conf_scores (List): Parallel list of confidence scores to bboxes
            slice_numbers (List): Parallel list of image slice numbers to bboxes

        Returns:
            List: List of joined bounding boxes based on clusters
        """
        joined_boxes = []
        for cluster in clusters:
            joined_box = self.weighted_box_fusion(
                bboxes=bboxes,
                cluster_indices=cluster,
                confidence_scores=conf_scores,
                slice_numbers=slice_numbers,
            )
            joined_boxes.append(joined_box)

        return joined_boxes

    def fuse_similar_bboxes(self, bbox_flattened_dict: Dict) -> List:
        """
        Returns:
            fused_boxes: [x1_avg, y1_avg, x2_avg, y2_avg, avg_conf_score]
        """
        bbox_array = self.convert_coords_to_array(bboxes=bbox_flattened_dict)

        # Check if no entities have been found
        if len(bbox_array) < 1:
            return []
        BboxTree, bounding_boxes, confidence_scores, centers, slice_numbers = (
            self.build_kd_tree(bbox_array)
        )
        log.info("Number of bounding boxes found: %s", len(bounding_boxes))

        neighbors = self.get_neighbors(kd_tree=BboxTree, centers=centers, radius=2.0)

        clusters = []
        visited = set()
        for i, neighbor_indices in enumerate(neighbors):
            if i not in visited:
                cluster = []
                for neighbor_index in neighbor_indices:
                    if self.is_proximate_iou(
                        bounding_boxes[i], bounding_boxes[neighbor_index], threshold=0.5
                    ):
                        cluster.append(neighbor_index)
                        visited.add(neighbor_index)
                clusters.append(cluster)

        log.info("Number of clusters found: %s", len(clusters))
        fused_boxes = self.join_bboxes(
            bboxes=bounding_boxes,
            clusters=clusters,
            conf_scores=confidence_scores,
            slice_numbers=slice_numbers,
        )
        log.info("Number of Bounding Boxes after aggregating: %s", len(fused_boxes))

        return fused_boxes
