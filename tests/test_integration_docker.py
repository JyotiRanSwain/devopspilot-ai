"""Runs against a real Docker engine. Enable with: DOP_INTEGRATION=1 pytest -m integration"""
import os
import time

import pytest

from app.core.config import Settings
from app.core.services import build_services

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.getenv("DOP_INTEGRATION") != "1", reason="set DOP_INTEGRATION=1")]


def test_real_crashing_container_is_diagnosed(tmp_path):
    import docker
    client = docker.from_env()
    c = client.containers.run("alpine:3.20", ["sh", "-c", "echo 'ERROR environment variable DATABASE_URL is not set'; exit 1"],
                              detach=True, name="dop-it-crash", labels={"devopspilot.test": "1"})
    try:
        c.wait(timeout=30)
        time.sleep(0.5)
        s = build_services(Settings(db_path=str(tmp_path / "it.db")))
        inv = s.investigator.investigate("dop-it-crash")
        assert {"DOP-EXIT-001", "DOP-ENV-001"} <= {f.rule_id for f in inv.findings}
    finally:
        c.remove(force=True)
