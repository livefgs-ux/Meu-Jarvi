"""Web search tool with Portuguese-first output discipline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google import genai
from core.response_discipline import portuguese_default_instruction, tool_truthfulness_instruction


def _get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR = _get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"


def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _build_search_prompt(query: str) -> str:
    return (
        f"{portuguese_default_instruction()}\n"
        f"{tool_truthfulness_instruction()}\n"
        "Resuma direto, em português brasileiro, mesmo se a fonte estiver em outro idioma.\n"
        "Se houver comparação, seja objetivo e mantenha a resposta curta.\n"
        "Não prometa pesquisa, abertura ou execução sem a chamada real da ferramenta.\n\n"
        f"Consulta: {query}"
    )


def _gemini_search(query: str) -> str:
    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=_build_search_prompt(query),
        config={"tools": [{"google_search": {}}]},
    )

    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text

    text = text.strip()
    if not text:
        raise ValueError("Gemini returned an empty response.")
    return text


def _ddg_search(query: str, max_results: int = 6) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title": r.get("title", ""),
                "snippet": r.get("body", ""),
                "url": r.get("href", ""),
            })
    return results


def _format_ddg(query: str, results: list[dict]) -> str:
    if not results:
        return f"Nenhum resultado encontrado para: {query}"

    lines = [f"Resultados da pesquisa para: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):
            lines.append(f"{i}. {r['title']}")
        if r.get("snippet"):
            lines.append(f"   {r['snippet']}")
        if r.get("url"):
            lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list[str], aspect: str) -> str:
    query = (
        f"Compare {', '.join(items)} in terms of {aspect}. "
        "Give specific facts and data. Respond in Brazilian Portuguese."
    )
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] Gemini compare failed: {e} - falling back to DDG")

    all_results: dict[str, list] = {}
    for item in items:
        try:
            all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
        except Exception:
            all_results[item] = []

    lines = [f"Comparacao - {aspect.upper()}", "-" * 40]
    for item in items:
        lines.append(f"\n- {item}")
        for r in all_results.get(item, [])[:2]:
            if r.get("snippet"):
                lines.append(f"  * {r['snippet']}")
    return "\n".join(lines)


def web_search(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query = params.get("query", "").strip()
    mode = params.get("mode", "search").lower().strip()
    items = params.get("items", [])
    aspect = params.get("aspect", "general").strip() or "general"

    if not query and not items:
        return "Por favor, informe uma consulta de pesquisa."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] Query: {query!r} Mode: {mode}")

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] Compare done.")
            return result

        print("[WebSearch] Trying Gemini...")
        try:
            result = _gemini_search(query)
            print("[WebSearch] Gemini OK.")
            return result
        except Exception as e:
            print(f"[WebSearch] Gemini failed ({e}) - trying DDG...")
            results = _ddg_search(query)
            result = _format_ddg(query, results)
            print(f"[WebSearch] DDG: {len(results)} result(s).")
            return result

    except Exception as e:
        print(f"[WebSearch] All backends failed: {e}")
        return f"Search failed: {e}"
