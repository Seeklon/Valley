import asyncio
from pathlib import Path

import pytest
from ignis import knowledge

ROOT = Path(__file__).resolve().parents[1]
REQUEST = knowledge.InsightRequest(config={"scene_id": "soyuz"})


def test_missing_codex_preserves_traceable_evidence(monkeypatch):
    monkeypatch.delenv("IGNIS_CODEX_EXECUTABLE", raising=False)
    result = asyncio.run(knowledge.interpret(ROOT, REQUEST))
    assert result["method"] == "extractive_evidence"
    assert result["model"] is None
    assert {item["id"] for item in result["sources"]} == {"PSI-25", "PSI-26", "PSI-98"}
    assert all(fact["source_id"] in {"PSI-25", "PSI-26", "PSI-98"} for fact in result["facts"])


@pytest.mark.parametrize("answer", [
    "Sans citation.", "Une observation inexistante [PSI-999].", "",
    "Une référence connue [PSI-25] et une inventée [PSI-inconnue].",
    "Une référence connue [PSI-25] et une citation ouverte [PSI-inconnue.",
    "Le ventilateur est documenté [PSI-25].\n\nUne observation sans citation.",
    "Le ventilateur est documenté [PSI-25].\r\n\r\nUne observation sans citation.",
    "Le ventilateur est documenté [PSI-25].\n \nUne observation sans citation.",
    "Une mesure inventée de 999 °C [PSI-25].",
])
def test_codex_cannot_replace_evidence_with_unknown_citations(monkeypatch, tmp_path, answer):
    executable = tmp_path / "codex.exe"
    executable.touch()
    monkeypatch.setenv("IGNIS_CODEX_EXECUTABLE", str(executable))
    monkeypatch.setattr(knowledge, "codex_summary", lambda *args: (answer, "test-model"))
    result = asyncio.run(knowledge.interpret(ROOT, REQUEST))
    assert result["method"] == "extractive_evidence"
    assert result["summary"] != answer
    assert any("citation" in limit for limit in result["limits"])


def test_cited_codex_interpretation_remains_distinct_from_verified_facts(monkeypatch, tmp_path):
    executable = tmp_path / "codex.exe"
    executable.touch()
    monkeypatch.setenv("IGNIS_CODEX_EXECUTABLE", str(executable))
    answer = "Les conditions d’écoulement permettent une comparaison documentaire [PSI-98]."
    monkeypatch.setattr(knowledge, "codex_summary", lambda *args: (answer, "test-model"))
    result = asyncio.run(knowledge.interpret(ROOT, REQUEST))
    assert result["method"] == "codex_grounded_in_nasa_evidence"
    assert result["summary"] == answer
    assert result["facts"] == knowledge.evidence(ROOT, REQUEST)[1]
    assert any("affirmations doivent être confrontées" in limit for limit in result["limits"])


def test_unavailable_codex_has_honest_fallback(monkeypatch, tmp_path):
    executable = tmp_path / "codex.exe"
    executable.touch()
    monkeypatch.setenv("IGNIS_CODEX_EXECUTABLE", str(executable))

    def unavailable(*args):
        raise OSError("executable not available")

    monkeypatch.setattr(knowledge, "codex_summary", unavailable)
    result = asyncio.run(knowledge.interpret(ROOT, REQUEST))
    assert result["method"] == "extractive_evidence"
    assert result["model"] is None
    assert any("indisponible" in limit for limit in result["limits"])
