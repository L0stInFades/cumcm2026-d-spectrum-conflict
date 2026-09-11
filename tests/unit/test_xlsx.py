from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from forge.xlsx import SheetContract, WorkbookContract, check_workbook, read_sheets, sheet_headers, write_result


def _template(path: Path) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "温度"
    ws.append(["时间\\到药材中心的距离", 0, 0.1, "…", 2])
    ws.append([1, None, None, None, None])
    ws2 = wb.create_sheet("水分浓度")
    ws2.append(["时间\\到药材中心的距离", 0, 0.1, "…", 2])
    wb.save(path)
    return path


def test_write_result_keeps_a1_rounds_and_passes_contract(tmp_path: Path) -> None:
    template = _template(tmp_path / "tpl.xlsx")
    header = ["ignored", 0.0, 0.1, 0.2]
    rows = [[t, 28.123456, 28.2, 28.3] for t in range(1, 6)]
    info = write_result(template, tmp_path / "out.xlsx", {"温度": (header, rows), "水分浓度": (header, rows)})
    assert info["sheets"]["温度"]["rows"] == 5
    headers = sheet_headers(tmp_path / "out.xlsx")
    assert headers["温度"][0] == "时间\\到药材中心的距离"
    assert headers["温度"][1:] == [0.0, 0.1, 0.2]
    frames = read_sheets(tmp_path / "out.xlsx")
    assert float(frames["温度"].iloc[0, 1]) == pytest.approx(28.1235)
    contract = WorkbookContract(
        "out.xlsx",
        "tpl.xlsx",
        (
            SheetContract("温度", min_rows=5, max_rows=5, header_len=4, numeric_from_col=0),
            SheetContract("水分浓度", min_rows=5, header_len=4, numeric_from_col=0),
        ),
    )
    report = check_workbook(tmp_path / "out.xlsx", contract, template)
    assert report["ok"], report["errors"]


def test_check_workbook_flags_blank_and_text_cells(tmp_path: Path) -> None:
    template = _template(tmp_path / "tpl.xlsx")
    rows = [[1, 1.0, None, "x"], [2, 2.0, 2.0, 2.0]]
    write_result(template, tmp_path / "out.xlsx", {"温度": (["h", 0, 0.1, 0.2], rows)})
    contract = WorkbookContract("out.xlsx", "tpl.xlsx", (SheetContract("温度", min_rows=2, numeric_from_col=0),))
    report = check_workbook(tmp_path / "out.xlsx", contract, template)
    joined = " ".join(report["errors"])
    assert not report["ok"] and "blank" in joined and "non-numeric" in joined


def test_write_result_rejects_unknown_sheet(tmp_path: Path) -> None:
    template = _template(tmp_path / "tpl.xlsx")
    with pytest.raises(KeyError):
        write_result(template, tmp_path / "out.xlsx", {"nope": (["h"], [])})


def test_write_only_path_for_large_sheets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import forge.xlsx as mod

    monkeypatch.setattr(mod, "BIG_SHEET_CELLS", 10)
    template = _template(tmp_path / "tpl.xlsx")
    rows = [[t, 1.0, 2.0] for t in range(1, 8)]
    info = write_result(template, tmp_path / "big.xlsx", {"温度": (["h", 0, 0.1], rows)})
    assert info["write_only"]
    headers = sheet_headers(tmp_path / "big.xlsx")
    assert list(headers) == ["温度", "水分浓度"]
    assert headers["温度"][0] == "时间\\到药材中心的距离"
