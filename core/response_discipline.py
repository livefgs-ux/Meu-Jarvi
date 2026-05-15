"""Local response discipline helpers for language and truthfulness."""

from __future__ import annotations

import re
import unicodedata

_SPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    raw = _SPACE_RE.sub(" ", (text or "").strip())
    if not raw:
        return ""
    raw = unicodedata.normalize("NFKD", raw)
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return raw.lower()


def portuguese_default_instruction() -> str:
    return (
        "Responda sempre em português brasileiro por padrão, salvo pedido explícito do usuário para outro idioma. "
        "Se a transcrição estiver ruim ou ambígua, peça repetição em português e de forma curta."
    )


def enforce_portuguese_local_reply(text: str) -> str:
    norm = _normalize(text)
    if not norm:
        return "Não entendi com segurança. Pode repetir?"

    if is_explicit_language_change_request(text):
        return text

    translations = (
        ("understood. is there anything else i can assist you with?", "Entendido. Há mais alguma coisa em que eu possa ajudar?"),
        ("understood", "Entendido."),
        ("okay", "Certo."),
        ("ok", "Certo."),
        ("sure", "Claro."),
        ("i did not understand", "Não entendi."),
        ("i didn't understand", "Não entendi."),
        ("can you repeat", "Pode repetir?"),
        ("please repeat", "Pode repetir?"),
        ("could you repeat", "Pode repetir?"),
    )
    for needle, replacement in translations:
        if needle in norm:
            return replacement

    if any(word in norm for word in ("what", "how", "who", "where", "when", "why", "assist")) and "portuguese" not in norm:
        return "Não entendi com segurança. Pode repetir?"

    return text


def is_explicit_language_change_request(text: str) -> bool:
    norm = _normalize(text)
    if not norm:
        return False
    language_markers = (
        "em ingles",
        "em portugues",
        "fale em ingles",
        "fale em portugues",
        "responda em ingles",
        "responda em portugues",
        "speak in english",
        "speak in portuguese",
        "answer in english",
        "answer in portuguese",
        "change language to english",
        "change language to portuguese",
    )
    return any(marker in norm for marker in language_markers)


def tool_truthfulness_instruction() -> str:
    return (
        "Nunca diga que pesquisou, abriu, executou, concluiu ou cancelou algo se a ferramenta correspondente não tiver sido realmente chamada. "
        "Se a intenção estiver incerta, peça clarificação em português. "
        "Não prometa pesquisa, abertura ou execução sem a chamada real da ferramenta."
    )


def concise_clarification(message: str) -> str:
    norm = _normalize(message)
    if not norm:
        return "Não entendi com segurança. Pode repetir?"
    if any(word in norm for word in ("acao", "executar", "fazer", "tool", "ferramenta", "action")):
        return "Não entendi qual ação você quer que eu execute. Pode repetir de forma mais direta?"
    if any(word in norm for word in ("pesquis", "buscar", "abrir", "arquivo", "jogo", "memoria")):
        return "Não entendi com segurança. Pode repetir de forma mais direta?"
    return "Não entendi com segurança. Pode repetir?"
