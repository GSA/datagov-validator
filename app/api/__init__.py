from apiflask import APIBlueprint

api = APIBlueprint("api", __name__, url_prefix="/api", tag="Validate")

from . import validate  # noqa: E402, F401
