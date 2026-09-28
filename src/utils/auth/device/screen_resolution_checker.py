from typing import Tuple
import numpy as np

from src.utils.auth.device.common_screen_resolution import COMMON_SCREEN_RESOLUTION


Resolution = Tuple[int, int]


class ScreenResolutionChecker:
    def __init__(self, current_resolution: str):
        self.know_screen_resolution = COMMON_SCREEN_RESOLUTION
        self.current_resolution: Resolution = self._parse_to_pair(current_resolution)

    def _parse_to_pair(self, res: str) -> Resolution:
        """
        Convert `res` (resolution string "1920x1080") → (w, h) integers.
        """
        screen = res.lower()
        if "x" not in screen:
            raise ValueError("Screen format not valid")

        splitted_screen = screen.split("x")
        if (
            len(splitted_screen) == 2
            and splitted_screen[0].isdigit()
            and splitted_screen[1].isdigit()
        ):
            return int(splitted_screen[0]), int(splitted_screen[1])

        raise ValueError(f"List with diff values! input: {screen}")

    @staticmethod
    def _euclidean_distance(resolution1: Tuple[int, int], resolution2: Tuple[int, int]):
        """Calculates the Euclidean distance between two resolutions."""
        return np.sqrt(np.sum((np.array(resolution1) - np.array(resolution2)) ** 2))

    def find_closest_resolution(self) -> str:
        """finds the closest resolution to the target resolution.
        **Returns**
        - A string with the closest resolution following 1980x1080
        """
        distances = [
            ScreenResolutionChecker._euclidean_distance(self.current_resolution, res)
            for res in self.know_screen_resolution
        ]
        closest_index = np.argmin(distances)

        resolution = self.know_screen_resolution[closest_index]
        return f"{resolution[0]}x{resolution[1]}"
