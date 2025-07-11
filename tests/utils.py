"""
Utils module for unit tests
"""

import json
from typing import Literal


def load_content(file_path: str, *, encoded: bool = True):
    """
    Loads content from a file
    """
    with open(file_path, encoding="utf-8") as file:
        if encoded:
            return file.read().encode("utf-8")
        return file.read()


def load_nwb_content(file_path: str):
    """
    Loads content for an NWB file
    """
    with open(file_path, "rb") as file:  # noqa: FURB101
        file_content = file.read()

    return file_content


def load_json_file(filepath: str, not_include: Literal["stimulus", "simulation"] | None = None):
    """
    Loads a JSON file from the specified path and returns the parsed data.

    Args:
        filepath (str): The path to the JSON file.

    Returns:
        object: The parsed JSON data, which can be a dictionary, list, etc.

    Raises:
        FileNotFoundError: If the specified file is not found.
        json.JSONDecodeError: If the file content is not valid JSON.
    """

    try:
        with open(filepath, encoding="utf-8") as f:
            json_data = json.load(f)
            if not_include == "simulation":
                del json_data["simulation"]
                return json.dumps(json_data).encode("utf-8")
            if not_include == "stimulus":
                del json_data["stimulus"]
                return json.dumps(json_data).encode("utf-8")
            return json.dumps(json_data).encode("utf-8")
    except FileNotFoundError:
        msg = f"JSON file not found: {filepath}"
        raise FileNotFoundError(msg) from None
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON format in file: {filepath} ({e})"
        raise json.JSONDecodeError(msg, e.doc, e.pos) from e
