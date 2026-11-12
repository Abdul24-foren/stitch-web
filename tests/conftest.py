import os
import re

os.environ.setdefault(
    "SECRET_KEY",
    "test-only-secret-key-with-at-least-32-characters",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.database import enable_sqlite_foreign_keys, get_db


class CSRFTestClient(TestClient):
    def post(self, url, *args, **kwargs):
        response = self.get("/login")
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        if not match:
            raise AssertionError("The application did not render a CSRF token.")
        data = kwargs.get("data")
        data = dict(data) if data is not None else {}
        data.setdefault("csrf_token", match.group(1))
        kwargs["data"] = data
        return super().post(url, *args, **kwargs)

    def post_without_csrf(self, url, *args, **kwargs):
        return super().post(url, *args, **kwargs)


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'stitch-it-test.db'}",
        connect_args={"check_same_thread": False},
    )
    enable_sqlite_foreign_keys(engine)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "get_db", override_get_db)
    monkeypatch.setattr(main, "UPLOAD_DIR", upload_dir)
    main.app.dependency_overrides[get_db] = override_get_db

    try:
        with CSRFTestClient(main.app, follow_redirects=False) as client:
            yield client, testing_session, upload_dir
    finally:
        main.app.dependency_overrides.clear()
        engine.dispose()
