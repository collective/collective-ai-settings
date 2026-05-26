from collective.aisettings.services.tasks import get_task
from plone.restapi.services import Service
from zope.interface import implementer
from zope.publisher.interfaces import IPublishTraverse


@implementer(IPublishTraverse)
class AITaskStatus(Service):
    """``GET /++api++/@ai-task/<task_id>`` — poll an async AI call.

    Returns:
        ``{"task_id", "status": "running"}`` while the worker is busy;
        ``{"task_id", "status": "done", "result": ...}`` on success;
        ``{"task_id", "status": "error", "error": "..."}`` on failure.
    """

    def __init__(self, context, request):
        super().__init__(context, request)
        self.params: list[str] = []

    def publishTraverse(self, request, name):
        self.params.append(name)
        return self

    def reply(self):
        if not self.params:
            self.request.response.setStatus(400)
            return {"error": "task_id required"}

        task_id = self.params[0]
        task = get_task(task_id)
        if task is None:
            self.request.response.setStatus(404)
            return {"error": "task not found"}

        return {"task_id": task_id, **task}
