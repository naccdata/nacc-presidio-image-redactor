"""Provides utilities for pulling input from the OS environment."""

import os
from typing import Optional


def get_environment_variable(name: str) -> Optional[str]:
    """Gets the value of the environment variable.

    Note: converts the variable name to upper case.

    Returns:
      The value of the environment variable.
    """
    value = None
    variable = name.upper()
    if variable in os.environ:
        value = os.environ[variable]
    return value
