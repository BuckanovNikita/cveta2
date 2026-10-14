"""Application CVAT operations over explicitly supplied ports."""

from cveta2.application.client.base import _ClientBase
from cveta2.application.client.fetch import _FetchMixin
from cveta2.application.client.images import _ImageMixin
from cveta2.application.client.read import _ReadMixin
from cveta2.application.client.task_ops import _TaskOpsMixin
from cveta2.application.client.write import _WriteMixin


class ApplicationClient(
    _FetchMixin, _ImageMixin, _WriteMixin, _TaskOpsMixin, _ReadMixin, _ClientBase
):
    """CVAT orchestration independent of configuration discovery and SDKs."""
