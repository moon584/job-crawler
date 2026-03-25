from __future__ import annotations

from crawler.db import Database


def test_compute_next_job_id_fills_gap() -> None:
    job_id = Database._compute_next_job_id("C001", ["C001J00001", "C001J00002", "C001J00004"])
    assert job_id == "C001J00003"


def test_compute_next_job_id_appends_when_no_gap() -> None:
    job_id = Database._compute_next_job_id("C001", ["C001J00001"])
    assert job_id == "C001J00002"


def test_compute_next_job_id_ignores_other_companies() -> None:
    job_id = Database._compute_next_job_id("C001", ["C002J00001", "C001J00001", "C002J00002"])
    assert job_id == "C001J00002"

