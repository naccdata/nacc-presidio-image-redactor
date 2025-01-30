"""A script for housing utility functions for tracking the algorithm's progress."""

from typing import Dict


class ProgressTracker:
    def __init__(self, len_of_iterable: int) -> None:
        """Initializes the ProgressTracker object.

        Args:
            len_of_iterable (int): Length of the iterable object.

        Returns:
            None

        """
        self.len_of_iterable = len_of_iterable

    def find_quartiles(
        self,
    ) -> Dict[int, int]:
        """Identifies the indices of an iterable's quartiles.

        Args:
            None

        Returns:
            markers (Dict[int, int]): A dictionary of quartile indices with percentage.

        """
        # Quartiles for progress logging
        if self.len_of_iterable >= 4:
            markers = {
                int(self.len_of_iterable * percentage): int(percentage * 100)
                for percentage in (0.25, 0.5, 0.75, 1.0)
            }
        else:
            markers = self.no_quartiles()

        return markers

    def no_quartiles(
        self,
    ) -> Dict[int, int]:
        """If iterable too small for quartiles, 0 or 100 used.

        Args:
            None

        Returns:
            markers (Dict[int, int]): A dictionary with nearest int for percentage.

        """
        # Round to nearest int if less than 4 elements in iterable
        markers = {
            file_idx: int((file_idx / self.len_of_iterable) * 100)
            for file_idx in range(1, self.len_of_iterable + 1)
        }

        return markers
