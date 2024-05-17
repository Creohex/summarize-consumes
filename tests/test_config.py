import json
import pytest
from pathlib import Path

from melbalabs.summarize_consumes.utils import Config, check_existing_file


TEST_CONF_PATH = Path().absolute() / "test.json"


@pytest.fixture(autouse=True, scope="function")
def cleanup_after_test():
    yield
    check_existing_file(TEST_CONF_PATH, delete=True)


def test_new():
    conf = Config.load(TEST_CONF_PATH)
    assert conf == {}
    assert conf.filepath == TEST_CONF_PATH
    assert check_existing_file(TEST_CONF_PATH) is True


def test_existing_upd():
    some_data = {"blabla": 123, "qweqwe": "ewqewq"}
    with open(TEST_CONF_PATH, "w") as f:
        json.dump(some_data, f)

    conf = Config.load(TEST_CONF_PATH)
    assert conf == some_data

    conf["new_field"] = 123
    conf.save()

    with open(TEST_CONF_PATH, "r") as f:
        new_conf = json.load(f)
    assert conf == new_conf


def test_formatting():
    invalid_json_dict = {123: "qwe"}
    expected_after_serealization = {"123": "qwe"}

    conf = Config.load(TEST_CONF_PATH)
    conf.update(invalid_json_dict)
    conf.save()

    assert conf == expected_after_serealization
    assert Config.load(TEST_CONF_PATH) == expected_after_serealization
