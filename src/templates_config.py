import json as _json
import markdown as _markdown
from markupsafe import Markup
from pathlib import Path
from fastapi.templating import Jinja2Templates


def _strftime_filter(value, fmt="%Y-%m-%d %H:%M"):
    if value is None:
        return ""
    return value.strftime(fmt)


def _fromjson_filter(value):
    if not value:
        return {}
    try:
        return _json.loads(value)
    except Exception:
        return {}


def _markdown_filter(value):
    if not value:
        return Markup("")
    return Markup(_markdown.markdown(value, extensions=["nl2br"]))


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.filters["strftime"] = _strftime_filter
templates.env.filters["fromjson"] = _fromjson_filter
templates.env.filters["mdrender"] = _markdown_filter
