"""The Order add-on's own preferences, in its data folder (prefs.json): the
browser mpc-autofill uses, your own copy of mpc-autofill, full-quality
previews and the MPCFill servers. MSE Studio's settings are only read – once,
to keep what you had chosen when the Order page came with MSE Studio."""
from __future__ import annotations

import json

from mse_studio.core import addons

DEFAULTS = {"browser": "", "autofill": "", "full_quality": False,
            "mpcfill_server": "", "mpcfill_images": ""}
# what MSE Studio before 0.25 kept in its own settings
OLD_SETTINGS = {"browser": "mpc_browser", "autofill": "mpc_autofill_path",
                "full_quality": "order_full_quality", "mpcfill_server": "mpcfill_server",
                "mpcfill_images": "mpcfill_images"}


def _file():
    return addons.data_dir("order") / "prefs.json"


def load(settings=None) -> dict:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict):           # the first start: what you had before
        data = {k: (getattr(settings, OLD_SETTINGS[k], v) if settings is not None else v)
                for k, v in DEFAULTS.items()}
        save(data)
    return {k: type(v)(data.get(k, v) or v) for k, v in DEFAULTS.items()}


def save(data: dict) -> None:
    f = _file()
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps({k: data.get(k, v) for k, v in DEFAULTS.items()}, indent=1),
                   encoding="utf-8")
    tmp.replace(f)
