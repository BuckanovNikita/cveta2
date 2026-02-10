"""cveta2 -- CVAT project annotation utilities."""

from cveta2.client import CvatClient, fetch_annotations
from cveta2.models import BBoxAnnotation, DeletedImage, ProjectAnnotations

__all__ = [
    "BBoxAnnotation",
    "CvatClient",
    "DeletedImage",
    "ProjectAnnotations",
    "fetch_annotations",
]
