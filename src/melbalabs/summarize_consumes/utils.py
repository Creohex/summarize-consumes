import json
import requests
import sys
import webbrowser
from pathlib import Path
from typing import Self


class IxioUploader:
    def upload(self, output):
        data = output.getvalue().encode("utf8")

        username, password = "summarize_consumes", "summarize_consumes"
        auth = requests.auth.HTTPBasicAuth(username, password)
        response = requests.post(
            url="http://ix.io",
            files={"f:1": data},
            auth=auth,
            timeout=30,
        )
        print(response.text)
        if "already exists" in response.text:
            return None
        if "down for DDOS" in response.text:
            return None
        if "ix.io is taking a break" in response.text:
            return None
        if response.status_code != 200:
            return None
        url = response.text.strip().split("\n")[-1]
        return url


class BpasteUploader:
    def upload(self, output):
        data = output.getvalue().encode("utf8")
        response = requests.post(
            url="https://bpaste.net/curl",
            data={"raw": data, "expiry": "1month"},
            timeout=30,
        )
        if response.status_code != 200:
            print(response.text)
            return None
        lines = response.text.splitlines()
        for line in lines:
            if "Raw URL" in line:
                url = line.split()[-1]
                return url


class CustomEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, dict):
            return {str(key): value for key, value in obj.items()}
        return super().default(obj)


class Config(dict):
    def __init__(self, filepath=str, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.filepath = filepath

    def save(self) -> None:
        with open(self.filepath, "w+") as f:
            json.dump(self, f, indent=2)

    def delete(self):
        check_existing_file(self.filepath, delete=True)

    def update(self, upd_dict, **kwargs):
        super().update(json.loads(json.dumps(upd_dict)), **kwargs)

    @classmethod
    def load(cls, filename) -> Self:
        # TODO: use some sort of temporary folder for win instead?
        match sys.platform:
            case "win32": conf_dir = Path(sys.executable).absolute().parent
            case _: conf_dir = Path(__file__).absolute().parent

        filepath = conf_dir / filename
        if check_existing_file(filepath):
            with open(filepath, "r") as f:
                return cls(filepath, json.load(f))
        else:
            conf = cls(filepath, {})
            conf.save()
            return conf


def upload_pastebin(output):
    url = BpasteUploader().upload(output)
    if url:
        return url
    url = IxioUploader().upload(output)
    return url


def open_browser(url):
    print(f"opening browser with {url}")
    webbrowser.open(url)


def check_existing_file(file: Path, delete: bool = False) -> None:
    """Check if file exist and deletes it when forced to.

    - file (Path): File location
    - delete (bool | None, optional (False)): delete file if True
    """

    if file.exists() and file.is_file():
        if delete or False:
            file.unlink()
        return True
    return False


def singleton(cls):
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance
