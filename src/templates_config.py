from pathlib import Path
from fastapi.templating import Jinja2Templates


def _strftime_filter(value, fmt="%Y-%m-%d %H:%M"):
    if value is None:
        return ""
    return value.strftime(fmt)


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["strftime"] = _strftime_filter
