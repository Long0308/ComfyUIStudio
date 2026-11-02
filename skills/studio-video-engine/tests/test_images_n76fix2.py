"""Windows device names cannot be used as library prompt folders."""
import pytest

from engine.core.errors import Refused
from engine.images.library import check_prompt_id


@pytest.mark.parametrize("name", ["CON", "PRN", "AUX", "NUL"] +
                         [f"COM{i}" for i in range(1, 10)] +
                         [f"LPT{i}" for i in range(1, 10)])
def test_reserved_device_names_are_refused(name):
    for value in (name, name.lower(), name.title()):
        with pytest.raises(Refused, match="reserved Windows device name"):
            check_prompt_id(value)


@pytest.mark.parametrize("name", ["NUL.txt", "con.", "PRN ", "COM1.txt", "lpt9. "])
def test_reserved_names_with_extension_or_trailing_dot_space_are_refused(name):
    with pytest.raises(Refused):
        check_prompt_id(name)


@pytest.mark.parametrize("name", ["CONSOLE", "NUL_1", "COM0", "COM10", "LPT10", "CHAR_08_FACE_1"])
def test_similar_valid_prompt_ids_are_accepted(name):
    assert check_prompt_id(name) == name
