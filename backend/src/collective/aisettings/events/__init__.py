from collective.aisettings.interfaces import ITaskLostEvent
from zope.interface import implementer


@implementer(ITaskLostEvent)
class TaskLostEvent:
    def __init__(self, task_id, label, owner, age, late=False):
        self.task_id = task_id
        self.label = label
        self.owner = owner
        self.age = age
        self.late = late
