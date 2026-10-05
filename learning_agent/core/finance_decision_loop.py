"""Loop de decisão paper — finance-lead (L6: tese → prova → ação → journal).

Fase 2–3 da estratégia: ler dados, decidir, validar F1/F4/F5, pending + Telegram.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from learning_agent.config import PROJECT_ROOT
from learning_agent.core import agent_action_journal, finance_probes

AGENT = "finance-lead"
PROJECT = "finance-lead-mastery"
FINANCE_ROOT = PROJECT_ROOT / "agents" / "projects" / "finance-lead"
JOURNAL_PATH = FINANCE_ROOT / "data" / "paper_journal.json"
PORTFOLIO_PATH = FINANCE_ROOT / "data" / "paper_portfolio.json"
PENDING_PATH = FINANCE_ROOT / "data" / "pending_decisions.json"
SEQ_STATE_PATH = FINANCE_ROOT / "data" / "decision_seq_state.json"
NEWS_MANIFEST = FINANCE_ROOT / "data" / "economic_news_manifest.json"
DIV_MANIFEST = FINANCE_ROOT / "data" / "diversified_manifest.json"
VALID_TICKERS = FINANCE_ROOT / "fixtures" / "valid_tickers.txt"
LAST_NOTIFY_PATH = FINANCE_ROOT / "data" / "last_decision_notify.json"
DEFAULT_SLIPPAGE = 0.1
PAPER_BUDGET_BRL = float(os.environ.get("FINANCE_PAPER_BUDGET_BRL", "5000"))

_ASSET_CLASS_LABEL = {
    "acoes_br": "ação BR",
    "fii": "FII",
    "etf_br": "ETF BR",
    "etf_internacional": "ETF internacional (USD)",
}


def _portfolio_held_tickers() -> set[str]:
    pf = _load_portfolio()
    return {
        str(p.get("ticker", "")).upper()
        for p in (pf.get("positions") or [])
        if p.get("ticker") and int(p.get("qty") or 0) > 0
    }


def _ticker_asset_class_map(market: dict[str, Any]) -> dict[str, str]:
    return {
        str(t.get("ticker", "")).upper(): str(t.get("asset_class") or "")
        for t in market.get("tickers") or []
    }


def _recent_trade_asset_classes(market: dict[str, Any], *, limit: int = 3) -> set[str]:
    class_map = _ticker_asset_class_map(market)
    journal = _load_journal()
    classes: set[str] = set()
    for trade in reversed(journal.get("trades") or []):
        ac = class_map.get(str(trade.get("ticker", "")).upper(), "")
        if ac:
            classes.add(ac)
        if len(classes) >= limit:
            break
    return classes


def _paper_qty_for_price(price: float, *, decision_id: str) -> int:
    """Sizing paper ~FINANCE_PAPER_BUDGET_BRL com variação leve por ciclo."""
    if price <= 0:
        return 0
    digest = hashlib.md5(decision_id.encode(), usedforsecurity=False).hexdigest()[:4]
    variance_pct = (int(digest, 16) % 21 - 10) / 100  # -10% … +10%
    budget = PAPER_BUDGET_BRL * (1 + variance_pct)
    return max(10, int(budget / price))


def _select_bullish_candidate(market: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Escolhe candidato bullish/emerging evitando recompra e favorecendo rotação."""
    candidates = [
        t
        for t in market.get("tickers", [])
        if t.get("signal") in {"bullish", "emerging"}
    ]
    if not candidates:
        return None, None

    held = _portfolio_held_tickers()
    class_map = _ticker_asset_class_map(market)
    recent_classes = _recent_trade_asset_classes(market)

    def rank(c: dict[str, Any]) -> tuple[int, int, int, float]:
        ticker = str(c.get("ticker", "")).upper()
        ac = class_map.get(ticker, "")
        held_penalty = 1 if ticker in held else 0
        class_penalty = 1 if ac and ac in recent_classes else 0
        signal_penalty = 0 if c.get("signal") == "bullish" else 1
        momentum = -float(c.get("momentum_pct") or 0)
        return (held_penalty, class_penalty, signal_penalty, momentum)

    ranked = sorted(candidates, key=rank)
    best = ranked[0]
    if best["ticker"] in held:
        return None, "Todos os sinais bullish já estão na carteira — aguardar rotação."
    skip_note = None
    if best.get("signal") == "emerging":
        skip_note = f"Sinal emerging (quase cruzamento) em {best['ticker']}."
    if class_map.get(best["ticker"]) in recent_classes and len(ranked) > 1:
        alt = next((c for c in ranked if c["ticker"] not in held), best)
        if alt["ticker"] != best["ticker"]:
            skip_note = f"Rotação: {best['ticker']} → {alt['ticker']} (diversificar classe)."
            best = alt
    return best, skip_note


def _score_ticker_for_ranking(
    t: dict[str, Any],
    *,
    held: set[str],
    class_map: dict[str, str],
    recent_classes: set[str],
) -> float:
    signal_scores = {"bullish": 30.0, "emerging": 18.0, "neutral": 5.0, "bearish": -20.0}
    ticker = str(t.get("ticker", "")).upper()
    score = signal_scores.get(str(t.get("signal") or ""), 0.0)
    score += float(t.get("momentum_pct") or 0)
    if ticker in held:
        score -= 100.0
    ac = class_map.get(ticker, "")
    if ac and ac in recent_classes:
        score -= 8.0
    return round(score, 2)


def build_pick_ranking(market: dict[str, Any], *, limit: int = 5) -> list[dict[str, Any]]:
    """Ranking do universo — o que mais compensa agora (técnico + diversificação)."""
    held = _portfolio_held_tickers()
    class_map = _ticker_asset_class_map(market)
    recent_classes = _recent_trade_asset_classes(market)
    ranked: list[dict[str, Any]] = []
    for t in market.get("tickers") or []:
        ticker = str(t.get("ticker", "")).upper()
        if not ticker:
            continue
        score = _score_ticker_for_ranking(
            t, held=held, class_map=class_map, recent_classes=recent_classes
        )
        ac = class_map.get(ticker, "")
        ac_label = _ASSET_CLASS_LABEL.get(ac, ac or "ativo")
        flags: list[str] = []
        if ticker in held:
            flags.append("já na carteira")
        if str(t.get("signal")) == "bullish":
            flags.append("sinal bullish")
        elif str(t.get("signal")) == "emerging":
            flags.append("quase cruzamento")
        elif str(t.get("signal")) == "bearish":
            flags.append("sinal bearish")
        ranked.append(
            {
                "ticker": ticker,
                "score": score,
                "signal": t.get("signal"),
                "momentum_pct": t.get("momentum_pct"),
                "last_close": t.get("last_close"),
                "asset_class": ac_label,
                "flags": flags,
            }
        )
    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:limit]


def format_pick_ranking(decision: dict[str, Any]) -> str:
    """Resumo Telegram — top picks e por que a escolhida ganhou."""
    ranking = decision.get("pick_ranking") or []
    if not ranking:
        return ""
    pick = str(decision.get("ticker") or "").upper()
    lines = ["O que mais compensa agora (universo monitorado):"]
    for i, row in enumerate(ranking, start=1):
        star = "★ " if row.get("ticker") == pick else "  "
        mom = row.get("momentum_pct")
        mom_txt = f", momentum {mom:+.1f}%" if mom is not None else ""
        flag_txt = f" — {', '.join(row['flags'])}" if row.get("flags") else ""
        lines.append(
            f"{star}#{i} {row['ticker']} ({row.get('asset_class', '?')})"
            f"{mom_txt}{flag_txt}"
        )
    if pick and ranking and ranking[0].get("ticker") != pick:
        top = ranking[0]["ticker"]
        top_flags = ranking[0].get("flags") or []
        if "já na carteira" in top_flags:
            lines.append(f"\nEscolhi {pick} porque {top} já está na carteira paper.")
        else:
            lines.append(f"\nEscolhi {pick} por rotação de classe e diversificação.")
    return "\n".join(lines)


def _market_data_source(market: dict[str, Any]) -> str:
    sources = {str(t.get("data_source") or "") for t in market.get("tickers") or []}
    sources.discard("")
    if "yfinance" in sources:
        return "yfinance"
    return next(iter(sources), "mixed")


def _watch_focus_ticker(market: dict[str, Any], pick_ranking: list[dict[str, Any]]) -> str:
    if pick_ranking:
        return str(pick_ranking[0]["ticker"])
    bench = next((t for t in market.get("tickers", []) if t.get("ticker") == "BOVA11"), None)
    return str(bench.get("ticker") if bench else "BOVA11")


def format_market_brief(decision: dict[str, Any]) -> str:
    """Panorama completo do universo — preço, momentum e sinal por ticker."""
    ranking = decision.get("pick_ranking") or []
    if not ranking:
        return ""
    src = decision.get("data_source") or "yfinance"
    lines = [f"Panorama live ({src}) — {len(ranking)} ativos:"]
    for row in ranking:
        mom = row.get("momentum_pct")
        mom_txt = f"{mom:+.1f}%" if mom is not None else "?"
        price = row.get("last_close")
        price_txt = f"R$ {price}" if price is not None else "?"
        sig = row.get("signal") or next(
            (f.replace("sinal ", "") for f in (row.get("flags") or []) if "sinal" in f or "cruzamento" in f),
            "neutro",
        )
        lines.append(f"  {row['ticker']}: {price_txt} · mom {mom_txt} · {sig}")
    return "\n".join(lines)


def _notify_fingerprint(decision: dict[str, Any]) -> dict[str, Any]:
    ranking = decision.get("pick_ranking") or []
    tops = [
        [r.get("ticker"), round(float(r.get("momentum_pct") or 0), 1), r.get("signal")]
        for r in ranking[:5]
    ]
    return {
        "action": str(decision.get("action") or ""),
        "focus": str(decision.get("ticker") or ""),
        "tops": tops,
    }


def _fingerprints_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return (
        a.get("action") == b.get("action")
        and a.get("focus") == b.get("focus")
        and (a.get("tops") or []) == (b.get("tops") or [])
    )


def _should_skip_watch_notify(decision: dict[str, Any]) -> bool:
    """Evita spam de WATCH idêntico a cada ciclo overnight."""
    mode = os.environ.get("FINANCE_DECISION_NOTIFY_WATCH", "smart").lower()
    if mode in {"always", "1", "true", "all"}:
        return False
    if str(decision.get("action", "")).lower() != "watch":
        return False
    if mode in {"never", "0", "off"}:
        return True
    prev = _read_json(LAST_NOTIFY_PATH, {})
    return _fingerprints_equal(prev.get("fingerprint") or {}, _notify_fingerprint(decision))


def _record_notify(decision: dict[str, Any]) -> None:
    _write_json(
        LAST_NOTIFY_PATH,
        {"fingerprint": _notify_fingerprint(decision), "at": _utcnow()},
    )


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _read_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _valid_ticker_set() -> set[str]:
    if not VALID_TICKERS.is_file():
        return set()
    return {
        line.strip().upper()
        for line in VALID_TICKERS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def load_market_context() -> dict[str, Any]:
    """Resumo por ticker a partir do diversified_manifest / market/*.json."""
    manifest = _read_json(DIV_MANIFEST, {})
    tickers_out: list[dict[str, Any]] = []
    for entry in manifest.get("tickers") or []:
        if not entry.get("success"):
            continue
        rel = str(entry.get("path") or "")
        path = PROJECT_ROOT / rel if rel else Path()
        rows = entry.get("rows") or []
        file_data: dict[str, Any] = {}
        if path.is_file():
            file_data = _read_json(path, {})
            rows = file_data.get("rows") or rows
        closes: list[float] = []
        for row in rows:
            try:
                closes.append(float(row.get("close", 0)))
            except (TypeError, ValueError):
                continue
        if len(closes) < 5:
            continue
        sma5 = _sma(closes, 5)
        sma10 = _sma(closes, 10)
        last = closes[-1]
        momentum = (last - sma5) / sma5 * 100 if sma5 else 0.0
        signal = "neutral"
        if sma5 and sma10:
            gap_pct = (sma5 - sma10) / sma10 * 100
            if sma5 > sma10 and momentum > 0:
                signal = "bullish"
            elif sma5 < sma10 and momentum < 0:
                signal = "bearish"
            elif momentum > 0.25 and gap_pct > -0.8:
                signal = "emerging"
        tickers_out.append(
            {
                "ticker": str(entry.get("ticker", "")).upper(),
                "asset_class": entry.get("asset_class"),
                "last_close": round(last, 2),
                "sma5": round(sma5, 2) if sma5 else None,
                "sma10": round(sma10, 2) if sma10 else None,
                "momentum_pct": round(momentum, 2),
                "signal": signal,
                "bars": len(closes),
                "data_source": entry.get("source") or file_data.get("source", "fixture"),
            }
        )
    return {
        "success": bool(tickers_out),
        "tickers": tickers_out,
        "summary": manifest.get("summary") or {},
        "data_complete": len(tickers_out) >= 4,
    }


def load_news_context(*, limit: int = 3) -> dict[str, Any]:
    manifest = _read_json(NEWS_MANIFEST, {})
    items = (manifest.get("items") or [])[:limit]
    return {
        "success": bool(items),
        "headlines": [str(i.get("title", ""))[:120] for i in items],
        "count": len(items),
    }


def generate_l6_decision(
    market: dict[str, Any] | None = None,
    news: dict[str, Any] | None = None,
    *,
    enrichment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Decisão L6 estruturada — regras + dados (sem ordem live)."""
    market = market or load_market_context()
    news = news or load_news_context()
    enrichment = enrichment or {}
    calendar = enrichment.get("calendar") or {}
    prefer_watch = bool(calendar.get("prefer_watch"))
    decision_id = f"dec-{datetime.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:6]}"
    pick_ranking = build_pick_ranking(market) if market.get("tickers") else []

    def _with_context(base: dict[str, Any]) -> dict[str, Any]:
        h = (enrichment.get("headline") or {}).get("headline")
        if h:
            base["news_context"] = [h]
        base["macro_context"] = enrichment.get("macro_line") or ""
        base["calendar_context"] = enrichment.get("calendar_line") or ""
        if pick_ranking:
            base["pick_ranking"] = pick_ranking
        return base

    if not market.get("data_complete"):
        return _with_context(
            {
                "decision_id": decision_id,
                "action": "hold",
                "side": None,
                "ticker": None,
                "qty": 0,
                "data_complete": False,
                "data_source": "incomplete",
                "premise": "Dados de mercado insuficientes para operar.",
                "thesis": "Recusa operar — F5 incerteza.",
                "risk": "Operar sem ≥4 tickers indexados aumenta risco de decisão cega.",
                "invalidation": "N/A — sem operação.",
                "rollback": "Manter caixa; reavaliar após fetch_diversified_data.",
                "reason": "Dados incompletos: menos de 4 tickers com histórico válido.",
                "news_context": news.get("headlines", [])[:2],
            }
        )

    candidates = [
        t for t in market.get("tickers", []) if t.get("signal") in {"bullish", "emerging"}
    ]
    pick, rotation_note = _select_bullish_candidate(market)
    live_src = _market_data_source(market)

    if not pick and candidates:
        focus = _watch_focus_ticker(market, pick_ranking)
        return _with_context(
            {
                "decision_id": decision_id,
                "action": "watch",
                "side": None,
                "ticker": focus,
                "qty": 0,
                "data_complete": True,
                "data_source": live_src,
                "premise": rotation_note or "Carteira já exposta aos únicos sinais bullish.",
                "thesis": f"Observar {focus} — evitar recompra; aguardar rotação.",
                "risk": "Repetir entrada concentra risco e reduz diversificação paper.",
                "invalidation": "Novo ticker com sinal bullish ou saída parcial da posição existente.",
                "rollback": "Permanece em caixa / posições existentes.",
                "reason": f"watch — diversificação ({focus})",
                "news_context": news.get("headlines", [])[:2],
                "market_snapshot": market.get("tickers", []),
            }
        )

    if not pick:
        focus = _watch_focus_ticker(market, pick_ranking)
        bullish_n = sum(1 for t in market.get("tickers", []) if t.get("signal") == "bullish")
        emerging_n = sum(1 for t in market.get("tickers", []) if t.get("signal") == "emerging")
        return _with_context(
            {
                "decision_id": decision_id,
                "action": "watch",
                "side": None,
                "ticker": focus,
                "qty": 0,
                "data_complete": True,
                "data_source": live_src,
                "premise": (
                    f"Mercado sem compra clara: {bullish_n} bullish, {emerging_n} emerging, "
                    f"resto neutro/bearish. Mais forte agora: {focus}."
                ),
                "thesis": f"Observar {focus} — regime cauteloso; caixa preservada.",
                "risk": "Entrar sem edge quantificado viola disciplina L6.",
                "invalidation": f"{focus} confirma cruzamento SMA5>SMA10 com momentum positivo.",
                "rollback": "Permanece em caixa / posições existentes.",
                "reason": f"watch — {focus} (regime cauteloso)",
                "news_context": news.get("headlines", [])[:2],
                "market_snapshot": market.get("tickers", []),
            }
        )

    ticker = pick["ticker"]
    price = float(pick["last_close"])
    exec_price = round(price * (1 + DEFAULT_SLIPPAGE / 100), 2)
    qty = _paper_qty_for_price(exec_price, decision_id=decision_id)
    ac = pick.get("asset_class") or ""
    ac_label = _ASSET_CLASS_LABEL.get(ac, ac or "ativo")
    headline = (news.get("headlines") or ["sem headline macro"])[0]
    enrich_headline = (enrichment.get("headline") or {}).get("headline")
    if enrich_headline:
        headline = enrich_headline

    thesis_extra = f" Classe: {ac_label}."
    if rotation_note:
        thesis_extra += f" {rotation_note}"

    decision = {
        "decision_id": decision_id,
        "action": "buy",
        "side": "buy",
        "ticker": ticker,
        "qty": qty,
        "price": exec_price,
        "last_close": price,
        "slippage_pct": DEFAULT_SLIPPAGE,
        "asset_class": ac,
        "data_complete": True,
        "data_source": str(pick.get("data_source", "fixture")),
        "premise": f"{ticker} ({ac_label}) SMA5>{pick.get('sma10')} com momentum {pick.get('momentum_pct')}%.",
        "thesis": f"Entrada paper {ticker} — tendência curta + diversificação.{thesis_extra}",
        "risk": "Stop mental -5% do preço; sizing ~1-2% patrimônio paper.",
        "invalidation": f"Fechamento abaixo SMA10 ({pick.get('sma10')}) ou headline macro adversa.",
        "rollback": "Vender posição paper e registrar no journal com motivo.",
        "reason": f"buy {ticker} qty={qty} @~{exec_price} ({pick.get('data_source', 'mixed')})",
        "news_context": [headline],
        "market_snapshot": [pick],
        "macro_context": enrichment.get("macro_line") or "",
        "calendar_context": enrichment.get("calendar_line") or "",
    }

    if prefer_watch:
        event_title = (calendar.get("events_today") or [{}])[0].get("title", "evento macro")
        decision.update(
            {
                "action": "watch",
                "side": None,
                "qty": 0,
                "thesis": f"Observar {ticker} — evento macro hoje ({event_title}).",
                "reason": f"watch — {event_title}; sinal técnico ignorado por calendário",
                "downgraded_from": "buy",
            }
        )

    return decision


def validate_decision_probes(decision: dict[str, Any]) -> dict[str, Any]:
    """F1 backtest + F4 tickers + F5 incerteza + F10 cotações + F11 risco."""
    from learning_agent.core import finance_quote_verify, finance_risk_engine

    results: dict[str, Any] = {"passed": True, "checks": {}}

    f1 = finance_probes.probe_finance_backtest_reproducible()
    results["checks"]["F1"] = f1
    if not f1.get("passed"):
        results["passed"] = False

    action = str(decision.get("action", "")).lower()
    if not decision.get("data_complete") and action not in {"hold", "watch"}:
        results["checks"]["F5"] = {
            "passed": False,
            "detail": "data_complete=false exige action hold|watch",
        }
        results["passed"] = False
    else:
        results["checks"]["F5"] = {"passed": True, "detail": f"action={action}"}

    ticker = decision.get("ticker")
    if ticker and action in {"buy", "sell"}:
        valid = _valid_ticker_set()
        if ticker.upper() not in valid:
            results["checks"]["F4"] = {"passed": False, "detail": f"ticker {ticker} invalido"}
            results["passed"] = False
        else:
            results["checks"]["F4"] = {"passed": True, "detail": f"{ticker} OK"}
    else:
        f4 = finance_probes.probe_finance_ticker_validation()
        results["checks"]["F4"] = f4
        if not f4.get("passed"):
            results["passed"] = False

    if action in {"buy", "sell"} and ticker:
        price = float(decision.get("price") or decision.get("last_close") or 0)
        from learning_agent.core import finance_market_context

        f10 = finance_quote_verify.verify_quote(
            str(ticker),
            price,
            data_source=str(decision.get("data_source") or "mixed"),
            manifest_age_hours=finance_market_context._manifest_age_hours(),
        )
        results["checks"]["F10"] = f10
        if not f10.get("passed"):
            results["passed"] = False

        f11 = finance_risk_engine.check_order(decision)
        results["checks"]["F11"] = f11
        if not f11.get("passed"):
            results["passed"] = False
    else:
        f10_probe = finance_probes.probe_finance_quote_freshness()
        results["checks"]["F10"] = f10_probe
        if not f10_probe.get("passed"):
            results["passed"] = False
        f11_probe = finance_probes.probe_finance_risk_engine()
        results["checks"]["F11"] = f11_probe
        if not f11_probe.get("passed"):
            results["passed"] = False

    return results


def _load_journal() -> dict[str, Any]:
    data = _read_json(JOURNAL_PATH, {"agent": AGENT, "trades": [], "benchmark": "CDI+BOVA11 blend (paper)"})
    if "trades" not in data:
        data["trades"] = []
    return data


def _load_portfolio() -> dict[str, Any]:
    return _read_json(
        PORTFOLIO_PATH,
        {"agent": AGENT, "cash_brl": 100_000.0, "positions": [], "updated_at": _utcnow()},
    )


def _load_seq_state() -> dict[str, Any]:
    return _read_json(SEQ_STATE_PATH, {"next_seq": 1, "by_seq": {}, "by_id": {}})


def _save_seq_state(state: dict[str, Any]) -> None:
    _write_json(SEQ_STATE_PATH, state)


def _bootstrap_seq_state() -> None:
    """Mapeia decisões já registradas para #1, #2, … (migração única)."""
    state = _load_seq_state()
    if state.get("by_id"):
        return
    by_seq: dict[str, str] = {}
    by_id: dict[str, int] = {}
    seq = 1
    journal = _load_journal()
    for trade in journal.get("trades") or []:
        did = trade.get("decision_id")
        if did and did not in by_id:
            by_id[str(did)] = seq
            by_seq[str(seq)] = str(did)
            seq += 1
    pending_doc = _load_pending()
    changed = False
    for item in pending_doc.get("pending") or []:
        did = item.get("decision_id")
        if did and str(did) not in by_id:
            by_id[str(did)] = seq
            by_seq[str(seq)] = str(did)
            item["seq"] = seq
            seq += 1
            changed = True
    if by_id:
        _save_seq_state({"next_seq": seq, "by_seq": by_seq, "by_id": by_id})
        if changed:
            _write_json(PENDING_PATH, pending_doc)


def allocate_seq(decision_id: str) -> int:
    _bootstrap_seq_state()
    state = _load_seq_state()
    seq = int(state.get("next_seq") or 1)
    state["next_seq"] = seq + 1
    state.setdefault("by_seq", {})[str(seq)] = decision_id
    state.setdefault("by_id", {})[decision_id] = seq
    _save_seq_state(state)
    return seq


def resolve_decision_ref(ref: str) -> str | None:
    """Aceita #1, 1 ou dec-… completo."""
    raw = ref.strip().lstrip("#").strip()
    if not raw:
        return None
    if raw.startswith("dec-"):
        return raw
    if raw.isdigit():
        _bootstrap_seq_state()
        state = _load_seq_state()
        full = (state.get("by_seq") or {}).get(raw)
        if full:
            return str(full)
        for item in list_pending_decisions():
            if str(item.get("seq")) == raw:
                return item.get("decision_id")
        return None
    return raw


def seq_label(decision_id: str | None = None, *, seq: int | None = None) -> str:
    if seq is None and decision_id:
        _bootstrap_seq_state()
        state = _load_seq_state()
        seq = (state.get("by_id") or {}).get(decision_id)
        if seq is None:
            for item in list_pending_decisions():
                if item.get("decision_id") == decision_id:
                    seq = item.get("seq")
                    break
    if seq is not None:
        return f"#{int(seq)}"
    return decision_id or "?"


def format_paper_portfolio() -> str:
    pf = _load_portfolio()
    journal = _load_journal()
    cash = float(pf.get("cash_brl") or 0)
    positions = pf.get("positions") or []
    trades = journal.get("trades") or []

    lines = [
        "Carteira paper — finance-lead",
        f"Caixa: R$ {cash:,.2f}",
        "",
        "Posicoes:",
    ]
    if positions:
        for p in positions:
            ticker = p.get("ticker", "?")
            qty = p.get("qty", 0)
            price = p.get("avg_price", 0)
            did = p.get("decision_id")
            tag = seq_label(did) if did else ""
            lines.append(f"  {ticker} {qty} @ R$ {price} {tag}".strip())
    else:
        lines.append("  (vazia)")

    lines.append(f"\nTrades no journal: {len(trades)}")
    recent = trades[-3:]
    if recent:
        lines.append("Ultimos:")
        for t in recent:
            did = t.get("decision_id")
            tag = seq_label(did) if did else ""
            lines.append(
                f"  {tag} {t.get('side', '?')} {t.get('ticker', '')} "
                f"{t.get('qty', 0)} @ {t.get('price', '?')}"
            )
    lines.append("\nPaper only — live_orders=false")
    return "\n".join(lines)


def format_pending_telegram() -> str:
    pending = list_pending_decisions()
    if not pending:
        return "Nenhuma decisao paper pendente."
    lines = ["Decisoes pendentes:"]
    for p in pending[-8:]:
        seq = p.get("seq") or seq_label(p.get("decision_id"))
        why = summarize_decision_plain(p).split(".")[0][:60]
        lines.append(
            f"- {seq if str(seq).startswith('#') else '#' + str(seq)}: "
            f"{p.get('action')} {p.get('ticker') or ''} — {why}"
        )
    lines.append("\n/decision approve <#> | /decision register <#>")
    lines.append("/portfolio — ver carteira paper")
    return "\n".join(lines)


def _load_pending() -> dict[str, Any]:
    return _read_json(PENDING_PATH, {"pending": []})


def save_pending_decision(decision: dict[str, Any], validation: dict[str, Any]) -> dict[str, Any]:
    pending_doc = _load_pending()
    action = str(decision.get("action", "")).lower()
    if action == "watch":
        pending_doc["pending"] = [
            p for p in pending_doc.get("pending", []) if p.get("action") != "watch"
        ]
    seq = allocate_seq(decision["decision_id"])
    entry = {
        **decision,
        "seq": seq,
        "status": "pending",
        "created_at": _utcnow(),
        "validation": validation,
    }
    pending_doc.setdefault("pending", []).append(entry)
    _write_json(PENDING_PATH, pending_doc)
    return entry


def list_pending_decisions() -> list[dict[str, Any]]:
    return list(_load_pending().get("pending") or [])


def _find_pending(decision_id: str) -> tuple[dict[str, Any], int] | tuple[None, None]:
    doc = _load_pending()
    for idx, item in enumerate(doc.get("pending") or []):
        if item.get("decision_id") == decision_id:
            return item, idx
    return None, None


def approve_decision(decision_id: str, *, mode: str = "approve") -> dict[str, Any]:
    """approve = journal + portfolio; register = journal apenas. ID: #1 ou dec-…"""
    resolved = resolve_decision_ref(decision_id)
    if not resolved:
        return {"success": False, "error": f"decisão não encontrada: {decision_id}"}
    decision_id = resolved
    item, idx = _find_pending(decision_id)
    if not item:
        return {"success": False, "error": f"decisão não encontrada: {decision_id}"}

    validation = validate_decision_probes(item)
    if not validation.get("passed"):
        return {"success": False, "error": "probes pre-commit falharam", "validation": validation}

    if item.get("action") in {"buy", "sell"}:
        from learning_agent.core import finance_risk_engine

        risk = finance_risk_engine.check_order(item, portfolio=_load_portfolio())
        if not risk.get("passed"):
            return {
                "success": False,
                "error": "risk engine rejeitou ordem",
                "validation": validation,
                "risk": risk,
            }

    journal = _load_journal()
    trade_note = (
        f"{item.get('action')} {item.get('ticker')} — {item.get('reason', '')[:80]} | "
        f"tese: {str(item.get('thesis', ''))[:60]}"
    )
    trades = journal.setdefault("trades", [])
    next_id = max((int(t.get("id", 0)) for t in trades), default=0) + 1

    if item.get("action") in {"buy", "sell"} and item.get("ticker"):
        trades.append(
            {
                "id": next_id,
                "ticker": item["ticker"],
                "side": item.get("side") or item["action"],
                "qty": item.get("qty", 0),
                "price": item.get("price"),
                "slippage_pct": item.get("slippage_pct", DEFAULT_SLIPPAGE),
                "note": trade_note,
                "decision_id": decision_id,
                "mode": mode,
            }
        )

    journal["updated_at"] = datetime.now().strftime("%Y-%m-%d")
    _write_json(JOURNAL_PATH, journal)

    if item.get("action") in {"buy", "sell"}:
        from learning_agent.core import finance_risk_engine

        finance_risk_engine.record_trade_executed()

    portfolio_updated = False
    if mode == "approve" and item.get("action") in {"buy", "sell"} and item.get("ticker"):
        pf = _load_portfolio()
        positions = pf.setdefault("positions", [])
        qty = int(item.get("qty") or 0)
        price = float(item.get("price") or 0)
        value = qty * price
        if item.get("action") == "buy":
            pf["cash_brl"] = float(pf.get("cash_brl", 0)) - value
            positions.append(
                {
                    "ticker": item["ticker"],
                    "qty": qty,
                    "avg_price": price,
                    "asset_class": item.get("asset_class") or "",
                    "decision_id": decision_id,
                }
            )
        else:
            remaining = qty
            for pos in positions:
                if str(pos.get("ticker", "")).upper() != str(item["ticker"]).upper():
                    continue
                take = min(int(pos.get("qty") or 0), remaining)
                pos["qty"] = int(pos.get("qty") or 0) - take
                remaining -= take
                if remaining <= 0:
                    break
            pf["positions"] = [p for p in positions if int(p.get("qty") or 0) > 0]
            pf["cash_brl"] = float(pf.get("cash_brl", 0)) + value
        pf["updated_at"] = _utcnow()
        _write_json(PORTFOLIO_PATH, pf)
        portfolio_updated = True

    doc = _load_pending()
    doc["pending"] = [p for p in doc.get("pending", []) if p.get("decision_id") != decision_id]
    _write_json(PENDING_PATH, doc)

    agent_action_journal.complete_action_cycle(
        AGENT,
        "finance_paper_decision",
        f"{mode} {decision_id} {item.get('action')} {item.get('ticker')}",
        {"decision": item, "validation": validation, "portfolio_updated": portfolio_updated},
        project=PROJECT,
    )
    return {
        "success": True,
        "decision_id": decision_id,
        "seq": item.get("seq") or seq_label(decision_id).lstrip("#"),
        "mode": mode,
        "portfolio_updated": portfolio_updated,
        "journal_trades": len(trades),
    }


def _context_extras(decision: dict[str, Any]) -> str:
    bits: list[str] = []
    headlines = decision.get("news_context") or []
    if headlines and headlines[0] and headlines[0] != "sem headline macro":
        bits.append(f"Notícia: {headlines[0][:100]}.")
    macro = str(decision.get("macro_context") or "").strip()
    if macro:
        bits.append(macro)
    cal = str(decision.get("calendar_context") or "").strip()
    if cal:
        bits.append(cal)
    return " ".join(bits)


def summarize_decision_plain(decision: dict[str, Any]) -> str:
    """Motivo simplificado para Telegram — 1–2 frases, sem jargão."""
    action = str(decision.get("action", "")).lower()
    ticker = decision.get("ticker") or "—"
    snap = (decision.get("market_snapshot") or [{}])[0]
    if isinstance(snap, dict) and snap:
        last = snap.get("last_close")
        mom = snap.get("momentum_pct")
        sma5 = snap.get("sma5")
        sma10 = snap.get("sma10")
        signal = snap.get("signal", "neutral")
    else:
        last = mom = sma5 = sma10 = None
        signal = "neutral"

    if action == "buy":
        ac = decision.get("asset_class") or ""
        ac_label = _ASSET_CLASS_LABEL.get(ac, "")
        parts = [f"Sugiro compra paper em {ticker}"]
        if ac_label:
            parts.append(f"({ac_label})")
        if last is not None:
            parts.append(f"preço ref. R$ {last}")
        if sma5 is not None and sma10 is not None:
            parts.append(f"média 5d ({sma5}) acima da 10d ({sma10})")
        if mom is not None:
            parts.append(f"momentum +{mom}% nas últimas barras")
        parts.append("→ tendência curta favorável no universo monitorado")
        body = ". ".join(parts) + "."
        extras = _context_extras(decision)
        return (body + " " + extras).strip() if extras else body

    if action == "sell":
        return (
            f"Sugiro venda paper em {ticker}: sinal de enfraquecimento "
            f"(médias ou momentum viraram contra a posição)."
        )

    if action == "watch":
        t = ticker if ticker != "—" else "BOVA11"
        top = (decision.get("pick_ranking") or [{}])[0]
        top_t = top.get("ticker") or t
        base = (
            f"Sem compra paper agora — mercado cauteloso. "
            f"Ativo mais forte no radar: {top_t}. "
            f"Observar {t} antes de alocar os R$ 5.000."
        )
        cal = str(decision.get("calendar_context") or "").strip()
        if decision.get("downgraded_from") == "buy":
            base = (
                f"Havia sinal de compra em {ticker}, mas hoje tem evento macro importante — "
                f"melhor observar do que operar."
            )
        if cal:
            base += f" {cal}"
        return base

    if action == "hold":
        if not decision.get("data_complete"):
            return (
                "Sem operar: dados de mercado incompletos (<4 tickers). "
                "Preciso de mais histórico antes de sugerir qualquer ação."
            )
        return "Manter caixa/posições — condições não justificam mudança neste ciclo."

    premise = str(decision.get("premise", "")).strip()
    if premise:
        return premise[:220]
    return str(decision.get("reason", "Sem motivo registrado."))[:220]


def is_auto_paper_mode(mode: str | None = None) -> bool:
    approval_mode = (mode or os.environ.get("FINANCE_DECISION_MODE", "assisted")).lower()
    return approval_mode in {"autonomous", "auto", "paper", "autonomous_paper"}


def format_autonomous_decision_telegram(
    decision: dict[str, Any],
    validation: dict[str, Any],
    commit: dict[str, Any],
) -> str:
    """Resumo pós-execução paper — sem pedir aprovação manual."""
    seq = decision.get("seq")
    label = f"#{seq}" if seq else seq_label(decision.get("decision_id"))
    action = str(decision.get("action", "")).upper()
    ticker = decision.get("ticker") or ""

    if not commit.get("success"):
        risk = commit.get("risk") or {}
        detail = risk.get("detail") or commit.get("error") or "rejeitado pelo motor de risco"
        return "\n".join(
            [
                "Finance-lead — paper AUTO (bloqueado)",
                f"ID: {label}",
                f"Intent: {action} {ticker}".strip(),
                f"Motivo: {detail}",
                "",
                "/portfolio — carteira | /performance — graduação",
            ]
        )

    if action in {"WATCH", "HOLD"}:
        return "\n".join(
            [
                "Finance-lead — paper AUTO (observar)",
                f"ID: {label}",
                summarize_decision_plain(decision),
                "",
                "/performance — progresso graduação",
            ]
        )

    qty = decision.get("qty")
    price = decision.get("price")
    operacao = f"{action} {ticker}".strip()
    if qty and price and action in {"BUY", "SELL"}:
        operacao += f" · {qty} @ R$ {price}"

    return "\n".join(
        [
            "Finance-lead — paper AUTO executado",
            f"ID: {label}",
            f"Operacao: {operacao}",
            "",
            summarize_decision_plain(decision),
            "",
            f"Probes: {'OK' if validation.get('passed') else 'FALHOU'} | live_orders=false",
            "/portfolio — carteira | /performance — graduação",
        ]
    )


def format_decision_telegram(decision: dict[str, Any], validation: dict[str, Any]) -> str:
    seq = decision.get("seq")
    label = f"#{seq}" if seq else seq_label(decision.get("decision_id"))
    ref = str(seq) if seq else decision.get("decision_id", "")
    action = str(decision.get("action", "")).upper()
    ticker = decision.get("ticker") or ""
    qty = decision.get("qty")
    price = decision.get("price")
    operacao = f"{action} {ticker}".strip()
    if qty and price and action in {"BUY", "SELL"}:
        operacao += f" · {qty} @ R$ {price}"

    ranking_block = format_pick_ranking(decision)
    brief_block = format_market_brief(decision)
    lines = [
        "Finance-lead — decisao paper (L6)",
        f"ID: {label}",
        f"Acao: {operacao}",
        "",
        "Por que:",
        summarize_decision_plain(decision),
    ]
    if brief_block:
        lines.extend(["", brief_block])
    if ranking_block:
        lines.extend(["", ranking_block])
    lines.extend(
        [
            "",
            f"Probes: {'OK' if validation.get('passed') else 'FALHOU'}",
            "",
            "Comandos:",
            f"/decision approve {ref}",
            f"/decision register {ref}",
            "/portfolio — ver carteira",
            "",
            "Ou responda esta mensagem: sim · aprovo · registrar · não",
        ]
    )
    return "\n".join(lines)


def run_decision_cycle(*, notify: bool | None = None) -> dict[str, Any]:
    """Ciclo completo: contexto → decisão → probes → pending → Telegram."""
    from learning_agent.core import finance_market_context, finance_risk_engine

    approval_mode = os.environ.get("FINANCE_DECISION_MODE", "assisted").lower()
    if approval_mode in {"off", "false", "0", "disabled"}:
        return {"success": True, "skipped": True, "reason": "FINANCE_DECISION_MODE=off"}

    kill, kill_reason = finance_risk_engine.is_kill_switch_active()
    if kill:
        return {
            "success": True,
            "skipped": True,
            "reason": f"kill_switch: {kill_reason}",
            "action": "finance_decision_cycle",
        }

    enrichment = finance_market_context.prepare_decision_context(force_market=True)
    market = load_market_context()
    news = load_news_context()
    decision = generate_l6_decision(market, news, enrichment=enrichment)
    validation = validate_decision_probes(decision)

    if not validation.get("passed"):
        return {
            "success": False,
            "action": "finance_decision_cycle",
            "decision": decision,
            "validation": validation,
            "error": "probes pre-commit falharam",
        }

    auto_paper = is_auto_paper_mode(approval_mode)
    pending = save_pending_decision(decision, validation)
    if auto_paper:
        result = approve_decision(decision["decision_id"], mode="approve")
    else:
        result = {"success": True, "status": "pending"}

    action = str(decision.get("action") or "").lower()
    if notify is not None:
        should_notify = notify
    elif auto_paper:
        if action in {"watch", "hold"}:
            should_notify = not _should_skip_watch_notify(decision)
        else:
            should_notify = True
    else:
        should_notify = True

    telegram = {"sent": False}
    if should_notify:
        from learning_agent.core import telegram_alerts

        if auto_paper:
            msg = format_autonomous_decision_telegram(decision, validation, result)
            telegram = telegram_alerts.send_alert(msg)
            _record_notify(decision)
        elif _should_skip_watch_notify(decision):
            telegram = {"sent": False, "skipped": True, "reason": "watch regime inalterado"}
        else:
            telegram = telegram_alerts.send_alert(format_decision_telegram(decision, validation))
            _record_notify(decision)
            if telegram.get("sent") and telegram.get("message_id") and telegram.get("chat_id"):
                from learning_agent.core import finance_telegram_replies

                finance_telegram_replies.register_decision_message(
                    message_id=int(telegram["message_id"]),
                    chat_id=int(telegram["chat_id"]),
                    seq=pending.get("seq") or "",
                    decision_id=str(decision["decision_id"]),
                )

    cycle_ok = bool(validation.get("passed"))
    if auto_paper and action in {"buy", "sell"}:
        cycle_ok = cycle_ok and bool(result.get("success"))

    agent_action_journal.complete_action_cycle(
        AGENT,
        "finance_decision_cycle",
        f"{decision.get('action')} {decision.get('ticker')}",
        {"decision": decision, "validation": validation, "result": result},
        project=PROJECT,
    )
    return {
        "success": cycle_ok,
        "action": "finance_decision_cycle",
        "decision": decision,
        "validation": validation,
        "pending": pending,
        "commit": result,
        "telegram": telegram,
        "mode": approval_mode,
        "enrichment": {
            "market_refresh": enrichment.get("refresh"),
            "macro_ok": (enrichment.get("macro") or {}).get("success"),
            "calendar": enrichment.get("calendar"),
        },
    }
