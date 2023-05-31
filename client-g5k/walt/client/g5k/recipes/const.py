from pathlib import Path

RECIPES_STORAGE_DIR = Path.home() / ".walt-g5k" / "recipes"
DEFAULT_WALLTIME = "01:00:00"
DEFAULT_SCHEDULING = "asap"
SCHEDULE_DESC = {
    "night": "at night (or during week-end)",
    "asap": "as soon as possible",
}
