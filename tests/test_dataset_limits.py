"""Uploads for analysis: a workbook or Parquet file that unpacks to far more than it weighs is refused before it is read."""
import io
import zipfile

import pandas as pd
import pytest

from src.config import settings
from src.shared.dataset_reader import DatasetReadError, read_table


def small_xlsx() -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame({"a": [1, 2], "b": ["x", "y"]}).to_excel(buffer, index=False)
    return buffer.getvalue()


def small_parquet() -> bytes:
    buffer = io.BytesIO()
    pd.DataFrame({"a": range(5), "b": list("abcde")}).to_parquet(buffer)
    return buffer.getvalue()


def test_ordinary_workbooks_and_parquet_files_are_read_as_before():
    assert read_table(small_xlsx(), "t.xlsx")[0].shape == (2, 2)
    assert read_table(small_parquet(), "t.parquet")[0].shape == (5, 2)


def test_a_workbook_that_unpacks_to_far_more_than_it_weighs_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "DATA_MAX_UNCOMPRESSED_MB", 1)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (3 * 1024 * 1024))   # a few KB on disk, 3 MB unpacked
    assert len(buffer.getvalue()) < 100_000
    with pytest.raises(DatasetReadError) as refused:
        read_table(buffer.getvalue(), "bomb.xlsx")
    assert refused.value.code == "unsafe"


def test_a_workbook_with_too_many_entries_is_refused(monkeypatch):
    from src.shared import dataset_reader

    monkeypatch.setattr(dataset_reader, "_MAX_ARCHIVE_ENTRIES", 3)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for i in range(5):
            archive.writestr(f"x{i}.xml", b"x")
    with pytest.raises(DatasetReadError) as refused:
        read_table(buffer.getvalue(), "many.xlsx")
    assert refused.value.code == "unsafe"


def test_a_parquet_file_with_too_many_rows_or_unpacked_bytes_is_refused_from_its_footer(monkeypatch):
    monkeypatch.setattr(settings, "DATA_MAX_PARQUET_ROWS", 2)
    with pytest.raises(DatasetReadError) as rows:
        read_table(small_parquet(), "big.parquet")
    assert rows.value.code == "unsafe"
    monkeypatch.setattr(settings, "DATA_MAX_PARQUET_ROWS", 5_000_000)
    monkeypatch.setattr(settings, "DATA_MAX_UNCOMPRESSED_MB", 0)
    with pytest.raises(DatasetReadError):
        read_table(small_parquet(), "big.parquet")


def test_the_refusal_has_a_message_in_both_languages():
    from src.agents.data_agent.i18n import tr

    assert "unpacked" in tr("en", "err.unsafe") and "giải nén" in tr("vi", "err.unsafe")
