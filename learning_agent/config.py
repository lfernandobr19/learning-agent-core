import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_data_dir() -> Path:
    raw = os.environ.get("LEARNING_DB", "").strip()
    if raw:
        # On Linux containers, ignore Windows-style absolute paths leaked from the desktop .env.
        if os.name != "nt" and re.match(r"^[A-Za-z]:\\", raw):
            return PROJECT_ROOT / "data"
        return Path(raw)
    return PROJECT_ROOT / "data"


DATA_DIR = _resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLITE_PATH = DATA_DIR / "learning.db"
CHROMA_PATH = DATA_DIR / "chroma"
DOCS_PATH = PROJECT_ROOT / "docs"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# Cloud sync (Supabase snapshot). false = local-only (SQLite + Chroma na máquina).
_cloud_sync_raw = os.environ.get("CLOUD_SYNC_ENABLED", "true").lower()
CLOUD_SYNC_ENABLED = _cloud_sync_raw in {"1", "true", "yes", "on"}

# Auto-sync to Supabase after learning (only when CLOUD_SYNC_ENABLED)
_auto_sync_raw = os.environ.get("AUTO_SYNC", "true").lower()
AUTO_SYNC = CLOUD_SYNC_ENABLED and _auto_sync_raw in {"1", "true", "yes", "on"}
AUTO_SYNC_DEBOUNCE_SECONDS = int(os.environ.get("AUTO_SYNC_DEBOUNCE_SECONDS", "15"))

# Provas reais após cada aprendizado (executa verificações de verdade)
_proofs_raw = os.environ.get("AUTO_PROOFS", "true").lower()
AUTO_PROOFS = _proofs_raw in {"1", "true", "yes", "on"}

API_HOST = os.environ.get("API_HOST", "127.0.0.1")
API_PORT = int(os.environ.get("API_PORT", "8000"))
MCP_HTTP_PORT = int(os.environ.get("MCP_HTTP_PORT", "8001"))

# Knowledge Distillation — teacher (API) → student (local)
TEACHER_API_BASE = os.environ.get("TEACHER_API_BASE", "https://api.openai.com/v1")
TEACHER_API_KEY = os.environ.get("TEACHER_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
TEACHER_MODEL = os.environ.get("TEACHER_MODEL", "openai/gpt-oss-120b").strip()

# DeepSeek V4 — IDE engine "deepseek_pro"
DEEPSEEK_API_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1").rstrip("/")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro").strip()
DEEPSEEK_MODEL_FAST = os.environ.get("DEEPSEEK_MODEL_FAST", "deepseek-v4-flash").strip()

# Manutenção (DeepSeek V4 Pro) — quando Cursor esgotado (MAINTENANCE_MODE)
# ou hop terciário se CHAT + TEACHER falharem
MAINTENANCE_API_BASE = os.environ.get(
    "MAINTENANCE_API_BASE",
    os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com/v1"),
).rstrip("/")
MAINTENANCE_API_KEY = os.environ.get(
    "MAINTENANCE_API_KEY",
    os.environ.get("DEEPSEEK_API_KEY", ""),
).strip()
MAINTENANCE_MODEL = os.environ.get("MAINTENANCE_MODEL", DEEPSEEK_MODEL).strip()
_maintenance_mode_raw = os.environ.get("MAINTENANCE_MODE", "false").lower()
MAINTENANCE_MODE = _maintenance_mode_raw in {"1", "true", "yes", "on"}

# Catalisador RemoteApp — "envia à Ravenna": editores externos (Cursor/VS Code)
# promovem notas ao banco de conhecimento do projeto via /v1/projects/{id}/notes.
# Cada editor tem um token que o identifica (EDITOR_TOKENS).
EDITOR_PROJECT = os.environ.get("EDITOR_PROJECT", "remote_app").strip().lower() or "remote_app"
EDITOR_LOCKED_ENGINE = os.environ.get("EDITOR_LOCKED_ENGINE", "deepseek_pro").strip() or "deepseek_pro"
_editor_tokens_raw = os.environ.get("EDITOR_TOKENS", "").strip()
EDITOR_TOKENS: dict[str, dict[str, str]] = {}
if _editor_tokens_raw:
    try:
        _editor_parsed = json.loads(_editor_tokens_raw)
        if isinstance(_editor_parsed, dict):
            for _editor_tok, _editor_meta in _editor_parsed.items():
                if isinstance(_editor_tok, str) and isinstance(_editor_meta, dict):
                    EDITOR_TOKENS[_editor_tok] = {
                        "user_id": str(_editor_meta.get("user_id") or ""),
                        "name": str(_editor_meta.get("name") or ""),
                    }
    except (json.JSONDecodeError, ValueError, TypeError):
        # Fallback: token único em texto puro (não-JSON) → dono padrão "luis".
        # Evita que um paste simples desligue o auth silenciosamente.
        EDITOR_TOKENS[_editor_tokens_raw] = {"user_id": "luis", "name": "Luis"}
EDITOR_AUTH_ENABLED = bool(EDITOR_TOKENS)

# Gateway "envia à Ravenna" usado pela tool MCP send_to_ravenna (grava no
# servidor via HTTP, de qualquer máquina). REMOTE_GATEWAY_URL_REMOVED aponta para a
# Ravenna; REMOTE_TOKEN_REMOVED é o token Bearer do editor que dispara o gesto.
# Default aponta para o próprio backend (MCP rodando na máquina Ravenna).
# No PC: definir REMOTE_GATEWAY_URL_REMOVED=https://<ip-tailscale>:8000 explicitamente.
REMOTE_GATEWAY_URL_REMOVED = os.environ.get("REMOTE_GATEWAY_URL_REMOVED", "http://127.0.0.1:8000").rstrip("/")
REMOTE_TOKEN_REMOVED = os.environ.get("REMOTE_TOKEN_REMOVED", "").strip()

STUDENT_API_BASE = os.environ.get("STUDENT_API_BASE", "http://localhost:11434/v1")
STUDENT_API_KEY = os.environ.get("STUDENT_API_KEY", "ollama")
STUDENT_MODEL = os.environ.get("STUDENT_MODEL", "phi3:mini")

DISTILL_TEMPERATURE = float(os.environ.get("DISTILL_TEMPERATURE", "0.7"))
DISTILL_SOFT_TEMPERATURE = float(os.environ.get("DISTILL_SOFT_TEMPERATURE", "2.0"))

_auto_distill_raw = os.environ.get("AUTO_DISTILL", "false").lower()
AUTO_DISTILL = _auto_distill_raw in {"1", "true", "yes", "on"}

# Active learning automático
_auto_learn_raw = os.environ.get("AUTO_ACTIVE_LEARN", "false").lower()
AUTO_ACTIVE_LEARN = _auto_learn_raw in {"1", "true", "yes", "on"}
ACTIVE_LEARN_MAX_PER_RUN = int(os.environ.get("ACTIVE_LEARN_MAX_PER_RUN", "3"))

# Autonomia dos agentes — inicia ao subir a API e/ou persiste preferência da IDE
# true = loop de aprendizado em background (opcional; autonomia conversacional funciona sem isso)
_auto_autonomy_raw = os.environ.get("AUTO_AGENT_AUTONOMY", "false").lower()
AUTO_AGENT_AUTONOMY = _auto_autonomy_raw in {"1", "true", "yes", "on"}
AUTONOMY_INTERVAL_SECONDS = int(os.environ.get("AUTONOMY_INTERVAL_SECONDS", "300"))
AUTONOMY_PREFS_PATH = DATA_DIR / "agent_autonomy.json"
AUTONOMY_CONSOLIDATION_EVERY_N = int(os.environ.get("AUTONOMY_CONSOLIDATION_EVERY_N", "12"))
AUTONOMY_GAP_SKILL_THRESHOLD = int(os.environ.get("AUTONOMY_GAP_SKILL_THRESHOLD", "3"))
GAP_RECURRENCE_PATH = DATA_DIR / "gap_recurrence.json"
CAPABILITY_STATE_PATH = DATA_DIR / "agent_capability.json"
AUTONOMY_EVENTS_PATH = DATA_DIR / "autonomy_events.json"
IDE_IMPROVEMENTS_DIR = PROJECT_ROOT / "agents" / "ide-improvements"
IDE_COMPLETION_STATE_PATH = DATA_DIR / "ide_completion.json"
SOFTWARE_EXCELLENCE_STATE_PATH = DATA_DIR / "software_excellence.json"
MODEL_PARITY_STATE_PATH = DATA_DIR / "model_parity.json"

# Paridade cognitiva — mapeie modelos do SEU plano Cursor (via API keys equivalentes)
MODEL_PARITY_TARGET_TIER = os.environ.get("MODEL_PARITY_TARGET_TIER", "balanced")
MODEL_PARITY_REFERENCE_FAST = os.environ.get("MODEL_PARITY_REFERENCE_FAST", STUDENT_MODEL)
MODEL_PARITY_REFERENCE_BALANCED = os.environ.get(
    "MODEL_PARITY_REFERENCE_BALANCED", TEACHER_MODEL
)
MODEL_PARITY_REFERENCE_REASONING = os.environ.get(
    "MODEL_PARITY_REFERENCE_REASONING", TEACHER_MODEL
)
MODEL_PARITY_MIN_SCORE = int(os.environ.get("MODEL_PARITY_MIN_SCORE", "75"))
MODEL_PARITY_STRICT_MIN_SCORE = int(os.environ.get("MODEL_PARITY_STRICT_MIN_SCORE", "80"))
L6_REFINEMENT_EVERY_N_CYCLES = int(os.environ.get("L6_REFINEMENT_EVERY_N_CYCLES", "6"))
# Metodologia pedagógica (1 agente/ciclo: mentor → par → prática → prova → destilar)
_study_structured_raw = os.environ.get("AGENT_STUDY_STRUCTURED", "true").lower()
AGENT_STUDY_STRUCTURED = _study_structured_raw in {"1", "true", "yes", "on"}
AGENT_SPRINT_TESTS_DIR = PROJECT_ROOT / "tests" / "agent_sprints"
SPRINT_ARTIFACTS_DIR = PROJECT_ROOT / "agents" / "collab-sprints" / "artifacts"

# Fine-tune student Ollama
STUDENT_FINETUNE_MODEL = os.environ.get("STUDENT_FINETUNE_MODEL", "raven")
# Base do cérebro raven (Modelfile FROM) — tier alvo para readiness
RAVEN_BASE_MODEL = os.environ.get("RAVEN_BASE_MODEL", STUDENT_MODEL)
# Base de inferência real no Ollama (16GB RAM: use 7b; com 32GB+: use 14b)
RAVEN_RUNTIME_BASE = os.environ.get("RAVEN_RUNTIME_BASE", RAVEN_BASE_MODEL)
# Gemma4 + corpus Ravenna (Fase 4 — Modelfile few-shots, base gemma4-coder)
GEMMA4_RAVEN_MODEL = os.environ.get("GEMMA4_RAVEN_MODEL", "gemma4-raven")
GEMMA4_RUNTIME_BASE = os.environ.get("GEMMA4_RUNTIME_BASE", "gemma4-coder")
GEMMA4_GGUF_PATH = os.environ.get(
    "GEMMA4_GGUF_PATH",
    r"C:/models/gemma4-coder/gemma4-coding-Q3_K_M.gguf",
)
GEMMA4_NUM_CTX = int(os.environ.get("GEMMA4_NUM_CTX", "4096"))
GEMMA4_FEWSHOT_MAX = int(os.environ.get("GEMMA4_FEWSHOT_MAX", "2"))
CHAT_TIMEOUT_SECONDS = float(os.environ.get("CHAT_TIMEOUT_SECONDS", "180"))
RAVEN_READINESS_STATE_PATH = DATA_DIR / "raven_readiness.json"

# Overnight finance-lead runtime profiles
OVERNIGHT_VAST_MODEL = os.environ.get("OVERNIGHT_VAST_MODEL", "qwen2.5:32b")
OVERNIGHT_RAVEN_MODEL = os.environ.get("OVERNIGHT_RAVEN_MODEL", "raven")
FINANCE_OVERNIGHT_DISTILL_EVERY = int(os.environ.get("FINANCE_OVERNIGHT_DISTILL_EVERY", "3"))
FINANCE_OVERNIGHT_32B_BATCH_EVERY = int(os.environ.get("FINANCE_OVERNIGHT_32B_BATCH_EVERY", "6"))
RAVENNA_GPU_HOST = os.environ.get("RAVENNA_GPU_HOST", "pc-do-luis")

# Metas de preparação total da Raven
RAVEN_MIN_DISTILL_PAIRS = int(os.environ.get("RAVEN_MIN_DISTILL_PAIRS", "80"))
RAVEN_MIN_CURSOR_PAIRS = int(os.environ.get("RAVEN_MIN_CURSOR_PAIRS", "30"))
RAVEN_MIN_PAIRS_PER_DOMAIN = int(os.environ.get("RAVEN_MIN_PAIRS_PER_DOMAIN", "10"))
RAVEN_MIN_TRAINING_EXAMPLES = int(os.environ.get("RAVEN_MIN_TRAINING_EXAMPLES", "300"))
RAVEN_MIN_L6_SCORE = int(os.environ.get("RAVEN_MIN_L6_SCORE", "75"))
RAVEN_PREPARED_BASE_MODELS = ("qwen2.5:14b", "qwen2.5:32b", "llama3.1:70b", "llama3.3:70b")

# Fontes externas
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Telegram bot
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
_allowed_raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
TELEGRAM_ALLOWED_USERS: set[int] = {
    int(x.strip()) for x in _allowed_raw.split(",") if x.strip().isdigit()
}

# Ponte Telegram → agente Cursor (cursor-sdk)
CURSOR_API_KEY = os.environ.get("CURSOR_API_KEY", "")
CURSOR_AGENT_MODEL = os.environ.get("CURSOR_AGENT_MODEL", "composer-2.5")
_cursor_bridge_raw = os.environ.get("CURSOR_BRIDGE_ENABLED", "true").lower()
CURSOR_BRIDGE_ENABLED = _cursor_bridge_raw in {"1", "true", "yes", "on"}
CURSOR_BRIDGE_TIMEOUT_SECONDS = float(os.environ.get("CURSOR_BRIDGE_TIMEOUT_SECONDS", "600"))

# Voz — Telegram → Whisper (Groq/OpenAI-compatible)
_speech_raw = os.environ.get("SPEECH_ENABLED", "true").lower()
SPEECH_ENABLED = _speech_raw in {"1", "true", "yes", "on"}
SPEECH_API_BASE = os.environ.get("SPEECH_API_BASE", TEACHER_API_BASE)
SPEECH_API_KEY = os.environ.get("SPEECH_API_KEY", TEACHER_API_KEY)
SPEECH_MODEL = os.environ.get("SPEECH_MODEL", "whisper-large-v3")

# Geolocalização do utilizador — motor Ravenna (contexto runtime, fase 1)
USER_TIMEZONE = os.environ.get("USER_TIMEZONE", "").strip()
USER_CITY = os.environ.get("USER_CITY", "").strip()
USER_REGION = os.environ.get("USER_REGION", "").strip()
USER_COUNTRY = os.environ.get("USER_COUNTRY", "").strip()
USER_LOCALE = os.environ.get("USER_LOCALE", "").strip()
USER_ADDRESS = os.environ.get("USER_ADDRESS", "").strip()

# Chat conversacional (Telegram, API) — assistente pessoal (Raven em standby)
CHAT_MODEL = os.environ.get("CHAT_MODEL", STUDENT_FINETUNE_MODEL)
# Provider local (fallback) — raven (7b), não mais o 0.5b antigo
CHAT_MODEL_FAST = os.environ.get("CHAT_MODEL_FAST", "raven")
# Modo agente / código — motor pesado (Gemma4)
AGENT_MODEL = os.environ.get("AGENT_MODEL", GEMMA4_RAVEN_MODEL)
CHAT_API_BASE = os.environ.get("CHAT_API_BASE", STUDENT_API_BASE)
CHAT_API_KEY = os.environ.get("CHAT_API_KEY", STUDENT_API_KEY)
CHAT_TEMPERATURE = float(os.environ.get("CHAT_TEMPERATURE", "0.7"))
CHAT_HISTORY_LIMIT = int(os.environ.get("CHAT_HISTORY_LIMIT", "10"))
CHAT_MAX_TOKENS = int(os.environ.get("CHAT_MAX_TOKENS", "2048"))
CHAT_IDE_MAX_TOKENS = int(os.environ.get("CHAT_IDE_MAX_TOKENS", "0"))
TELEGRAM_CHAT_MAX_TOKENS = int(os.environ.get("TELEGRAM_CHAT_MAX_TOKENS", "900"))
CHAT_FAST_MAX_TOKENS = int(os.environ.get("CHAT_FAST_MAX_TOKENS", "256"))
CHAT_IDE_HISTORY_LIMIT = int(os.environ.get("CHAT_IDE_HISTORY_LIMIT", "80"))
CHAT_IDE_HISTORY_CONTENT_LIMIT = int(os.environ.get("CHAT_IDE_HISTORY_CONTENT_LIMIT", "2500"))
AGENT_IDE_HISTORY_LIMIT = int(os.environ.get("AGENT_IDE_HISTORY_LIMIT", "40"))
AGENT_HISTORY_CONTENT_LIMIT = int(os.environ.get("AGENT_HISTORY_CONTENT_LIMIT", "2000"))
CHAT_IDE_EDITOR_MAX_CHARS = int(os.environ.get("CHAT_IDE_EDITOR_MAX_CHARS", "20000"))
CHAT_IDE_FILE_SLICE = int(os.environ.get("CHAT_IDE_FILE_SLICE", "2200"))
LLM_PAYLOAD_MAX_CHARS = int(os.environ.get("LLM_PAYLOAD_MAX_CHARS", "250000"))
# API remota (Telegram no PC → stack na VM). Ex.: http://ravenna-vm:8000
RAVENNA_API_BASE = os.environ.get("RAVENNA_API_BASE", "").rstrip("/")
AGENT_GROQ_CONTEXT_MAX = int(os.environ.get("AGENT_GROQ_CONTEXT_MAX", "5000"))
_ide_agent_local_raw = os.environ.get("IDE_AGENT_USE_LOCAL", "true").lower()
IDE_AGENT_USE_LOCAL = _ide_agent_local_raw in {"1", "true", "yes", "on"}
_agent_tool_loop_raw = os.environ.get("AGENT_TOOL_LOOP", "true").lower()
AGENT_TOOL_LOOP = _agent_tool_loop_raw in {"1", "true", "yes", "on"}
AGENT_TOOL_MAX_TURNS = int(os.environ.get("AGENT_TOOL_MAX_TURNS", "8"))
AGENT_MAX_TOKENS = int(os.environ.get("AGENT_MAX_TOKENS", "2048"))

# Tab AI (fill-in-middle) — modelo local de autocomplete via Ollama
COMPLETION_MODEL = os.environ.get("COMPLETION_MODEL", "raven").strip()
COMPLETION_API_BASE = os.environ.get("COMPLETION_API_BASE", CHAT_API_BASE).rstrip("/")
COMPLETION_API_KEY = os.environ.get("COMPLETION_API_KEY", CHAT_API_KEY)
COMPLETION_MAX_TOKENS = int(os.environ.get("COMPLETION_MAX_TOKENS", "64"))
COMPLETION_ENABLED = os.environ.get("COMPLETION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

# Visão multimodal (image_url) — modelo vision usado quando há imagens anexadas
VISION_ENABLED = os.environ.get("VISION_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
VISION_MODEL = os.environ.get("VISION_MODEL", "deepseek-v4-flash-vision-exp").strip()
VISION_API_BASE = os.environ.get("VISION_API_BASE", DEEPSEEK_API_BASE).rstrip("/")
VISION_API_KEY = os.environ.get("VISION_API_KEY", DEEPSEEK_API_KEY).strip()

EDITOR_GATEWAY_URL = ""
EDITOR_TOKEN = ""
