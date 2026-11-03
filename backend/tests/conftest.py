import asyncio

import pytest

from app import runner, tasks


@pytest.fixture
def tasks_dir(tmp_path, monkeypatch):
    """Point TASKS_DIR at a temp dir so tests never touch the real tasks/."""
    directory = (tmp_path / "tasks").resolve()
    monkeypatch.setattr(tasks, "TASKS_DIR", directory)
    return directory


@pytest.fixture
def fake_sdk(monkeypatch):
    """Replace runner.ClaudeSDKClient. Call the fixture with `session(prompt,
    options)`, an async generator of SDK messages; returns the fake class
    (its `instances` lists every client made)."""

    def install(session):
        class FakeClient:
            instances: list["FakeClient"] = []

            def __init__(self, options):
                self.options = options
                self.prompt = None
                self.interrupted = asyncio.Event()
                FakeClient.instances.append(self)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def query(self, prompt):
                self.prompt = prompt

            async def receive_response(self):
                async for message in session(self.prompt, self.options, self):
                    yield message

            async def interrupt(self):
                self.interrupted.set()

        monkeypatch.setattr(runner, "ClaudeSDKClient", FakeClient)
        return FakeClient

    return install
