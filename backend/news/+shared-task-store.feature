Optionally share async task state between processes through memcached, so a
poll answered by another instance behind a load balancer no longer gets "task
not found". Off unless `COLLECTIVE_AISETTINGS_TASK_STORE=memcached://host:port`
is set (install `collective.aisettings[memcached]`); then tasks running past
`COLLECTIVE_AISETTINGS_TASK_MAX_RUNNING` (900 s) are reported as failed and
fire `ITaskLostEvent`, a task is only readable by the user who started it, and
`begin_shutdown()` lets a deployment's shutdown hook hand running tasks back to
clients as `retryable`. `@ai-task` responses are now `Cache-Control: no-store`.
@frapell
