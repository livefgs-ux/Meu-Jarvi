import os
import re
from typing import List, Optional, Dict
from core.runtime_journal import get_runtime_timeline, list_recent_events
from core.task_runtime import get_task_runtime

def get_current_task_summary() -> str:
    """Returns a summary of tasks currently running or pending."""
    runtime = get_task_runtime()
    tasks = runtime.list_tasks()

    def _task_label(task) -> str:
        return getattr(task, "goal", None) or getattr(task, "name", "Tarefa")
    
    running = [t for t in tasks if t.status.name == "RUNNING"]
    pending = [t for t in tasks if t.status.name == "WAITING_RESOURCE" or t.status.name == "QUEUED"]
    
    if not running and not pending:
        return "Não há tarefas em execução ou pendentes no momento."
    
    summary = []
    if running:
        summary.append(f"Tarefas em execução ({len(running)}):")
        for t in running:
            summary.append(f"- {_task_label(t)} (ID: {getattr(t, 'id', getattr(t, 'task_id', 'desconhecido'))})")
            
    if pending:
        summary.append(f"Tarefas aguardando ({len(pending)}):")
        for t in pending:
            summary.append(f"- {_task_label(t)} (ID: {getattr(t, 'id', getattr(t, 'task_id', 'desconhecido'))})")
            
    return "\n".join(summary)

def get_recent_task_summary(limit=10) -> str:
    """Returns a summary of recently finished tasks from the timeline."""
    timeline = get_runtime_timeline()
    events = timeline.list_recent(limit=limit, event_type="task_finished")
    
    if not events:
        return "Não encontrei registros de tarefas concluídas recentemente."
    
    summary = ["Tarefas concluídas recentemente:"]
    for e in events:
        summary.append(f"- {e.summary} ({e.timestamp.split('T')[1].split('.')[0]})")
        
    return "\n".join(summary)

def get_last_tool_result(tool_name: Optional[str] = None) -> Optional[Dict]:
    """Retrieves the result of the last tool execution."""
    timeline = get_runtime_timeline()
    events = timeline.list_recent(limit=20, event_type="tool_result")
    
    for e in events:
        if tool_name is None or e.source == tool_name:
            return {
                "tool": e.source,
                "result": e.summary,
                "timestamp": e.timestamp,
                "metadata": e.metadata
            }
    return None

def get_last_failed_action() -> Optional[Dict]:
    """Retrieves the last failed action or tool error."""
    timeline = get_runtime_timeline()
    # Check tool_error and live_session_error
    events = timeline.list_recent(limit=10, event_type="tool_error")
    session_errors = timeline.list_recent(limit=10, event_type="live_session_error")
    
    all_errs = events + session_errors
    all_errs.sort(key=lambda x: x.timestamp, reverse=True)
    
    if all_errs:
        e = all_errs[0]
        return {
            "type": e.event_type,
            "source": e.source,
            "error": e.summary,
            "timestamp": e.timestamp
        }
    return None

def get_last_search_context() -> Optional[Dict]:
    """Retrieves the context of the last web search."""
    # Try finding tool_called for web_search or tool_result
    timeline = get_runtime_timeline()
    results = timeline.list_recent(limit=20, event_type="tool_result")
    for r in results:
        if r.source == "web_search":
            return {
                "query": r.metadata.get("query", "desconhecida"),
                "result": r.summary,
                "timestamp": r.timestamp
            }
    return None

def get_last_app_resolution_context() -> Optional[Dict]:
    """Retrieves the last app resolution event (trusted or not found)."""
    timeline = get_runtime_timeline()
    # Check for app_not_found or tool_called: open_app
    not_found = timeline.list_recent(limit=10, event_type="app_not_found")
    tool_results = timeline.list_recent(limit=20, event_type="tool_result")
    
    app_results = [r for r in tool_results if r.source == "open_app"]
    
    all_events = not_found + app_results
    all_events.sort(key=lambda x: x.timestamp, reverse=True)
    
    if all_events:
        e = all_events[0]
        return {
            "type": e.event_type,
            "summary": e.summary,
            "metadata": e.metadata,
            "timestamp": e.timestamp
        }
    return None

def get_last_suggested_alternatives() -> List[str]:
    """Retrieves the last suggested alternative apps."""
    timeline = get_runtime_timeline()
    # This might be in app_not_found metadata or in a speak event
    events = timeline.list_recent(limit=5, event_type="app_not_found")
    for e in events:
        alts = e.metadata.get("alternatives", [])
        if alts:
            return alts
    return []

def answer_context_question(text: str) -> dict:
    """Detects contextual questions and provides structured answers."""
    text_low = text.lower()
    
    # Intent Detection Patterns (Portuguese with variations)
    patterns = {
        "current_tasks": [r"task.*andamento", r"o que você está fazendo", r"o que voc. est. fazendo", r"tarefas? atuais?", r"o que está fazendo"],
        "recent_activity": [r"o que você fez", r"o que voc. fez", r"atividades? recentes?", r"últimas tarefas", r"ultimas tarefas"],
        "last_search": [r"qual foi a última busca", r"qual foi a ultima busca", r"o que você buscou", r"o que voc. buscou", r"contexto da busca"],
        "show_last_search": [r"mostra.*busca", r"ver a busca", r"resultado da busca"],
        "last_failure": [r"por que falhou", r"qual foi o erro", r"última falha", r"ultima falha", r"última coisa que você tentou", r"ultima coisa que voce tentou"],
        "app_not_found_reason": [r"por que você não abriu", r"por que voc. n.o abriu", r"por que voce nao abriu", r"não encontrou o app", r"nao encontrou o app"],
        "suggested_alternative": [r"qual alternativa", r"que sugestão", r"que sugestao", r"abre essa alternativa", r"usar essa sugestão", r"usar essa sugestao"]
    }
    
    detected_intent = "unknown_context_query"
    for intent, p_list in patterns.items():
        if any(re.search(p, text_low) for p in p_list):
            detected_intent = intent
            break
            
    if detected_intent == "unknown_context_query":
        return {"intent": detected_intent, "confidence": 0.0}

    # Answer Construction
    res = {
        "intent": detected_intent,
        "confidence": 0.9,
        "answer": "Desculpe, não consegui recuperar essa informação agora.",
        "evidence": "",
        "suggested_action": None
    }
    
    if detected_intent == "current_tasks":
        summary = get_current_task_summary()
        res["answer"] = summary
        res["evidence"] = "Task Runtime State"
        
    elif detected_intent == "recent_activity":
        summary = get_recent_task_summary()
        res["answer"] = summary
        res["evidence"] = "Timeline: task_finished"
        
    elif detected_intent == "last_search":
        ctx = get_last_search_context()
        if ctx:
            res["answer"] = f"A última busca foi por '{ctx['query']}'."
            res["evidence"] = ctx["result"]
        else:
            res["answer"] = "Não encontrei registros de buscas recentes."
            
    elif detected_intent == "show_last_search":
        ctx = get_last_search_context()
        if ctx:
            res["answer"] = f"Aqui está o resultado da última busca por '{ctx['query']}':\n{ctx['result'][:300]}..."
            res["evidence"] = ctx["result"]
        else:
            res["answer"] = "Não há resultado de busca recente para mostrar."
            
    elif detected_intent == "last_failure":
        fail = get_last_failed_action()
        if fail:
            res["answer"] = f"A última falha ocorreu em '{fail['source']}': {fail['error']}"
            res["evidence"] = str(fail)
        else:
            res["answer"] = "Não detectei falhas críticas recentemente."
            
    elif detected_intent == "app_not_found_reason":
        ctx = get_last_app_resolution_context()
        if ctx and ctx["type"] == "app_not_found":
            res["answer"] = f"Não abri o aplicativo porque: {ctx['summary']}"
            res["evidence"] = str(ctx["metadata"])
        else:
            res["answer"] = "Não encontrei registros de aplicativos não encontrados recentemente."
            
    elif detected_intent == "suggested_alternative":
        alts = get_last_suggested_alternatives()
        if "abre" in text_low or "usar" in text_low:
            if alts:
                res["answer"] = f"Entendi. Você se refere à alternativa sugerida: {alts[0]}."
                res["suggested_action"] = {"tool": "open_app", "args": {"app_name": alts[0]}}
            else:
                res["answer"] = "Não tenho uma alternativa recente para abrir."
        else:
            if alts:
                res["answer"] = f"Sugeri as seguintes alternativas recentemente: {', '.join(alts)}."
            else:
                res["answer"] = "Não sugeri alternativas recentemente."
                
    print(f"DEBUG_CTX: intent={res['intent']} text={text}")
    return res
