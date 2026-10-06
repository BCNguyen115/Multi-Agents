"""Uploads: the bytes must match the name, bombs are refused, and parsing runs in a child that can be stopped."""
import io
import os
import time
import zipfile

import pytest

from src.config import settings
from src.ingestion import upload
from src.ingestion.upload import UploadError, check_file
from src.shared.isolated import IsolatedError, run_isolated


def zipped(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


# ---- what the bytes must look like -------------------------------------------------------------------------------------

def test_a_pdf_must_start_like_one():
    check_file("a.pdf", b"%PDF-1.7\n...")
    with pytest.raises(UploadError):
        check_file("a.pdf", b"MZ\x90\x00 this is an executable")


def test_an_office_file_must_be_a_zip():
    check_file("a.docx", zipped({"word/document.xml": b"<w/>"}))
    with pytest.raises(UploadError):
        check_file("a.docx", b"%PDF-1.7 renamed")
    with pytest.raises(UploadError):
        check_file("a.pptx", b"not a zip at all")


def test_text_has_no_nul_bytes():
    check_file("a.md", "# Tiêu đề\nnội dung".encode())
    with pytest.raises(UploadError):
        check_file("a.txt", b"binary\x00\x01\x02")


def test_a_file_that_unpacks_to_far_more_than_it_weighs_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "KNOWLEDGE_MAX_UNCOMPRESSED_MB", 1)
    bomb = zipped({"word/document.xml": b"0" * (3 * 1024 * 1024)})  # 3 MB of zeros: a few KB on disk
    assert len(bomb) < 100_000
    with pytest.raises(UploadError, match="1"):
        check_file("a.docx", bomb)


def test_an_archive_with_too_many_entries_is_refused(monkeypatch):
    monkeypatch.setattr(upload, "MAX_ARCHIVE_ENTRIES", 5)
    with pytest.raises(UploadError):
        check_file("a.pptx", zipped({f"slide{i}.xml": b"x" for i in range(6)}))


# ---- the worker process ------------------------------------------------------------------------------------------------

def _answer(x, y):
    return {"sum": x + y, "pid": os.getpid()}


def _slow():
    time.sleep(60)


def _explode():
    raise ValueError("boom")


def _die():
    os._exit(3)


def test_the_result_comes_back_from_another_process():
    result = run_isolated(_answer, 2, 3, timeout=180)
    assert result["sum"] == 5 and result["pid"] != os.getpid()


def test_a_worker_that_takes_too_long_is_killed():
    started = time.time()
    with pytest.raises(TimeoutError):
        run_isolated(_slow, timeout=2)
    assert time.time() - started < 30


def test_a_worker_that_raises_or_dies_is_reported_not_propagated():
    with pytest.raises(IsolatedError, match="ValueError: boom"):
        run_isolated(_explode, timeout=180)
    with pytest.raises(IsolatedError, match="died"):
        run_isolated(_die, timeout=180)


def test_a_real_document_is_read_through_the_worker(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "KNOWLEDGE_PARSE_ISOLATED", True)
    path = tmp_path / "policy.md"
    path.write_text("# Chính sách\n\n" + "Nhân viên phải đổi mật khẩu mỗi chín mươi ngày. " * 20, encoding="utf-8")
    doc = upload._parse(str(path), "general", "policy.md")
    assert doc is not None and doc.sections


def test_a_timeout_or_a_dead_worker_becomes_an_upload_problem_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "KNOWLEDGE_PARSE_ISOLATED", True)
    path = tmp_path / "a.md"
    path.write_text("# x\n\ntext", encoding="utf-8")

    def too_slow(*a, **kw):
        raise TimeoutError("late")

    def dies(*a, **kw):
        raise IsolatedError("died")

    monkeypatch.setattr(upload, "run_isolated", too_slow)
    with pytest.raises(UploadError):
        upload._parse(str(path), "general", "a.md")
    monkeypatch.setattr(upload, "run_isolated", dies)
    assert upload._parse(str(path), "general", "a.md") is None  # reads as an unreadable file
