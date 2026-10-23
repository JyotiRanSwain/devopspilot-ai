from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.services import build_services
from app.main import create_app
from app.services.docker_service import DockerService


def iso(delta_seconds=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "000Z"


def make_attrs(name, status="running", exit_code=0, restart_count=0, health=None, error="", oom=False, env=None,
               started=-3600, finished=None, image="app:1"):
    state = {"Status": status, "Running": status == "running", "Restarting": status == "restarting", "ExitCode": exit_code,
             "Error": error, "OOMKilled": oom, "StartedAt": iso(started), "FinishedAt": iso(finished) if finished is not None else "0001-01-01T00:00:00Z"}
    if health:
        state["Health"] = {"Status": health, "Log": [{"Output": "curl: (7) Failed to connect password=hunter2"}]}
    return {"Id": (name * 20).encode().hex()[:64], "Name": "/" + name, "Created": iso(-7200), "RestartCount": restart_count,
            "State": state, "Config": {"Image": image, "Env": env or [], "Cmd": ["python", "app.py"]},
            "HostConfig": {"RestartPolicy": {"Name": "always"}}, "Mounts": [], "NetworkSettings": {"Ports": {}, "Networks": {"bridge": {}}}}


class FakeContainer:
    def __init__(self, attrs, logs="", stats=None):
        self.attrs, self._logs, self._stats = attrs, logs, stats
        self.name = attrs["Name"].lstrip("/")
        self.id = attrs["Id"]
        self.short_id = self.id[:12]

    def reload(self): pass

    def logs(self, **kwargs):
        lines = self._logs.splitlines()[-kwargs.get("tail", 100):]
        return "\n".join(f"{iso(-60 + i)} {l}" for i, l in enumerate(lines)).encode()

    def stats(self, stream=False):
        if self._stats is None:
            raise RuntimeError("no stats")
        return self._stats


class FakeClient:
    def __init__(self, containers):
        self._c = containers
        self.containers = self

    def ping(self): return True

    def list(self, all=True, limit=None): return list(self._c)

    def get(self, ref):
        from docker.errors import NotFound
        for c in self._c:
            if ref in (c.name, c.id, c.short_id):
                return c
        raise NotFound("missing")

    def info(self): return {"ServerVersion": "27.0", "OperatingSystem": "Test OS", "NCPU": 4, "MemTotal": 8 * 2**30, "Containers": len(self._c)}
    def version(self): return {"ApiVersion": "1.46"}


STATS = {"cpu_stats": {"cpu_usage": {"total_usage": 200}, "system_cpu_usage": 2000, "online_cpus": 2},
         "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
         "memory_stats": {"usage": 100 * 2**20, "limit": 512 * 2**20, "stats": {"inactive_file": 20 * 2**20}}}


@pytest.fixture
def containers():
    return [
        FakeContainer(make_attrs("web", health="healthy"), "INFO started\nGET /x 200", STATS),
        FakeContainer(make_attrs("api", status="exited", exit_code=1, started=-100, finished=-95, env=["DB_PASSWORD=s3cret", "MODE=prod"]),
                      'Traceback (most recent call last):\n  File "app.py", line 3\nKeyError: \'DATABASE_URL\'\nERROR environment variable DATABASE_URL is not set'),
        FakeContainer(make_attrs("worker", status="restarting", restart_count=7, exit_code=1), "FATAL cannot start\nERROR boom"),
    ]


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=str(tmp_path / "t.db"), ai_provider="none")


@pytest.fixture
def services(settings, containers):
    docker = DockerService(settings, client_factory=lambda: FakeClient(containers))
    return build_services(settings, docker=docker)


@pytest.fixture
def client(settings, services):
    return TestClient(create_app(settings, services))
