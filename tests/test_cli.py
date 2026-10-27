import json
import shutil

import pytest
from helpers import DATA

from pd3f import ocr, output
from pd3f.cli import main

LETTER = DATA / "00004_09212018_bstbk_Unwandlungsgesetz.pdf"
TEXT = LETTER.with_suffix(".txt").read_text()


def test_text_on_stdout(capsys):
    main([str(LETTER)])
    assert capsys.readouterr() == (TEXT, "")


def test_files_in_a_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(output, "tables", lambda result: ["a,b\r\n", "c\r\n"])
    main([str(LETTER), "--out", str(tmp_path / "out")])
    out = tmp_path / "out"
    assert (out / "text.txt").read_text() == TEXT
    assert (out / "text.md").read_text().startswith("Bundesministerium der Justiz")
    decisions = json.loads((out / "decisions.json").read_text())
    assert {"kind", "layer", "start", "end", "uncertain"} <= decisions[0].keys()
    tables = [(out / "tables" / f"{i}.csv").read_bytes() for i in (1, 2)]
    assert tables == [b"a,b\r\n", b"c\r\n"]
    assert not (out / "ocr.pdf").exists()


def test_outputs_go_into_a_new_or_empty_directory(tmp_path, capsys):
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "3.csv").write_text("from an earlier PDF\r\n")
    with pytest.raises(SystemExit):
        main([str(LETTER), "--out", str(tmp_path)])
    error = capsys.readouterr().err
    assert f"--out {tmp_path} must be a new or empty directory" in error
    (tmp_path / "file").write_text("")
    with pytest.raises(SystemExit):
        main([str(LETTER), "--out", str(tmp_path / "file")])


def test_options(capsys):
    main([str(LETTER), "--page-breaks", "--lang", "pl", "--headers-footers", "drop"])
    assert capsys.readouterr().out.count("\f") == 3


def test_errors(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing")
    with pytest.raises(SystemExit, match=f"pd3f: cannot read {broken}"):
        main([str(broken)])
    with pytest.raises(SystemExit, match="no Tesseract language known for pl"):
        main([str(LETTER), "--lang", "pl", "--ocr", "force"])


def test_ocr_is_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        ocr, "ocr", lambda path, out, pages, lang, progress: shutil.copy(path, out)
    )
    main([str(LETTER), "--ocr", "force", "--out", str(tmp_path)])
    assert capsys.readouterr().err == "pd3f: OCR on pages 1, 2, 3\n"
    assert (tmp_path / "ocr.pdf").exists()
