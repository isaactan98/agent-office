import pytest

from app import tasks


@pytest.fixture
def tasks_dir(tmp_path, monkeypatch):
    """Point TASKS_DIR at a temp dir so tests never touch the real tasks/."""
    directory = (tmp_path / "tasks").resolve()
    monkeypatch.setattr(tasks, "TASKS_DIR", directory)
    return directory
