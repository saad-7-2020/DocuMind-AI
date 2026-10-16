import threading

from documind.worker.runner import Worker


class FlakyQueue:
    """claim() fails twice (database unreachable), then returns no job and stops the loop."""

    def __init__(self, stop: threading.Event) -> None:
        self.calls = 0
        self.stop = stop

    def claim(self, worker_id, job_timeout_s):
        self.calls += 1
        if self.calls <= 2:
            raise ConnectionError("database unreachable")
        self.stop.set()
        return None


def test_worker_survives_infrastructure_errors():
    stop = threading.Event()
    queue = FlakyQueue(stop)
    worker = Worker(queue, indexing=None, job_timeout_s=60, poll_interval_s=0.001)  # type: ignore[arg-type]
    worker.run_forever(stop)  # must not raise
    assert queue.calls == 3
