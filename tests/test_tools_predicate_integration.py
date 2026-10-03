"""Finite query selection stops at the requested output limit."""

from slogger.tools import Field, scan


def test_file_query_stops_reading_at_limit(tmp_path):
    source = tmp_path / "stream.log"
    source.write_text('{"n":1}\nmalformed trailing line\n')
    result = scan(source).filter(Field("n").eq(1)).limit(1).execute()
    assert [row["n"] for row in result.records] == [1]
    assert result.metadata["skipped_lines"] == 0
