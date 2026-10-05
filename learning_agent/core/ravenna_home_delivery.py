"""Contrato de entrega Ravenna Home — validação estática, guards de write e aceite Cursor."""

from __future__ import annotations

import json
import re
import difflib
from pathlib import Path
from typing import Any

_FORBIDDEN_IMPORTS = (
    "react-router-dom",
    "react-router",
    "@tanstack/react-router",
)
_FORBIDDEN_APP_PATTERNS = (
    (r"\bBrowserRouter\b", "PROIBIDO `BrowserRouter` — use abas com `useState`, sem react-router."),
    (r"\bRoutes\b", "PROIBIDO `Routes` — use abas com `useState`."),
    (r"\bRoute\b", "PROIBIDO `Route` — use abas com `useState`."),
    (r"from ['\"]\.\./components/Layout", "Import quebrado: use `import Layout from './Layout'`."),
    (r"from ['\"]\./components/Layout", "Import quebrado: use `import Layout from './Layout'`."),
    (r"\bGpuStatus\b", "Remova GPU — apenas abas Chat | Casa."),
    (r"['\"]GPU['\"]", "Remova aba GPU — apenas Chat | Casa."),
)
_SPACE_CHAT_CSS_MARKERS = ("neon", "glow", "nebula", "space-bg", "starfield", "tab-bar")
MIN_PRODUCTION_CSS_BYTES = 400
MIN_SOURCE_CSS_BYTES = 800
_CSS_PLACEHOLDER_HINTS = ("path/to/", "placeholder", "todo-fix", "your-image")
_PRODUCTION_CSS_MARKERS = (
    "tab-bar",
    "chat-fullscreen",
    "neon",
    "space-bg",
    "starfield",
    ".stars",
    "100dvh",
    "100vh",
    "radial-gradient",
)
_PRODUCTION_CSS_REQUIRED = ("tab-bar", "chat-fullscreen", "--ravenna-accent")
_SPACE_CHAT_APP_MARKERS = ("useState", "Chat", "Casa", "./Layout")

SPACE_CHAT_APP_TSX = """\
import { useState } from 'react';
import Layout from './Layout';
import { Chat, Lights, Scenes } from './components';

type Tab = 'Chat' | 'Casa';

const TABS: Tab[] = ['Chat', 'Casa'];

export default function App() {
  const [tab, setTab] = useState<Tab>('Chat');

  return (
    <Layout>
      <nav className="tab-bar" role="tablist" aria-label="Navegação principal">
        {TABS.map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            className={tab === id ? 'tab active' : 'tab'}
            onClick={() => setTab(id)}
          >
            {id}
          </button>
        ))}
      </nav>
      <div className="tab-panel" role="tabpanel">
        {tab === 'Chat' && <Chat />}
        {tab === 'Casa' && (
          <>
            <Lights />
            <Scenes />
          </>
        )}
      </div>
    </Layout>
  );
}
"""


def _chat_api_integrity(text: str) -> str | None:
    if "export default" in text and "export function Chat" not in text:
        return "Chat.tsx deve usar `export function Chat` (named export) — App importa de `./components`."
    if "export function Chat" not in text and "export const Chat" not in text:
        return "Chat.tsx deve exportar `Chat` como named export."
    if "../api" not in text and "from '../api'" not in text and "api<" not in text and "api(" not in text:
        return "Chat.tsx deve preservar integração API (`import { api } from '../api'`)."
    lower = text.lower()
    if re.search(r"fetch\s*\(\s*['\"]https?://", text, re.I) and "/api/chat" not in lower:
        return "Chat.tsx: PROIBIDO fetch para API externa — use api() com /api/chat/history e POST /api/chat."
    if len(text.encode("utf-8")) < 400:
        return "Chat.tsx truncado — preserve histórico, send() e integração com `/api/chat`."
    return None


SPACE_CHAT_CHAT_TSX = """\
import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

type Msg = { role: 'user' | 'assistant'; content: string };
const STORAGE_KEY = 'ravenna-home-conversation-id';

export function Chat() {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [loading, setLoading] = useState(false);
  const [booting, setBooting] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY) || '';
    if (!saved) {
      setBooting(false);
      return;
    }
    setConversationId(saved);
    api<{ messages?: Array<{ role?: string; content?: string }> }>(
      `/api/chat/history?conversation_id=${encodeURIComponent(saved)}`,
    )
      .then((data) => {
        const rows = (data.messages || [])
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: String(m.content || ''),
          }));
        setMessages(rows);
      })
      .catch(() => undefined)
      .finally(() => setBooting(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  async function send() {
    const text = message.trim();
    if (!text || loading) return;
    setMessage('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const data = await api<{ message?: string; conversation_id?: string }>('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          mode: 'chat',
          conversation_id: conversationId,
        }),
      });
      const cid = data.conversation_id || conversationId;
      if (cid && cid !== conversationId) {
        setConversationId(cid);
        localStorage.setItem(STORAGE_KEY, cid);
      }
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: data.message || '(sem resposta)' },
      ]);
    } catch (e) {
      const err =
        e instanceof Error
          ? e.message
          : 'Motor de IA indisponível. Tente de novo em instantes.';
      setMessages((prev) => [...prev, { role: 'assistant', content: err }]);
    } finally {
      setLoading(false);
    }
  }

  function clearHistory() {
    localStorage.removeItem(STORAGE_KEY);
    setConversationId('');
    setMessages([]);
  }

  return (
    <section className="chat-fullscreen card chat-card">
      <div className="card-header">
        <h2>Chat Ravenna</h2>
        {messages.length > 0 ? (
          <button type="button" className="btn-ghost" onClick={clearHistory}>
            Nova conversa
          </button>
        ) : null}
      </div>
      <div className="chat-log" aria-live="polite">
        {booting ? <p className="muted">Carregando histórico…</p> : null}
        {!booting && messages.length === 0 ? (
          <p className="muted">Pergunte qualquer coisa — casa, PC, notícias, pesquisas…</p>
        ) : null}
        {messages.map((m, i) => (
          <div key={`${i}-${m.role}`} className={`bubble bubble-${m.role}`}>
            {m.content}
          </div>
        ))}
        {loading ? <div className="bubble bubble-assistant muted">Ravenna pensando…</div> : null}
        <div ref={bottomRef} />
      </div>
      <textarea
        rows={2}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder="Fale com a Ravenna…"
      />
      <div className="chat-actions">
        <button type="button" onClick={send} disabled={loading}>
          {loading ? 'Enviando…' : 'Enviar'}
        </button>
      </div>
    </section>
  );
}
"""

VOICE_PWA_CHAT_TSX = """\
import { useEffect, useRef, useState } from 'react';
import { api } from '../api';

type Msg = { role: 'user' | 'assistant'; content: string };
const STORAGE_KEY = 'ravenna-home-conversation-id';

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((ev: { results: { [i: number]: { [j: number]: { transcript: string } } } }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
};

function getSpeechRecognition(): (new () => SpeechRecognitionLike) | null {
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function Chat() {
  const [message, setMessage] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [conversationId, setConversationId] = useState('');
  const [loading, setLoading] = useState(false);
  const [booting, setBooting] = useState(true);
  const [isListening, setIsListening] = useState(false);
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY) || '';
    if (!saved) {
      setBooting(false);
      return;
    }
    setConversationId(saved);
    api<{ messages?: Array<{ role?: string; content?: string }> }>(
      `/api/chat/history?conversation_id=${encodeURIComponent(saved)}`,
    )
      .then((data) => {
        const rows = (data.messages || [])
          .filter((m) => m.role === 'user' || m.role === 'assistant')
          .map((m) => ({
            role: m.role as 'user' | 'assistant',
            content: String(m.content || ''),
          }));
        setMessages(rows);
      })
      .catch(() => undefined)
      .finally(() => setBooting(false));
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  function speakResponse(text: string) {
    if (!voiceEnabled || !text.trim()) return;
    window.speechSynthesis.cancel();
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = 'pt-BR';
    window.speechSynthesis.speak(utter);
  }

  async function send(textOverride?: string) {
    const text = (textOverride ?? message).trim();
    if (!text || loading) return;
    setMessage('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);
    setLoading(true);
    try {
      const data = await api<{ message?: string; conversation_id?: string }>('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: text,
          mode: 'chat',
          conversation_id: conversationId,
        }),
      });
      const cid = data.conversation_id || conversationId;
      if (cid && cid !== conversationId) {
        setConversationId(cid);
        localStorage.setItem(STORAGE_KEY, cid);
      }
      const reply = data.message || '(sem resposta)';
      setMessages((prev) => [...prev, { role: 'assistant', content: reply }]);
      speakResponse(reply);
    } catch (e) {
      const err =
        e instanceof Error
          ? e.message
          : 'Motor de IA indisponível. Tente de novo em instantes.';
      setMessages((prev) => [...prev, { role: 'assistant', content: err }]);
    } finally {
      setLoading(false);
    }
  }

  function toggleVoiceInput() {
    const SR = getSpeechRecognition();
    if (!SR) {
      setMessage('Microfone indisponível neste navegador.');
      return;
    }
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    const rec = new SR();
    rec.lang = 'pt-BR';
    rec.continuous = false;
    rec.interimResults = false;
    rec.onresult = (ev) => {
      const transcript = ev.results[0]?.[0]?.transcript || '';
      if (transcript.trim()) {
        setMessage(transcript);
        void send(transcript);
      }
    };
    rec.onend = () => setIsListening(false);
    recognitionRef.current = rec;
    setIsListening(true);
    rec.start();
  }

  function clearHistory() {
    localStorage.removeItem(STORAGE_KEY);
    setConversationId('');
    setMessages([]);
  }

  return (
    <section className="chat-fullscreen card chat-card">
      <div className="card-header">
        <h2>Chat Ravenna</h2>
        <label className="voice-toggle">
          <input
            type="checkbox"
            checked={voiceEnabled}
            onChange={(e) => setVoiceEnabled(e.target.checked)}
          />
          Voz da Ravenna
        </label>
        {messages.length > 0 ? (
          <button type="button" className="btn-ghost" onClick={clearHistory}>
            Nova conversa
          </button>
        ) : null}
      </div>
      <div className="chat-log" aria-live="polite">
        {booting ? <p className="muted">Carregando histórico…</p> : null}
        {!booting && messages.length === 0 ? (
          <p className="muted">Pergunte qualquer coisa — casa, PC, notícias, pesquisas…</p>
        ) : null}
        {messages.map((m, i) => (
          <div key={`${i}-${m.role}`} className={`bubble bubble-${m.role}`}>
            {m.content}
          </div>
        ))}
        {loading ? <div className="bubble bubble-assistant muted">Ravenna pensando…</div> : null}
        <div ref={bottomRef} />
      </div>
      <textarea
        rows={2}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void send();
          }
        }}
        placeholder="Fale com a Ravenna…"
      />
      <div className="chat-actions">
        <button
          type="button"
          className={isListening ? 'mic-button pulse' : 'mic-button'}
          aria-label="Microfone"
          onClick={toggleVoiceInput}
        >
          🎤
        </button>
        <button type="button" onClick={() => void send()} disabled={loading}>
          {loading ? 'Enviando…' : 'Enviar'}
        </button>
      </div>
    </section>
  );
}
"""

VOICE_PWA_INSTALL_PROMPT_TSX = """\
import { useEffect, useState } from 'react';

type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: string }>;
};

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [showIos, setShowIos] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };
    window.addEventListener('beforeinstallprompt', handler);
    const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const standalone = window.matchMedia('(display-mode: standalone)').matches;
    if (isIos && !standalone) setShowIos(true);
    return () => window.removeEventListener('beforeinstallprompt', handler);
  }, []);

  async function installPwa() {
    if (!deferredPrompt) return;
    await deferredPrompt.prompt();
    await deferredPrompt.userChoice;
    setDeferredPrompt(null);
  }

  if (!deferredPrompt && !showIos) return null;

  return (
    <div className="install-pwa-banner card">
      {deferredPrompt ? (
        <>
          <p>Instalar Ravenna no celular</p>
          <button type="button" onClick={() => void installPwa()}>
            Instalar
          </button>
        </>
      ) : (
        <p>Adicionar à Tela de Início: Compartilhar → Adicionar à Tela de Início</p>
      )}
    </div>
  );
}
"""

VOICE_PWA_LAYOUT_TSX = """\
import type { ReactNode } from 'react';
import { InstallPrompt } from './components/InstallPrompt';

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell space-bg">
      <InstallPrompt />
      <main className="app-main">{children}</main>
    </div>
  );
}
"""

_PWA_MANIFEST = {
    "name": "Ravenna Home",
    "short_name": "Ravenna",
    "display": "standalone",
    "theme_color": "#1a1a2e",
    "background_color": "#0f0f1a",
    "start_url": "/",
    "icons": [
        {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
        {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ],
}


def ui_mode_from_prompt(prompt: str) -> str | None:
    lowered = (prompt or "").lower()
    if any(m in lowered for m in ("rh-12n", "golden-d2", "patch-d2-gemini", "golden patch d2")):
        return "chat-patch-d2-gemini"
    if any(m in lowered for m in ("rh-12m", "patch-d2", "d2 strict", "micro-patch d2")):
        return "chat-patch-d2-strict-gemini"
    if any(m in lowered for m in ("rh-12l-golden", "golden-d1", "patch-d1-gemini", "golden patch d1")):
        return "chat-patch-d1-gemini"
    if any(m in lowered for m in ("rh-12l", "patch-d1", "d1 strict", "micro-patch d1")):
        return "chat-patch-d1-strict-gemini"
    if any(m in lowered for m in ("rh-12k", "patch-d strict", "strict autonomy", "sem golden fallback")):
        return "chat-patch-d-strict-gemini"
    if any(m in lowered for m in ("rh-12j", "chat-patch-d-gemini", "patch-d gemini", "sem golden")):
        return "chat-patch-d-gemini"
    if any(m in lowered for m in ("rh-12h", "chat-patch-c-gemini", "patch-c gemini")):
        return "chat-patch-c-gemini"
    if any(m in lowered for m in ("rh-12g", "chat-patch-b-gemini", "patch-b gemini")):
        return "chat-patch-b-gemini"
    if any(m in lowered for m in ("rh-12f", "chat-patch-a-gemini", "patch-a gemini", "golden patch")):
        return "chat-patch-a-gemini"
    if any(m in lowered for m in ("rh-12e", "chat-patch-gemini", "patch gemini")):
        return "chat-patch-gemini"
    if any(m in lowered for m in ("rh-12d", "gemini-copy", "copiar referência")):
        return "chat-history-autonomy"
    if any(m in lowered for m in ("rh-12c-v2", "chat-history-autonomy", "autonomy-only")):
        return "chat-history-autonomy"
    if any(m in lowered for m in ("rh-12c", "chat-history-gemini", "chat-history only")):
        return "chat-history-gemini"
    if any(m in lowered for m in ("rh-12b-v2", "chat-tests", "main.py lock")):
        return "backend-tests-only"
    if any(m in lowered for m in ("rh-12b", "backend-web", "backend web")):
        return "web-gemini-backend"
    if any(m in lowered for m in ("rh-12", "web-gemini", "web search + hist")):
        return "web-gemini"
    if any(m in lowered for m in ("rh-11", "gemini-space", "espaço sideral", "espaco sideral", "layout gemini")):
        return "gemini-space"
    if any(m in lowered for m in ("rh-10", "visual-identity", "concierge orbital", "identidade visual")):
        return "visual-identity"
    if any(m in lowered for m in ("rh-09", "voz", "voice", "speech", "microfone", "instalar app", "pwa install", "download celular")):
        return "voice-pwa"
    if any(m in lowered for m in ("rh-08", "full-screen", "full screen", "espaço", "espaco", "neon")):
        return "space-chat"
    if any(m in lowered for m in ("rh-07", "3 abas", "cursor-bar", "ui pro")):
        return "tabs-v1"
    return None


def apply_ui_mode(spec: dict[str, Any], *, prompt: str) -> dict[str, Any]:
    mode = ui_mode_from_prompt(prompt)
    if mode:
        spec["ravennaHomeUiMode"] = mode
    if mode == "space-chat":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = True
        spec["allowedPaths"] = [
            "src/index.css",
            "src/Layout.tsx",
            "theme",
        ]
        if "rh-14" in prompt.lower():
            spec["requireGroundingTools"] = True
            spec["requiredGroundingReads"] = [
                "theme/tokens.css",
                "theme/gemini-space-index.css",
                "src/index.css",
            ]
    elif mode == "voice-pwa":
        spec["ravennaHomeLockApp"] = True
        spec["requireGroundingTools"] = True
        spec["requiredGroundingReads"] = [
            "package.json",
            "src/components/Chat.tsx",
            "src/components/InstallPrompt.tsx",
            "public/manifest.webmanifest",
            "index.html",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
            "src/components/InstallPrompt.tsx",
            "src/hooks",
            "src/index.css",
            "src/Layout.tsx",
            "index.html",
            "public",
            "theme",
            "backend/main.py",
            "backend/speech_proxy.py",
        ]
    elif mode == "visual-identity":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = True
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeRemoteValidation"] = True
        spec["requireGroundingTools"] = True
        spec["requiredGroundingReads"] = [
            "theme/tokens.css",
            "theme/visual-identity-index.css",
            "src/index.css",
        ]
        spec["allowedPaths"] = [
            "src/index.css",
            "theme/tokens.css",
            "src/Layout.tsx",
        ]
    elif mode == "gemini-space":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeRemoteValidation"] = True
        spec["requireGroundingTools"] = True
        spec["requiredGroundingReads"] = [
            "theme/tokens.css",
            "theme/gemini-space-index.css",
            "theme/gemini-space-chat-reference.tsx",
            "src/index.css",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/index.css",
            "theme/tokens.css",
            "src/Layout.tsx",
            "src/components/Chat.tsx",
        ]
    elif mode == "web-gemini":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["requireGroundingTools"] = True
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "backend/main.py",
            "frontend/src/components/Chat.tsx",
            "frontend/src/api.ts",
        ]
        spec["allowedPaths"] = [
            "backend/main.py",
            "backend/tests",
            "frontend/src/components/Chat.tsx",
            "frontend/src/api.ts",
        ]
    elif mode == "chat-history-gemini":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeRemoteValidation"] = True
        spec["requireGroundingTools"] = True
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
        ]
    elif mode == "chat-history-autonomy":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeRemoteValidation"] = True
        spec["ravennaHomeDisableDeterministicRepair"] = True
        spec["ravennaHomeRequireAutonomyPass"] = True
        spec["requireGroundingTools"] = False
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
        ]
        spec["toolAllowlist"] = []
        spec["toolMaxTurns"] = 0
    elif mode in ("chat-patch-d1-strict-gemini", "chat-patch-d2-strict-gemini"):
        spec["ravennaHomeUiMode"] = mode
        spec["ravennaHomeStrictAutonomy"] = True
        spec["ravennaHomePatchOnly"] = True
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeDisableDeterministicRepair"] = True
        spec["ravennaHomeRequireAutonomyPass"] = True
        spec["requireGroundingTools"] = False
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
        ]
        spec["toolAllowlist"] = []
        spec["toolMaxTurns"] = 0
    elif mode == "chat-patch-d-strict-gemini":
        spec["ravennaHomeUiMode"] = "chat-patch-d-gemini"
        spec["ravennaHomeStrictAutonomy"] = True
        spec["ravennaHomePatchOnly"] = True
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeDisableDeterministicRepair"] = True
        spec["ravennaHomeRequireAutonomyPass"] = True
        spec["requireGroundingTools"] = False
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "theme/gemini-space-chat-reference.tsx",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
        ]
        spec["toolAllowlist"] = []
        spec["toolMaxTurns"] = 0
    elif mode in ("chat-patch-gemini", "chat-patch-a-gemini", "chat-patch-b-gemini", "chat-patch-c-gemini", "chat-patch-d-gemini", "chat-patch-d1-gemini", "chat-patch-d2-gemini"):
        spec["ravennaHomePatchOnly"] = True
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockChat"] = False
        spec["ravennaHomeSkipCssSeed"] = True
        spec["ravennaHomeDisableDeterministicRepair"] = True
        spec["ravennaHomeRequireAutonomyPass"] = True
        spec["requireGroundingTools"] = False
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "theme/gemini-space-chat-reference.tsx",
            "theme/chat-patch-scaffold.tsx",
            "src/components/Chat.tsx",
        ]
        spec["allowedPaths"] = [
            "src/components/Chat.tsx",
        ]
        spec["toolAllowlist"] = []
        spec["toolMaxTurns"] = 0
    elif mode == "backend-tests-only":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockFrontend"] = True
        spec["ravennaHomeLockMain"] = True
        spec["requireGroundingTools"] = True
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "main.py",
            "tests/test_health.py",
            "tests/test_chat_reference.py",
        ]
        spec["allowedPaths"] = [
            "tests",
        ]
    elif mode == "web-gemini-backend":
        spec["ravennaHomeLockApp"] = True
        spec["ravennaHomeLockChat"] = True
        spec["ravennaHomeLockCss"] = True
        spec["ravennaHomeLockLayout"] = True
        spec["ravennaHomeLockFrontend"] = True
        spec["requireGroundingTools"] = True
        spec["enforceAllowedPaths"] = True
        spec["requiredGroundingReads"] = [
            "main.py",
            "tests/test_health.py",
        ]
        spec["allowedPaths"] = [
            "main.py",
            "tests",
        ]
    return spec


def build_visual_identity_css_bundle() -> tuple[str, str]:
    """Referência Concierge Orbital — Ravenna escreve os mesmos paths."""
    root = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend"
    tokens_path = root / "theme" / "tokens.css"
    index_ref = root / "theme" / "visual-identity-index.css"
    tokens = tokens_path.read_text(encoding="utf-8") if tokens_path.is_file() else ""
    index = index_ref.read_text(encoding="utf-8") if index_ref.is_file() else ""
    return tokens, index


def build_gemini_space_bundle() -> tuple[str, str, str]:
    """Referência rh-11 — tokens + CSS sideral + Chat estilo Gemini."""
    root = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend"
    tokens_path = root / "theme" / "tokens.css"
    index_ref = root / "theme" / "gemini-space-index.css"
    chat_ref = root / "theme" / "gemini-space-chat-reference.tsx"
    tokens = tokens_path.read_text(encoding="utf-8") if tokens_path.is_file() else ""
    index = index_ref.read_text(encoding="utf-8") if index_ref.is_file() else ""
    chat = chat_ref.read_text(encoding="utf-8") if chat_ref.is_file() else ""
    return tokens, index, chat


def build_chat_patch_scaffold() -> str:
    """Scaffold rh-12e — api/historico prontos; falta UX Gemini."""
    root = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend"
    ref = root / "theme" / "chat-patch-scaffold.tsx"
    if ref.is_file():
        return ref.read_text(encoding="utf-8")
    return build_chat_history_bundle()


_PICK_COLLAPSED_FN = """function pickCollapsedMessages(messages: Msg[]): Msg[] {
  if (messages.length <= 2) return messages;
  let lastUser = -1;
  let lastAssistant = -1;
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (lastAssistant < 0 && messages[i].role === 'assistant') lastAssistant = i;
    if (lastUser < 0 && messages[i].role === 'user') lastUser = i;
    if (lastUser >= 0 && lastAssistant >= 0) break;
  }
  if (lastUser < 0 && lastAssistant < 0) return messages;
  const start = Math.min(
    lastUser >= 0 ? lastUser : messages.length,
    lastAssistant >= 0 ? lastAssistant : messages.length,
  );
  return messages.slice(Math.max(0, start));
}
"""


def build_chat_patch_a_golden_diff() -> str:
    """Unified diff válido contra scaffold real — rh-12f treino patch aplicável."""
    scaffold = build_chat_patch_scaffold()
    marker = "export function Chat()"
    if not scaffold.strip() or marker not in scaffold:
        return ""
    idx = scaffold.index(marker)
    target = scaffold[:idx] + _PICK_COLLAPSED_FN + "\n" + scaffold[idx:]
    diff = list(
        difflib.unified_diff(
            scaffold.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_a_baseline() -> str:
    """Estado pós rh-12f — scaffold + pickCollapsedMessages."""
    from learning_agent.core import autonomy_patch

    scaffold = build_chat_patch_scaffold()
    diff = build_chat_patch_a_golden_diff()
    if not diff.strip():
        return scaffold
    merged, _ = autonomy_patch.apply_unified_patch(scaffold, diff)
    return merged


_SCROLL_EFFECT_OLD = """  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);"""

_SCROLL_EFFECT_NEW = """  useEffect(() => {
    const el = logRef.current;
    if (!el) return undefined;
    const onScroll = () => {
      const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 56;
      setHistoryExpanded(!atBottom);
    };
    el.addEventListener('scroll', onScroll, { passive: true });
    return () => el.removeEventListener('scroll', onScroll);
  }, []);

  useEffect(() => {
    if (!historyExpanded) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, loading, historyExpanded]);"""


def build_chat_patch_b_golden_diff() -> str:
    """Unified diff válido contra baseline patch-A — rh-12g historyExpanded + logRef."""
    baseline = build_chat_patch_a_baseline()
    state_old = (
        "  const [booting, setBooting] = useState(true);\n"
        "  const bottomRef = useRef<HTMLDivElement>(null);"
    )
    state_new = (
        "  const [booting, setBooting] = useState(true);\n"
        "  const [historyExpanded, setHistoryExpanded] = useState(false);\n"
        "  const logRef = useRef<HTMLDivElement>(null);\n"
        "  const bottomRef = useRef<HTMLDivElement>(null);"
    )
    if state_old not in baseline or _SCROLL_EFFECT_OLD not in baseline:
        return ""
    target = baseline.replace(state_old, state_new, 1).replace(_SCROLL_EFFECT_OLD, _SCROLL_EFFECT_NEW, 1)
    diff = list(
        difflib.unified_diff(
            baseline.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_b_baseline() -> str:
    """Estado pós rh-12g — patch-A + historyExpanded + logRef."""
    from learning_agent.core import autonomy_patch

    baseline = build_chat_patch_a_baseline()
    diff = build_chat_patch_b_golden_diff()
    if not diff.strip():
        return baseline
    merged, _ = autonomy_patch.apply_unified_patch(baseline, diff)
    return merged


_CLEAR_HISTORY_OLD = """  function clearHistory() {
    localStorage.removeItem(STORAGE_KEY);
    setConversationId('');
    setMessages([]);
  }"""

_CLEAR_HISTORY_NEW = """  function clearHistory() {
    localStorage.removeItem(STORAGE_KEY);
    setConversationId('');
    setMessages([]);
    setHistoryExpanded(false);
  }"""

_SEND_COLLAPSE_OLD = """    setMessage('');
    setMessages((prev) => [...prev, { role: 'user', content: text }]);"""

_SEND_COLLAPSE_NEW = """    setMessage('');
    setHistoryExpanded(false);
    setMessages((prev) => [...prev, { role: 'user', content: text }]);"""

_RETURN_CARD = """  return (
    <section className="card chat-card">
      <div className="card-header">
        <h2>Chat Ravenna</h2>
        {messages.length > 0 ? (
          <button type="button" className="btn-ghost" onClick={clearHistory}>
            Nova conversa
          </button>
        ) : null}
      </div>
      <div className="chat-log" aria-live="polite">
        {booting ? <p className="muted">Carregando historico…</p> : null}
        {!booting && messages.length === 0 ? (
          <p className="muted">Por onde comecamos?</p>
        ) : null}
        {messages.map((m, i) => (
          <div key={`${i}-${m.role}`} className={`bubble bubble-${m.role}`}>
            {m.content}
          </div>
        ))}
        {loading ? <div className="bubble bubble-assistant muted">Ravenna pensando…</div> : null}
        <div ref={bottomRef} />
      </div>
      <textarea
        rows={2}
        value={message}
        onChange={(e) => setMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
          }
        }}
        placeholder="Fale com a Ravenna…"
      />
      <div className="chat-actions">
        <button type="button" onClick={send} disabled={loading}>
          {loading ? 'Enviando…' : 'Enviar'}
        </button>
      </div>
    </section>
  );"""

_RETURN_GEMINI = """  const visible = historyExpanded ? messages : pickCollapsedMessages(messages);
  const hiddenCount = messages.length - visible.length;

  return (
    <section className="chat-fullscreen gemini-chat" aria-label="Chat Ravenna">
      {booting ? (
        <p className="gemini-empty muted">Carregando historico…</p>
      ) : messages.length === 0 ? (
        <p className="gemini-empty">Por onde comecamos?</p>
      ) : (
        <div ref={logRef} className="gemini-chat-log" aria-live="polite">
          <div className="gemini-chat-log-inner">
            {!historyExpanded && hiddenCount > 0 ? (
              <p className="gemini-history-hint">
                {hiddenCount} mensagens anteriores — role para ver
              </p>
            ) : null}
            {visible.map((m, i) => (
              <div
                key={`${i}-${m.role}-${m.content.slice(0, 20)}`}
                className={`bubble bubble-${m.role}`}
              >
                {m.content}
              </div>
            ))}
            {loading ? (
              <div className="bubble bubble-assistant muted">Ravenna pensando…</div>
            ) : null}
            <div ref={bottomRef} />
          </div>
        </div>
      )}
      <div className="chat-input-dock">
        <div className="chat-input-pill neon-glow">
          <textarea
            rows={1}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="Fale com a Ravenna…"
            aria-label="Mensagem"
          />
          <button type="button" onClick={send} disabled={loading}>
            {loading ? '…' : 'Enviar'}
          </button>
        </div>
        {messages.length > 0 ? (
          <div style={{ textAlign: 'center', marginTop: '0.35rem' }}>
            <button type="button" className="btn-ghost" onClick={clearHistory}>
              Nova conversa
            </button>
          </div>
        ) : null}
      </div>
    </section>
  );"""


def build_chat_patch_c_golden_diff() -> str:
    """Unified diff válido contra baseline patch-B — rh-12h layout Gemini (só JSX)."""
    baseline = build_chat_patch_b_baseline()
    if _RETURN_CARD not in baseline:
        return ""
    target = baseline.replace(_RETURN_CARD, _RETURN_GEMINI, 1)
    diff = list(
        difflib.unified_diff(
            baseline.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_c_baseline() -> str:
    """Estado pós rh-12h — Chat Gemini completo (patch A+B+C)."""
    from learning_agent.core import autonomy_patch

    baseline = build_chat_patch_b_baseline()
    diff = build_chat_patch_c_golden_diff()
    if not diff.strip():
        return baseline
    merged, _ = autonomy_patch.apply_unified_patch(baseline, diff)
    return merged


def build_chat_patch_d1_baseline() -> str:
    """Estado pós rh-12l — patch-C + setHistoryExpanded em clearHistory."""
    baseline = build_chat_patch_c_baseline()
    if _CLEAR_HISTORY_OLD not in baseline:
        return baseline
    return baseline.replace(_CLEAR_HISTORY_OLD, _CLEAR_HISTORY_NEW, 1)


def build_chat_patch_d1_golden_diff() -> str:
    """Patch D1 — somente clearHistory (rh-12l micro)."""
    baseline = build_chat_patch_c_baseline()
    target = build_chat_patch_d1_baseline()
    if baseline == target:
        return ""
    diff = list(
        difflib.unified_diff(
            baseline.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_d2_golden_diff() -> str:
    """Patch D2 — somente send (rh-12m micro, sobre baseline d1)."""
    baseline = build_chat_patch_d1_baseline()
    if _SEND_COLLAPSE_OLD not in baseline:
        return ""
    target = baseline.replace(_SEND_COLLAPSE_OLD, _SEND_COLLAPSE_NEW, 1)
    diff = list(
        difflib.unified_diff(
            baseline.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_d_baseline() -> str:
    """Estado pós patch D completo (D1 clearHistory + D2 send)."""
    target = build_chat_patch_c_baseline()
    for old, new in (
        (_CLEAR_HISTORY_OLD, _CLEAR_HISTORY_NEW),
        (_SEND_COLLAPSE_OLD, _SEND_COLLAPSE_NEW),
    ):
        if old in target:
            target = target.replace(old, new, 1)
    return target


def build_chat_patch_d_golden_diff() -> str:
    """Patch D — setHistoryExpanded(false) em clearHistory + send (rh-12j)."""
    baseline = build_chat_patch_c_baseline()
    target = baseline
    for old, new in (
        (_CLEAR_HISTORY_OLD, _CLEAR_HISTORY_NEW),
        (_SEND_COLLAPSE_OLD, _SEND_COLLAPSE_NEW),
    ):
        if old not in target:
            return ""
        target = target.replace(old, new, 1)
    diff = list(
        difflib.unified_diff(
            baseline.splitlines(),
            target.splitlines(),
            fromfile="a/src/components/Chat.tsx",
            tofile="b/src/components/Chat.tsx",
            lineterm="",
        )
    )
    return "\n".join(diff) + ("\n" if diff else "")


def build_chat_patch_d1_context_hint() -> str:
    return (
        "MICRO-PATCH D1 — UMA unica alteracao em clearHistory:\n"
        f"```tsx\n{_CLEAR_HISTORY_OLD}\n```\n"
        "→ adicione +    setHistoryExpanded(false); apos setMessages([]).\n"
        "`export function Chat` — NAO arrow component."
    )


def build_chat_patch_d2_context_hint() -> str:
    return (
        "MICRO-PATCH D2 — UMA unica alteracao em send (apos setMessage):\n"
        f"```tsx\n{_SEND_COLLAPSE_OLD}\n```\n"
        "→ adicione +    setHistoryExpanded(false); apos setMessage('').\n"
        "clearHistory ja tem setHistoryExpanded — nao altere."
    )


def build_chat_patch_d_context_hint() -> str:
    """Trecho exato do baseline patch-C para o LLM montar o diff (rh-12j, sem golden completo)."""
    return (
        "CONTEXTO EXATO — copie estas linhas no unified diff (nao invente arrow/const Chat):\n\n"
        "1) clearHistory — adicione setHistoryExpanded(false) apos setMessages([]):\n"
        f"```tsx\n{_CLEAR_HISTORY_OLD}\n```\n"
        "→ deve ficar com +    setHistoryExpanded(false);\n\n"
        "2) send — adicione setHistoryExpanded(false) apos setMessage(''):\n"
        f"```tsx\n{_SEND_COLLAPSE_OLD}\n```\n"
        "→ deve ficar com +    setHistoryExpanded(false);\n"
        "Arquivo usa `export function Chat` — NAO `const Chat = () =>`."
    )


def build_chat_history_bundle() -> str:
    """Referência rh-12c — Chat.tsx Gemini + histórico API/localStorage."""
    root = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend"
    chat_ref = root / "theme" / "gemini-space-chat-reference.tsx"
    if not chat_ref.is_file():
        return ""
    return chat_ref.read_text(encoding="utf-8")


def seed_gemini_shell(root: Path, *, force: bool = False) -> list[str]:
    """CSS + Layout + tokens — sem Chat.tsx (kickoff rh-12c)."""
    written: list[str] = []
    tokens, index, _ = build_gemini_space_bundle()
    layout = seed_layout_baseline(root, force=force)
    if layout:
        written.append(layout)
    theme = root / "theme"
    theme.mkdir(parents=True, exist_ok=True)
    tokens_path = theme / "tokens.css"
    if force or not tokens_path.is_file():
        tokens_path.write_text(tokens, encoding="utf-8")
        written.append(str(tokens_path))
    index_path = root / "src" / "index.css"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    needs_index = force or not index_path.is_file()
    if index_path.is_file() and not force:
        needs_index = index_path.stat().st_size < MIN_SOURCE_CSS_BYTES
    if needs_index:
        index_path.write_text(index, encoding="utf-8")
        written.append(str(index_path))
    return written


def build_backend_tests_bundle() -> str:
    """Referência rh-12b-v2 — test_chat.py a partir de test_chat_reference.py."""
    root = Path(__file__).resolve().parents[2] / "ravenna-home" / "backend"
    ref = root / "tests" / "test_chat_reference.py"
    if not ref.is_file():
        return ""
    text = ref.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and "referência" in lines[0].lower():
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines).strip() + "\n"


def seed_tokens_scaffold(root: Path) -> str | None:
    """Garante theme/tokens.css sem tocar index.css — Ravenna aplica identidade."""
    theme = root / "theme"
    theme.mkdir(parents=True, exist_ok=True)
    tokens_path = theme / "tokens.css"
    if tokens_path.is_file() and tokens_path.stat().st_size > 100:
        return None
    bundled = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend" / "theme" / "tokens.css"
    if bundled.is_file():
        tokens_path.write_text(bundled.read_text(encoding="utf-8"), encoding="utf-8")
    else:
        tokens_path.write_text("/* Ravenna: defina tokens Concierge Orbital */\n", encoding="utf-8")
    return str(tokens_path)


def _default_index_css() -> str:
    """CSS baseline — usa arte local se disponível, senão template mínimo."""
    bundled = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend" / "src" / "index.css"
    if bundled.is_file():
        text = bundled.read_text(encoding="utf-8", errors="replace")
        if len(text.encode("utf-8")) >= MIN_SOURCE_CSS_BYTES:
            return text
    return """\
:root {
  font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
  color: #f0ecff;
  line-height: 1.5;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: radial-gradient(ellipse at 50% 0%, #3b1d6e 0%, #1a0f2e 45%, #0a0614 100%);
}
.space-bg, .stars {
  position: fixed;
  inset: 0;
  pointer-events: none;
  z-index: 0;
  opacity: 0.85;
}
.tab-bar { display: flex; gap: 0.5rem; margin: 1rem 0; }
.tab { flex: 1; background: rgba(255,255,255,0.08); color: #e9d5ff; border-radius: 10px; padding: 0.65rem; }
.tab.active { background: linear-gradient(135deg, #7c3aed, #a78bfa); color: #fff; }
.chat-fullscreen { display: flex; flex-direction: column; min-height: 100dvh; max-height: 100dvh; }
.neon-glow { box-shadow: 0 0 12px rgba(167, 139, 250, 0.45); }
.mic-button.pulse { animation: pulse 1.2s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.55} }
.install-pwa-banner {
  position: fixed; bottom: 1rem; left: 1rem; right: 1rem;
  background: rgba(26,16,48,0.92); border: 1px solid rgba(167,139,250,0.35);
  border-radius: 12px; padding: 0.75rem 1rem; z-index: 20;
}
button { cursor: pointer; border: none; border-radius: 10px; padding: 0.65rem 1.1rem;
  background: linear-gradient(135deg, #7c3aed, #5b21b6); color: white; font-weight: 600; }
textarea { width: 100%; border-radius: 10px; border: 1px solid rgba(167,139,250,0.25);
  background: rgba(15,10,30,0.65); color: inherit; padding: 0.65rem; }
.card { background: rgba(26,16,48,0.55); border-radius: 16px; padding: 1rem; }
"""


def _voice_pwa_css_extras() -> str:
    return """
.mic-button.pulse { animation: pulse 1.2s ease-in-out infinite; }
.install-pwa-banner { position: fixed; bottom: 1rem; left: 1rem; right: 1rem; z-index: 20; }
.chat-fullscreen { min-height: 100dvh; max-height: 100dvh; display: flex; flex-direction: column; }
.neon-glow { box-shadow: 0 0 12px rgba(167, 139, 250, 0.45); }
.space-bg { position: fixed; inset: 0; pointer-events: none; z-index: 0; }
"""


def seed_index_css_baseline(root: Path, *, force: bool = False, voice_pwa: bool = False) -> str | None:
    """Garante index.css válido — evita gap seed-pass sem tema."""
    css_path = root / "src" / "index.css"
    css_path.parent.mkdir(parents=True, exist_ok=True)
    needs = force or not css_path.is_file()
    if css_path.is_file() and not force:
        text = css_path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        needs = (
            len(text.encode("utf-8")) < MIN_SOURCE_CSS_BYTES
            or any(h in lower for h in _CSS_PLACEHOLDER_HINTS)
        )
    if not needs:
        return None
    content = _default_index_css()
    if voice_pwa and ".mic-button" not in content:
        content += _voice_pwa_css_extras()
    css_path.write_text(content, encoding="utf-8")
    return str(css_path)


def seed_space_chat_baseline(root: Path, *, force: bool = False, skip_css: bool = False) -> list[str]:
    """Infra garante App.tsx + Chat.tsx (API intacta) — Ravenna edita CSS/layout visual."""
    written: list[str] = []
    src = root / "src"
    src.mkdir(parents=True, exist_ok=True)
    app_path = src / "App.tsx"
    needs_app = force or not app_path.is_file()
    if app_path.is_file() and not force:
        failures = validate_filesystem(root, spec={"ravennaHomeUiMode": "space-chat", "ravennaHomeLockApp": True})
        app_failures = [f for f in failures if "App.tsx" in f or "router" in f.lower() or "GPU" in f]
        needs_app = bool(app_failures)
        if not needs_app:
            text = app_path.read_text(encoding="utf-8", errors="replace")
            if "GPU" in text or "GpuStatus" in text:
                needs_app = True
    if needs_app:
        app_path.write_text(SPACE_CHAT_APP_TSX, encoding="utf-8")
        written.append(str(app_path))

    chat_path = src / "components" / "Chat.tsx"
    chat_path.parent.mkdir(parents=True, exist_ok=True)
    needs_chat = force or not chat_path.is_file()
    if chat_path.is_file() and not force:
        chat_text = chat_path.read_text(encoding="utf-8", errors="replace")
        needs_chat = bool(_chat_api_integrity(chat_text))
    if needs_chat:
        chat_path.write_text(SPACE_CHAT_CHAT_TSX, encoding="utf-8")
        written.append(str(chat_path))

    css_written = None if skip_css else seed_index_css_baseline(root, force=force, voice_pwa=False)
    if css_written:
        written.append(css_written)
    return written


def seed_pwa_icons(root: Path, *, force: bool = False) -> list[str]:
    """Ícones mínimos para PWA passar validação — Ravenna pode substituir por arte final."""
    import base64

    written: list[str] = []
    public = root / "public"
    if not public.is_dir():
        public = root.parent / "public"
    public.mkdir(parents=True, exist_ok=True)
    png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    )
    data = base64.b64decode(png_b64)
    for name in ("icon-192.png", "icon-512.png"):
        path = public / name
        if force or not path.is_file():
            path.write_bytes(data)
            written.append(str(path))
    manifest_path = public / "manifest.webmanifest"
    if force or not manifest_path.is_file():
        manifest_path.write_text(json.dumps(_PWA_MANIFEST, indent=2), encoding="utf-8")
        written.append(str(manifest_path))
    else:
        try:
            current = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current = {}
        merged = {**_PWA_MANIFEST, **current, "display": "standalone", "icons": list(_PWA_MANIFEST["icons"])}
        manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        written.append(str(manifest_path))
    return written


def _patch_index_html_pwa(root: Path, *, force: bool = False) -> str | None:
    html_path = root / "index.html"
    if not html_path.is_file():
        html_path = root.parent / "index.html"
    if not html_path.is_file():
        return None
    text = html_path.read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    changed = False
    if 'rel="manifest"' not in lower and "manifest.webmanifest" not in lower:
        text = text.replace("</head>", '  <link rel="manifest" href="/manifest.webmanifest" />\n</head>')
        changed = True
    if "apple-mobile-web-app-capable" not in lower:
        text = text.replace(
            "</head>",
            '  <meta name="apple-mobile-web-app-capable" content="yes" />\n'
            '  <meta name="apple-mobile-web-app-title" content="Ravenna" />\n</head>',
        )
        changed = True
    if force or changed:
        html_path.write_text(text, encoding="utf-8")
        return str(html_path)
    return None


def blueprint_for_prompt(spec: dict[str, Any] | None) -> str:
    mode = (spec or {}).get("ravennaHomeUiMode")
    if mode == "space-chat":
        return (
            "BLUEPRINT OBRIGATÓRIO RAVENNA HOME (rh-08 — App.tsx JÁ ESTÁ CORRETO, NÃO REESCREVA):\n"
            "- **`App.tsx` e `Chat.tsx` bloqueados** — infra mantém abas + API/histórico + `chat-fullscreen`.\n"
            "- **Você edita SOMENTE:** `index.css` (espaço + neon + viewport), opcional `Layout.tsx` e `theme/`.\n"
            "- CSS: `.space-bg`, `.neon-glow`, `.tab-bar`, `.chat-fullscreen`, `100dvh`, estrelas/nebulosa.\n"
            "- PROIBIDO: react-router-dom, package.json, App.js, GPU, novas dependências.\n"
        )
    if mode == "voice-pwa":
        return (
            "BLUEPRINT OBRIGATÓRIO RAVENNA HOME (rh-09 v3 — gate pré-apply + baseline seedado):\n"
            "- **GROUNDING prevalece** — Diagnóstico contraditório = writes BLOQUEADOS.\n"
            "- **Baseline seedado** — REFINE CSS/UX; read_file obrigatório antes de Investigação.\n"
            "- **STT/TTS/InstallPrompt já existem** — melhore pulse, banner, toggle voz.\n"
            "- PROIBIDO: pytest, backend, package.json, App.js, react-router.\n"
        )
    if mode == "chat-history-gemini":
        return (
            "BLUEPRINT RH-12C — CHAT ONLY (CSS/Layout/backend LOCK):\n"
            "- **Somente** `src/components/Chat.tsx` — paths relativos ao projectRoot.\n"
            "- Leia `theme/gemini-space-chat-reference.tsx` e adapte preservando "
            "`api`, `localStorage`, `conversation_id`, `pickCollapsedMessages`, `historyExpanded`.\n"
            "- PROIBIDO: index.css, Layout.tsx, backend, npm install, paths `ravenna-home/frontend/...`.\n"
        )
    if mode == "chat-patch-gemini":
        return (
            "BLUEPRINT RH-12E — PATCH GEMINI (scaffold com api/historico):\n"
            "- **Chat.tsx ja tem api + historico** — NAO reescreva do zero.\n"
            "- Emita ```patch src/components/Chat.tsx``` (1-3 patches) OU 1 write completo.\n"
            "- Copie pickCollapsedMessages + layout de theme/gemini-space-chat-reference.tsx.\n"
            "- PROIBIDO: CSS, backend, fetch https externo.\n"
        )
    if mode == "chat-history-autonomy":
        return (
            "BLUEPRINT RH-12C-V2 — AUTONOMIA PURA (repair DESLIGADO):\n"
            "- **Somente** `src/components/Chat.tsx` — 1 bloco ```write``` no **1º turno de texto**.\n"
            "- Investigação **máx 3 linhas** — depois o write completo. Sem narrar deploy/npm.\n"
            "- Adaptar `theme/gemini-space-chat-reference.tsx` com api + histórico.\n"
            "- Repair determinístico **NÃO existe** neste épico — só conta se VOCÊ escrever.\n"
        )
    if mode == "backend-tests-only":
        return (
            "BLUEPRINT RH-12B-V2 — TESTES ONLY (main.py LOCK):\n"
            "- **main.py BLOQUEADO** — endpoints já existem; NÃO write/patch em main.py.\n"
            "- Crie **somente** `tests/test_chat.py` com TestClient + mock httpx.\n"
            "- Leia `main.py` e `tests/test_health.py` antes de escrever.\n"
            "- pytest mínimo 3 testes; sem npm/node/frontend.\n"
        )
    if mode == "web-gemini-backend":
        return (
            "BLUEPRINT RH-12B — BACKEND ONLY (frontend LOCK):\n"
            "- **projectRoot = backend/** — writes: `main.py`, `tests/test_*.py` apenas.\n"
            "- read_file `main.py` + `tests/test_health.py` ANTES de diagnosticar.\n"
            "- Patch FastAPI existente — endpoints history + chat + web context.\n"
            "- pytest com TestClient + mock httpx — NÃO use npm.\n"
            "- PROIBIDO: frontend, CSS, Chat.tsx, package.json.\n"
        )
    if mode == "web-gemini":
        return (
            "BLUEPRINT RH-12 — WEB + HISTÓRICO (preservar UX Gemini rh-11):\n"
            "- **LOCK:** `index.css`, `Layout.tsx`, `theme/*` — NÃO reescreva visual.\n"
            "- **Edite:** `backend/main.py` e `frontend/src/components/Chat.tsx`.\n"
            "- read_file nesses paths ANTES de Investigação/Diagnóstico.\n"
            "- Manter `pickCollapsedMessages`, `historyExpanded`, `api`, `localStorage`.\n"
            "- PROIBIDO: package.json, App.tsx, CSS, paths com prefixo duplicado.\n"
        )
    if mode == "visual-identity":
        return (
            "BLUEPRINT RH-10 — CONCIERGE ORBITAL (identidade visual futurista + assistente profissional):\n"
            "- **Você aplica** `theme/tokens.css` + `src/index.css` (2 blocos ```write``` no MESMO turno).\n"
            "- Leia `theme/visual-identity-index.css` como REFERÊNCIA — não escreva nesse arquivo.\n"
            "- `index.css` DEVE começar com `@import '../theme/tokens.css';` e usar var(--ravenna-*).\n"
            "- Visual: glass 16px, 100dvh, `.tab-bar` pill, `.chat-fullscreen`, `.status-bar`, estrelas sutis.\n"
            "- Voz: `.voice-toggle` custom, `.mic-button.pulse` ciano, `.install-pwa-banner` glass.\n"
            "- Tom profissional — sem neon exagerado, sem fonte sci-fi.\n"
            "- PROIBIDO: App.tsx, Chat.tsx, package.json, backend, react-router.\n"
        )
    if (spec or {}).get("ravennaHomeDeploy"):
        return (
            "BLUEPRINT RAVENNA HOME:\n"
            "- `App.tsx` com `useState` + abas + `import Layout from './Layout'`.\n"
            "- PROIBIDO react-router-dom, App.js, package.json.\n"
        )
    return ""


def should_block_write(relative_path: str, content: str, *, spec: dict[str, Any] | None) -> str | None:
    if not (spec or {}).get("ravennaHome"):
        return None
    rel = relative_path.replace("\\", "/").strip("/")
    if rel.endswith("package.json") or rel.endswith("frontend/package.json"):
        return "package.json bloqueado — JSON estrito; build Docker falha se reescrito."

    if rel.endswith("src/App.tsx") or rel.endswith("frontend/src/App.tsx"):
        if (spec or {}).get("ravennaHomeLockApp"):
            return (
                "App.tsx bloqueado neste épico — infra já definiu abas Chat|Casa. "
                "Edite `Chat.tsx` e `index.css` para visual full-screen + neon."
            )
        return _validate_app_source(content, spec, write_time=True)

    if rel.endswith("src/App.js") or rel.endswith("src/App.jsx"):
        return "App.js/App.jsx proibido — use App.tsx."

    if "components/Layout.tsx" in rel:
        return "Layout duplicado proibido — use src/Layout.tsx."

    if rel.endswith("main.py") or rel.endswith("backend/main.py"):
        if (spec or {}).get("ravennaHomeLockMain"):
            return "main.py bloqueado neste épico — leia o arquivo e escreva apenas tests/test_chat.py."
        if (spec or {}).get("ravennaHomeUiMode") == "web-gemini-backend":
            if len((content or "").encode("utf-8")) < 400:
                return "main.py truncado/stub — use patch no FastAPI existente; não reescrever do zero."

    if rel.endswith("src/index.css") or rel.endswith("frontend/src/index.css"):
        if (spec or {}).get("ravennaHomeLockCss"):
            return "index.css bloqueado neste épico — visual rh-11 preservado; edite Chat/backend apenas."
    if rel.endswith("theme/tokens.css") or rel.endswith("frontend/theme/tokens.css"):
        if (spec or {}).get("ravennaHomeLockCss"):
            return "theme/tokens.css bloqueado neste épico."
    if rel.endswith("src/Layout.tsx") or rel.endswith("frontend/src/Layout.tsx"):
        if (spec or {}).get("ravennaHomeLockLayout") or (spec or {}).get("ravennaHomeLockFrontend"):
            return "Layout.tsx bloqueado neste épico."

    if (spec or {}).get("ravennaHomeLockFrontend"):
        blocked_frontend = (
            "frontend/",
            "src/index.css",
            "src/components/",
            "theme/",
            "index.html",
        )
        if any(marker in rel for marker in blocked_frontend):
            return "Frontend bloqueado neste épico — edite apenas backend (main.py, tests/)."

    if rel.endswith("src/components/Chat.tsx") or rel.endswith("frontend/src/components/Chat.tsx"):
        if (spec or {}).get("ravennaHomeLockChat") or (spec or {}).get("ravennaHomeLockFrontend"):
            return (
                "Chat.tsx bloqueado neste épico — infra preserva API/histórico. "
                "Estilize via `index.css` (`.chat-fullscreen`, neon, viewport)."
            )
        blocked = _chat_api_integrity(content)
        if blocked:
            return blocked

    return None


def _validate_app_source(text: str, spec: dict[str, Any] | None, *, write_time: bool) -> str | None:
    for forbidden in _FORBIDDEN_IMPORTS:
        if forbidden in text:
            return f"PROIBIDO `{forbidden}` — abas com useState, sem router, sem deps novas."
    for pattern, message in _FORBIDDEN_APP_PATTERNS:
        if re.search(pattern, text):
            return message
    mode = (spec or {}).get("ravennaHomeUiMode")
    if (spec or {}).get("ravennaHomeDeploy") or mode:
        if "useState" not in text:
            return "App.tsx deve usar `useState` para abas Chat | Casa."
        if "./Layout" not in text and "from './Layout'" not in text:
            return "App.tsx deve importar `Layout` de `./Layout`."
    if mode == "space-chat":
        if "Chat" not in text or "Casa" not in text:
            return "Modo space-chat: App.tsx deve ter abas Chat e Casa."
    return None


_BACKEND_MAIN_MARKERS = (
    "/api/chat/history",
    "conversation_id",
    "_web_context",
    "search-web",
)


def validate_backend_filesystem(root: Path) -> list[str]:
    """Validação pós-apply — backend rh-12b."""
    failures: list[str] = []
    main = root / "main.py"
    if not main.is_file():
        return ["backend: main.py ausente."]
    text = main.read_text(encoding="utf-8", errors="replace").lower()
    for marker in _BACKEND_MAIN_MARKERS:
        if marker.lower() not in text:
            failures.append(f"backend: marcador `{marker}` ausente em main.py.")
    tests = root / "tests"
    if not tests.is_dir():
        failures.append("backend: pasta tests/ ausente.")
    elif not list(tests.glob("test_chat*.py")):
        failures.append("backend: tests/test_chat.py (ou similar) ausente.")
    return failures


def validate_backend_tests_only(root: Path) -> list[str]:
    """rh-12b-v2 — só exige test_chat.py com conteúdo mínimo."""
    failures: list[str] = []
    chat_tests = list((root / "tests").glob("test_chat*.py")) if (root / "tests").is_dir() else []
    if not chat_tests:
        return ["backend: tests/test_chat.py ausente."]
    text = chat_tests[0].read_text(encoding="utf-8", errors="replace")
    lower = text.lower()
    for marker in ("testclient", "def test_", "mock", "patch"):
        if marker not in lower:
            failures.append(f"backend: test_chat.py sem `{marker}`.")
    if lower.count("def test_") < 3:
        failures.append(f"backend: test_chat.py precisa ≥3 funções test_ (tem {lower.count('def test_')}).")
    return failures


def validate_filesystem(root: Path, *, spec: dict[str, Any] | None = None) -> list[str]:
    """Validação pós-apply — estado real no disco."""
    failures: list[str] = []
    if not root.is_dir():
        return ["projectRoot do frontend não encontrado."]

    app_tsx = root / "src" / "App.tsx"
    if not app_tsx.is_file():
        failures.append("Entrypoint `src/App.tsx` ausente.")
        return failures

    app_text = app_tsx.read_text(encoding="utf-8", errors="replace")
    blocked = _validate_app_source(app_text, spec, write_time=False)
    if blocked:
        failures.append(blocked)

    if (root / "src" / "App.js").is_file():
        failures.append("Órfão `src/App.js` presente.")

    if (root / "src" / "components" / "Layout.tsx").is_file():
        failures.append("Layout duplicado em `src/components/Layout.tsx`.")

    if not (root / "src" / "Layout.tsx").is_file():
        failures.append("`src/Layout.tsx` ausente.")

    pkg_failures = _validate_package_json(root / "package.json")
    failures.extend(pkg_failures)

    mode = (spec or {}).get("ravennaHomeUiMode")
    if mode == "space-chat":
        failures.extend(_validate_space_chat_visual(root))
    if mode == "voice-pwa":
        failures.extend(_validate_voice_pwa(root))
    if mode == "visual-identity":
        failures.extend(_validate_visual_identity(root, spec=spec))
    if mode == "gemini-space":
        failures.extend(_validate_gemini_space(root, spec=spec))
    if mode == "chat-history-gemini":
        failures.extend(_validate_chat_history_gemini(root))
    if mode == "chat-history-autonomy":
        failures.extend(_validate_chat_history_gemini(root))
    if mode == "chat-patch-d1-gemini":
        failures.extend(_validate_chat_patch_d1(root))
    if mode == "chat-patch-d2-gemini":
        failures.extend(_validate_chat_patch_d(root))
    if mode == "chat-patch-d1-strict-gemini":
        failures.extend(_validate_chat_patch_d1(root))
    if mode == "chat-patch-d2-strict-gemini":
        failures.extend(_validate_chat_patch_d(root))
    if mode == "chat-patch-d-gemini":
        failures.extend(_validate_chat_patch_d(root))
    elif mode == "chat-patch-c-gemini":
        failures.extend(_validate_chat_patch_c(root))
    elif mode == "chat-patch-b-gemini":
        failures.extend(_validate_chat_patch_b(root))
    elif mode == "chat-patch-a-gemini":
        failures.extend(_validate_chat_patch_a(root))
    elif mode == "chat-patch-gemini":
        failures.extend(_validate_chat_history_gemini(root))

    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        failures.append("Entrypoint `src/components/Chat.tsx` ausente.")
    elif chat.is_file():
        chat_text = chat.read_text(encoding="utf-8", errors="replace")
        chat_block = _chat_api_integrity(chat_text)
        if chat_block:
            failures.append(chat_block)
        elif "fetch" not in chat_text and "api" not in chat_text.lower():
            failures.append("Chat.tsx deve preservar integração API/histórico.")

    return failures


def _validate_package_json(path: Path) -> list[str]:
    if not path.is_file():
        return ["package.json ausente."]
    text = path.read_text(encoding="utf-8", errors="replace")
    if "//" in text or "/*" in text:
        return ["package.json contém comentários — JSON inválido."]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [f"package.json inválido: {exc}"]
    if data.get("name") != "ravenna-home-frontend":
        return [f"package.json corrompido (name={data.get('name')!r})."]
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    for forbidden in _FORBIDDEN_IMPORTS:
        if forbidden in deps:
            return [f"Dependência proibida em package.json: {forbidden}"]
    return []


def _validate_space_chat_visual(root: Path) -> list[str]:
    failures: list[str] = []
    css_chunks: list[str] = []
    for path in (root / "src" / "index.css", root / "theme" / "tokens.css"):
        if path.is_file():
            css_chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    css = "\n".join(css_chunks).lower()
    if not any(marker in css for marker in _SPACE_CHAT_CSS_MARKERS):
        failures.append(
            "Visual space-chat: CSS deve incluir classes espaço/neon (ex.: .space-bg, .neon-glow, .tab-bar)."
        )
    chat = root / "src" / "components" / "Chat.tsx"
    if chat.is_file():
        chat_text = chat.read_text(encoding="utf-8", errors="replace").lower()
        if "100vh" not in chat_text and "100dvh" not in chat_text and "fullscreen" not in chat_text:
            if not any(m in css for m in ("100vh", "100dvh", "chat-fullscreen", "chat-full")):
                failures.append(
                    "Chat full-screen: Chat.tsx ou index.css deve usar viewport cheia (100vh/chat-fullscreen)."
                )
    return failures


_VOICE_STT_MARKERS = (
    "speechrecognition",
    "webkitSpeechRecognition",
    "isListening",
    "toggleVoice",
    "microphone",
    "mic-button",
    "voice-input",
    "/api/speech/transcribe",
)
_VOICE_TTS_MARKERS = (
    "speechSynthesis",
    "SpeechSynthesisUtterance",
    "speakResponse",
    "voiceEnabled",
    "readAloud",
    "tts",
)
_PWA_INSTALL_MARKERS = (
    "beforeinstallprompt",
    "InstallPrompt",
    "installPwa",
    "deferredPrompt",
    "Adicionar à Tela",
    "Adicionar a Tela",
    "instalar no celular",
)


def seed_voice_pwa_baseline(root: Path, *, force: bool = False, skip_css: bool = False) -> list[str]:
    """Infra garante baseline voz+PWA — Ravenna refina UX sem recriar arquivos existentes."""
    written: list[str] = []
    written.extend(seed_space_chat_baseline(root, force=force, skip_css=skip_css))
    written.extend(seed_pwa_icons(root, force=force))

    src = root / "src"
    install_path = src / "components" / "InstallPrompt.tsx"
    install_path.parent.mkdir(parents=True, exist_ok=True)
    if force or not install_path.is_file():
        install_path.write_text(VOICE_PWA_INSTALL_PROMPT_TSX, encoding="utf-8")
        written.append(str(install_path))

    layout_path = src / "Layout.tsx"
    if force or not layout_path.is_file():
        layout_path.write_text(VOICE_PWA_LAYOUT_TSX, encoding="utf-8")
        written.append(str(layout_path))
    elif force:
        layout_text = layout_path.read_text(encoding="utf-8", errors="replace")
        if "InstallPrompt" not in layout_text:
            layout_path.write_text(VOICE_PWA_LAYOUT_TSX, encoding="utf-8")
            written.append(str(layout_path))

    chat_path = src / "components" / "Chat.tsx"
    needs_chat = force or not chat_path.is_file()
    if chat_path.is_file() and not force:
        chat_text = chat_path.read_text(encoding="utf-8", errors="replace")
        chat_lower = chat_text.lower()
        needs_voice = not any(m.lower() in chat_lower for m in _VOICE_STT_MARKERS)
        needs_tts = not any(m.lower() in chat_lower for m in _VOICE_TTS_MARKERS)
        needs_chat = bool(_chat_api_integrity(chat_text)) or needs_voice or needs_tts
    if needs_chat:
        chat_path.write_text(VOICE_PWA_CHAT_TSX, encoding="utf-8")
        written.append(str(chat_path))

    html_written = _patch_index_html_pwa(root, force=force)
    if html_written:
        written.append(html_written)
    if not skip_css:
        css_written = seed_index_css_baseline(root, force=force, voice_pwa=True)
        if css_written:
            written.append(css_written)
    scaffold = seed_tokens_scaffold(root)
    if scaffold:
        written.append(scaffold)
    return written


_GEMINI_SPACE_CHAT_MARKERS = (
    "pickCollapsedMessages",
    "historyExpanded",
    "gemini-chat",
    "gemini-chat-log",
    "chat-input-dock",
    "localStorage",
    "conversation_id",
)
_GEMINI_SPACE_CSS_MARKERS = (
    "starfield",
    "space-bg",
    "gemini-chat",
    "chat-input-dock",
    "chat-input-pill",
)


def seed_layout_baseline(root: Path, *, force: bool = False) -> str | None:
    """Restaura Layout canonico (AuthProvider + camadas siderais) — infra pre-rh-11."""
    layout_path = root / "src" / "Layout.tsx"
    bundled = Path(__file__).resolve().parents[2] / "ravenna-home" / "frontend" / "src" / "Layout.tsx"
    canonical = """\
import React from 'react';
import { AuthProvider } from './auth';

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <div className="space-bg" aria-hidden />
      <div className="starfield" aria-hidden />
      <div className="stars" aria-hidden />
      <div className="app-shell">
        <header className="app-header">
          <h1>Ravenna Home</h1>
          <p>Casa inteligente · chat + luzes + GPU</p>
        </header>
        <main>{children}</main>
      </div>
    </AuthProvider>
  );
}
"""
    text = layout_path.read_text(encoding="utf-8", errors="replace") if layout_path.is_file() else ""
    broken = (
        "Layout.css" in text
        or "AuthProvider" not in text
        or "export default function Layout" not in text
        or ("space-bg" not in text and "starfield" not in text)
    )
    if force or broken:
        layout_path.parent.mkdir(parents=True, exist_ok=True)
        if bundled.is_file() and not force:
            base = bundled.read_text(encoding="utf-8")
            if "space-bg" not in base:
                base = canonical
            layout_path.write_text(base, encoding="utf-8")
        else:
            layout_path.write_text(canonical, encoding="utf-8")
        return str(layout_path)
    return None


def _validate_gemini_space(root: Path, *, spec: dict[str, Any] | None = None) -> list[str]:
    failures: list[str] = []
    ref_css = root / "theme" / "gemini-space-index.css"
    ref_chat = root / "theme" / "gemini-space-chat-reference.tsx"
    if not ref_css.is_file():
        failures.append("gemini-space: referencia `theme/gemini-space-index.css` ausente.")
    if not ref_chat.is_file():
        failures.append("gemini-space: referencia `theme/gemini-space-chat-reference.tsx` ausente.")
    if (spec or {}).get("ravennaHomeSkipCssSeed"):
        return failures
    css, css_bytes = _read_css_chunks(root)
    css_lower = css.lower()
    if css_bytes < MIN_SOURCE_CSS_BYTES:
        failures.append(
            f"gemini-space: CSS curto ({css_bytes}B) — index.css com void sideral + layout Gemini."
        )
    for marker in _GEMINI_SPACE_CSS_MARKERS:
        if marker not in css_lower:
            failures.append(f"gemini-space: marcador CSS `{marker}` ausente.")
    layout = root / "src" / "Layout.tsx"
    if layout.is_file():
        lt = layout.read_text(encoding="utf-8", errors="replace").lower()
        if "authprovider" not in lt:
            failures.append("gemini-space: Layout.tsx deve manter AuthProvider.")
        if "layout.css" in lt:
            failures.append("gemini-space: Layout.tsx nao deve importar Layout.css inexistente.")
        if "space-bg" not in lt and "starfield" not in lt:
            failures.append("gemini-space: Layout.tsx deve ter `.space-bg` e `.starfield`.")
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        failures.append("gemini-space: `src/components/Chat.tsx` ausente.")
    else:
        ct = chat.read_text(encoding="utf-8", errors="replace")
        cl = ct.lower()
        missing = [m for m in _GEMINI_SPACE_CHAT_MARKERS if m.lower() not in cl]
        if missing:
            failures.append(f"gemini-space: Chat.tsx incompleto — faltam: {', '.join(missing[:5])}.")
        if "./Chat.css" in ct or "./chat.css" in ct:
            failures.append("gemini-space: Chat.tsx nao deve importar Chat.css.")
    return failures


def _validate_chat_history_gemini(root: Path) -> list[str]:
    """rh-12c — só Chat.tsx com UX Gemini + histórico."""
    failures: list[str] = []
    ref_chat = root / "theme" / "gemini-space-chat-reference.tsx"
    if not ref_chat.is_file():
        failures.append("chat-history: referencia `theme/gemini-space-chat-reference.tsx` ausente.")
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return failures + ["chat-history: `src/components/Chat.tsx` ausente."]
    ct = chat.read_text(encoding="utf-8", errors="replace")
    cl = ct.lower()
    missing = [m for m in _GEMINI_SPACE_CHAT_MARKERS if m.lower() not in cl]
    if missing:
        failures.append(f"chat-history: Chat.tsx incompleto — faltam: {', '.join(missing[:6])}.")
    if "./Chat.css" in ct or "./chat.css" in ct:
        failures.append("chat-history: Chat.tsx nao deve importar Chat.css.")
    if "/api/chat/history" not in ct and "api.chat" not in cl and "gethistory" not in cl:
        failures.append("chat-history: Chat.tsx deve carregar historico via API (`/api/chat/history` ou api).")
    return failures


def _validate_chat_patch_a(root: Path) -> list[str]:
    """rh-12f — só pickCollapsedMessages (degrau mínimo de autonomia patch)."""
    failures: list[str] = []
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return ["chat-patch-a: `src/components/Chat.tsx` ausente."]
    ct = chat.read_text(encoding="utf-8", errors="replace")
    if "pickCollapsedMessages" not in ct:
        failures.append("chat-patch-a: Chat.tsx deve conter `pickCollapsedMessages`.")
    if "/api/chat/history" not in ct and "api" not in ct.lower():
        failures.append("chat-patch-a: preservar api/historico do scaffold.")
    return failures


def _validate_chat_patch_b(root: Path) -> list[str]:
    """rh-12g — patch-A + historyExpanded + logRef scroll."""
    failures = _validate_chat_patch_a(root)
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return failures
    ct = chat.read_text(encoding="utf-8", errors="replace")
    for marker in ("historyExpanded", "logRef", "setHistoryExpanded"):
        if marker not in ct:
            failures.append(f"chat-patch-b: Chat.tsx deve conter `{marker}`.")
    return failures


def _validate_chat_patch_c(root: Path) -> list[str]:
    """rh-12h — patch-B + layout Gemini (gemini-chat, chat-input-dock)."""
    failures = _validate_chat_patch_b(root)
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return failures
    ct = chat.read_text(encoding="utf-8", errors="replace")
    for marker in ("gemini-chat", "gemini-chat-log", "chat-input-dock"):
        if marker not in ct:
            failures.append(f"chat-patch-c: Chat.tsx deve conter `{marker}`.")
    if "visible.map" not in ct and "visible.map((m" not in ct:
        failures.append("chat-patch-c: Chat.tsx deve usar `visible.map` para mensagens colapsadas.")
    return failures


def _validate_chat_patch_d1(root: Path) -> list[str]:
    """rh-12l — patch-C + setHistoryExpanded só em clearHistory."""
    failures = _validate_chat_patch_c(root)
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return failures
    ct = chat.read_text(encoding="utf-8", errors="replace")
    if _CLEAR_HISTORY_NEW.strip() not in ct:
        failures.append("chat-patch-d1: clearHistory deve chamar setHistoryExpanded(false).")
    return failures


def _validate_chat_patch_d(root: Path) -> list[str]:
    """rh-12j — patch-C + setHistoryExpanded em clearHistory/send."""
    failures = _validate_chat_patch_c(root)
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        return failures
    ct = chat.read_text(encoding="utf-8", errors="replace")
    if _CLEAR_HISTORY_NEW.strip() not in ct:
        failures.append("chat-patch-d: clearHistory deve chamar setHistoryExpanded(false).")
    if _SEND_COLLAPSE_NEW.strip() not in ct:
        failures.append("chat-patch-d: send deve resetar historyExpanded apos setMessage.")
    return failures


def _validate_visual_identity(root: Path, *, spec: dict[str, Any] | None = None) -> list[str]:
    failures: list[str] = []
    ref = root / "theme" / "visual-identity-index.css"
    if not ref.is_file():
        failures.append("visual-identity: referência `theme/visual-identity-index.css` ausente.")
    if (spec or {}).get("ravennaHomeSkipCssSeed"):
        return failures
    css, css_bytes = _read_css_chunks(root)
    css_lower = css.lower()
    if css_bytes < MIN_SOURCE_CSS_BYTES:
        failures.append(
            f"visual-identity: CSS combinado curto ({css_bytes}B) — tokens + index.css com Concierge Orbital."
        )
    for marker in ("--ravenna-accent", "tab-bar", "chat-fullscreen", "100dvh", "@import"):
        if marker not in css_lower:
            failures.append(f"visual-identity: marcador `{marker}` ausente em tokens/index.css.")
    return failures


def _validate_voice_pwa(root: Path) -> list[str]:
    failures: list[str] = []
    chat = root / "src" / "components" / "Chat.tsx"
    if not chat.is_file():
        failures.append("voice-pwa: `Chat.tsx` ausente.")
        return failures
    chat_text = chat.read_text(encoding="utf-8", errors="replace")
    chat_lower = chat_text.lower()
    if not any(m.lower() in chat_lower for m in _VOICE_STT_MARKERS):
        failures.append(
            "Voz STT: Chat.tsx deve ter botão microfone + Web Speech API ou `/api/speech/transcribe`."
        )
    if not any(m.lower() in chat_lower for m in _VOICE_TTS_MARKERS):
        failures.append(
            "Voz TTS: Chat.tsx deve usar `speechSynthesis` (ou hook) para ler respostas do assistente."
        )
    install = root / "src" / "components" / "InstallPrompt.tsx"
    install_text = ""
    if install.is_file():
        install_text = install.read_text(encoding="utf-8", errors="replace")
    combined = f"{chat_text}\n{install_text}".lower()
    if not any(m.lower() in combined for m in _PWA_INSTALL_MARKERS):
        failures.append(
            "PWA install: falta `InstallPrompt` com `beforeinstallprompt` ou instruções iOS para adicionar à tela."
        )
    manifest = root / "public" / "manifest.webmanifest"
    if not manifest.is_file():
        manifest = root.parent / "public" / "manifest.webmanifest"
    if manifest.is_file():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            failures.append("manifest.webmanifest inválido.")
            data = {}
        if data.get("display") != "standalone":
            failures.append("PWA: manifest deve ter `display: standalone`.")
        icons = data.get("icons") or []
        sizes = {str(i.get("sizes", "")) for i in icons if isinstance(i, dict)}
        if not any("192" in s for s in sizes):
            failures.append("PWA: manifest precisa de ícone 192x192.")
        if not any("512" in s for s in sizes):
            failures.append("PWA: manifest precisa de ícone 512x512.")
    else:
        failures.append("PWA: `public/manifest.webmanifest` ausente.")
    for icon_name in ("icon-192.png", "icon-512.png"):
        icon_path = root / "public" / icon_name
        if not icon_path.is_file():
            icon_path = root.parent / "public" / icon_name
        if not icon_path.is_file():
            failures.append(f"PWA: `{icon_name}` ausente em public/.")
    html = root / "index.html"
    if not html.is_file():
        html = root.parent / "index.html"
    if html.is_file():
        html_text = html.read_text(encoding="utf-8", errors="replace").lower()
        if "manifest" not in html_text:
            failures.append("PWA: index.html deve referenciar manifest.")
        if "apple-mobile-web-app" not in html_text and "mobile-web-app-capable" not in html_text:
            failures.append("PWA: index.html deve ter meta apple-mobile-web-app-capable.")
    return failures


def _read_css_chunks(root: Path) -> tuple[str, int]:
    chunks: list[str] = []
    for path in (root / "src" / "index.css", root / "theme" / "tokens.css"):
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    combined = "\n".join(chunks)
    return combined, len(combined.encode("utf-8"))


def validate_source_css(root: Path, *, spec: dict[str, Any] | None = None) -> list[str]:
    """CSS no disco — seed-pass não substitui refine visual."""
    if (spec or {}).get("ravennaHomeSkipCssSeed"):
        return []
    failures: list[str] = []
    if not root.is_dir():
        return ["projectRoot do frontend não encontrado."]
    css, css_bytes = _read_css_chunks(root)
    if css_bytes < MIN_SOURCE_CSS_BYTES:
        failures.append(
            f"CSS fonte muito curto ({css_bytes} bytes) — seed não escreve index.css; "
            "refine visual obrigatório (`delivery_mode=refine`)."
        )
    css_lower = css.lower()
    if any(hint in css_lower for hint in _CSS_PLACEHOLDER_HINTS):
        failures.append("CSS fonte contém placeholder (ex.: path/to/) — substituir por estilos reais.")
    mode = (spec or {}).get("ravennaHomeUiMode")
    if mode in {"space-chat", "voice-pwa"}:
        if not any(marker in css_lower for marker in _SPACE_CHAT_CSS_MARKERS):
            failures.append(
                "CSS fonte sem marcadores espaço/neon (.space-bg, .tab-bar, neon, etc.)."
            )
    return failures


def validate_production_css_body(css_body: str, *, asset_name: str = "", ui_mode: str | None = None) -> list[str]:
    """Bundle CSS servido em :5174 — detecta stub/245B sem tema."""
    failures: list[str] = []
    body = css_body or ""
    size = len(body.encode("utf-8"))
    label = asset_name or "index-*.css"
    if size < MIN_PRODUCTION_CSS_BYTES:
        failures.append(
            f"Produção CSS stub ({size} bytes em {label}) — HTML sem tema; "
            "rebuild completo de ravenna-home-web necessário."
        )
        return failures
    lower = body.lower()
    if any(hint in lower for hint in _CSS_PLACEHOLDER_HINTS):
        failures.append(f"Produção CSS contém placeholder em {label}.")
    mode = (ui_mode or "").strip().lower()
    if mode in {"gemini-space", "web-gemini", "chat-history-gemini"}:
        gemini_required = ("starfield", "chat-input-dock", "100dvh")
        missing = [m for m in gemini_required if m not in lower]
        if missing:
            failures.append(
                f"Produção CSS gemini incompleto em {label} — faltam: {', '.join(missing)}."
            )
        return failures
    if not any(marker in lower for marker in _PRODUCTION_CSS_MARKERS):
        failures.append(
            f"Produção CSS sem marcadores visuais (.tab-bar, neon, viewport) em {label}."
        )
    missing_required = [m for m in _PRODUCTION_CSS_REQUIRED if m not in lower]
    if missing_required:
        failures.append(
            f"Produção CSS incompleto em {label} — faltam: {', '.join(missing_required)}."
        )
    return failures


def fetch_production_css_body(home_url: str, html: str) -> tuple[str, dict[str, str]]:
    """Baixa bundle CSS referenciado no HTML de produção."""
    assets = parse_assets_from_html(html)
    css_name = assets.get("css") or ""
    if not css_name:
        return "", assets
    try:
        import httpx

        css_url = f"{home_url.rstrip('/')}/assets/{css_name}"
        css_body = httpx.get(css_url, timeout=30).text
        return css_body, assets
    except Exception:
        return "", assets


def validate_production_visual(
    html: str,
    *,
    home_url: str = "",
    css_body: str | None = None,
    previous_assets: dict[str, str] | None = None,
    skip_asset_compare: bool = False,
    ui_mode: str | None = None,
) -> list[str]:
    """Aceite visual :5174 — assets + tamanho/conteúdo do CSS bundle."""
    failures = validate_production(
        html,
        previous_assets=previous_assets,
        skip_asset_compare=skip_asset_compare,
    )
    assets = parse_assets_from_html(html)
    css_name = assets.get("css") or ""
    body = css_body
    if body is None and home_url and css_name:
        body, _ = fetch_production_css_body(home_url, html)
    if body is not None:
        failures.extend(validate_production_css_body(body, asset_name=css_name, ui_mode=ui_mode))
    elif css_name:
        failures.append(f"Não foi possível ler bundle CSS de produção ({css_name}).")
    return failures


def validate_production(
    html: str,
    *,
    previous_assets: dict[str, str] | None = None,
    skip_asset_compare: bool = False,
) -> list[str]:
    """Aceite Cursor em :5174 — assets e sinais mínimos."""
    failures: list[str] = []
    js = _extract_asset(html, ".js")
    css = _extract_asset(html, ".css")
    if not js:
        failures.append("Produção :5174 sem asset JS.")
    if not css:
        failures.append("Produção :5174 sem asset CSS.")
    if previous_assets and not skip_asset_compare:
        if js and previous_assets.get("js") == js:
            failures.append(f"Deploy não detectado — JS inalterado ({js}).")
        if css and previous_assets.get("css") == css:
            failures.append(f"Deploy CSS não detectado ({css}).")
    return failures


def _resolve_home_url(explicit: str = "") -> str:
    import os

    candidates = [
        explicit,
        os.environ.get("RAVENNA_HOME_URL", ""),
        os.environ.get("RAVENNA_HOME_INTERNAL_URL", ""),
        "http://ravenna-home-web",
        "http://host.docker.internal:5174",
        "http://ravenna-vm:5174",
        "http://127.0.0.1:5174",
    ]
    for key in candidates:
        clean = (key or "").strip().rstrip("/")
        if clean:
            return clean
    return "http://ravenna-vm:5174"


def run_visual_vistoria(
    root: Path | None,
    *,
    spec: dict[str, Any] | None = None,
    home_url: str = "",
) -> dict[str, Any]:
    """Vistoria determinística — filesystem + produção + marcadores visuais."""
    spec = dict(spec or {})
    home_url = _resolve_home_url(home_url)
    gaps: list[str] = []
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {"home_url": home_url}

    if root and root.is_dir():
        fs_failures = validate_filesystem(root, spec=spec)
        css_failures = validate_source_css(root, spec=spec)
        css_text, css_bytes = _read_css_chunks(root)
        evidence["filesystem"] = {
            "root": str(root),
            "css_source_bytes": css_bytes,
            "css_markers": {m: m in css_text.lower() for m in _SPACE_CHAT_CSS_MARKERS},
        }
        for name, ok in evidence["filesystem"]["css_markers"].items():
            checks.append({"item": f"fs-css-{name}", "ok": ok})
        gaps.extend(fs_failures)
        gaps.extend(css_failures)
        checks.append({"item": "filesystem", "ok": not fs_failures})
    else:
        gaps.append("projectRoot do frontend não encontrado para vistoria filesystem.")
        checks.append({"item": "filesystem", "ok": False})

    html = ""
    assets: dict[str, str] = {}
    css_body = ""
    prod_ok = False
    try:
        import httpx

        for candidate in (
            home_url,
            "http://ravenna-home-web",
            "http://host.docker.internal:5174",
            "http://ravenna-vm:5174",
        ):
            url = (candidate or "").strip().rstrip("/")
            if not url:
                continue
            try:
                html = httpx.get(url, timeout=45).text
                home_url = url
                prod_ok = True
                break
            except Exception:
                continue
        if not prod_ok:
            raise RuntimeError(f"nenhum endpoint respondeu ({home_url})")
        assets = parse_assets_from_html(html)
        css_body, _ = fetch_production_css_body(home_url, html)
        prod_failures = validate_production_visual(
            html,
            home_url=home_url,
            css_body=css_body,
        )
        evidence["production"] = {
            "assets": assets,
            "css_bundle_bytes": len((css_body or "").encode("utf-8")),
            "html_len": len(html),
        }
        gaps.extend(prod_failures)
        checks.append({"item": "production-css-size", "ok": not any("stub" in g.lower() or "bytes" in g for g in prod_failures if "CSS" in g)})
        checks.append({"item": "production-assets", "ok": bool(assets.get("js") and assets.get("css"))})
    except Exception as exc:
        gaps.append(f"Produção inacessível ({home_url}): {exc}")
        checks.append({"item": "production-reachable", "ok": False})

    if css_body:
        css_lower = css_body.lower()
        for marker in ("tab-bar", "neon", "space-bg", "chat-fullscreen", "100dvh"):
            ok = marker in css_lower
            checks.append({"item": f"prod-css-{marker}", "ok": ok})
            if not ok:
                gaps.append(f"Produção: marcador CSS `{marker}` ausente no bundle.")

    score = max(0, 100 - min(100, 5 * len(gaps)))
    combined = " ".join(gaps).lower()
    critical = any(
        token in combined
        for token in (
            "stub",
            "placeholder",
            "path/to/",
            "inacessível",
            "inacessivel",
            "sem asset css",
            "html cru",
            "refine visual obrigatório",
        )
    )
    if not gaps:
        verdict = "APROVADO"
    elif critical or score < 70:
        verdict = "REPROVADO"
    elif score >= 70:
        verdict = "APROVADO COM RESSALVAS"
    else:
        verdict = "REPROVADO"

    root_cause = _infer_visual_root_cause(gaps, evidence)
    return {
        "verdict": verdict,
        "score": score,
        "gaps": gaps,
        "checks": checks,
        "evidence": evidence,
        "root_cause": root_cause,
    }


def _infer_visual_root_cause(gaps: list[str], evidence: dict[str, Any]) -> str:
    """Explica por que filesystem OK pode coexistir com produção quebrada."""
    fs_css = (evidence.get("filesystem") or {}).get("css_source_bytes") or 0
    prod_css = (evidence.get("production") or {}).get("css_bundle_bytes") or 0
    combined = " ".join(gaps).lower()
    if prod_css and prod_css < MIN_PRODUCTION_CSS_BYTES:
        return (
            "seed-pass aprovou filesystem sem refine de index.css e deploy rápido (up sem rebuild) "
            "serviu bundle CSS stub em :5174 — HTML cru sem tema."
        )
    if fs_css >= MIN_SOURCE_CSS_BYTES and prod_css < MIN_PRODUCTION_CSS_BYTES:
        return (
            "CSS fonte OK no disco mas bundle de produção desatualizado — "
            "docker compose build ravenna-home-web necessário após writes."
        )
    if "placeholder" in combined:
        return "CSS contém placeholder; refine em index.css + rebuild completo."
    if any("ausente" in g.lower() for g in gaps):
        return "Diagnóstico deve usar read_file/GROUNDING — arquivos seedados existem no projectRoot."
    if fs_css < MIN_SOURCE_CSS_BYTES:
        return (
            "Infra seed não escreve index.css (by design); rh-09 seed-pass pulou LLM refine — "
            "visual nunca foi aplicado."
        )
    return "Filesystem e produção divergem — validar deploy e refine CSS."


def format_vistoria_report(
    audit: dict[str, Any],
    *,
    auditor: str = "Ravenna",
    include_root_cause: bool = True,
) -> str:
    """Markdown determinístico para modo vistoria (sem alucinação)."""
    lines = [
        f"### Vistoria visual — {auditor}",
        f"**Veredito:** {audit.get('verdict', 'INDETERMINADO')} (score {audit.get('score', 0)})",
        "",
        "#### 1. Checklist",
    ]
    for row in audit.get("checks") or []:
        mark = "OK" if row.get("ok") else "FALHA"
        lines.append(f"- [{mark}] {row.get('item')}")
    lines.extend(["", "#### 2. Regressões / gaps"])
    gaps = audit.get("gaps") or []
    if gaps:
        for gap in gaps[:20]:
            lines.append(f"- {gap}")
    else:
        lines.append("- Nenhum gap detectado.")
    if include_root_cause and audit.get("root_cause"):
        lines.extend(["", "#### 3. Causa provável", audit["root_cause"]])
    ev = audit.get("evidence") or {}
    prod = ev.get("production") or {}
    fs = ev.get("filesystem") or {}
    if prod or fs:
        lines.extend(
            [
                "",
                "#### 4. Evidências",
                f"- CSS fonte: {fs.get('css_source_bytes', '?')} bytes",
                f"- CSS produção: {prod.get('css_bundle_bytes', '?')} bytes ({prod.get('assets', {}).get('css', '?')})",
                f"- URL: {ev.get('home_url', '?')}",
            ]
        )
    lines.extend(["", "#### 5. Top correções (prioridade)"])
    if audit.get("verdict") == "APROVADO":
        lines.append("- Nenhuma — visual OK.")
    else:
        fixes = [
            "Emitir `write src/index.css` com tema espaço/neon (.tab-bar, .chat-fullscreen, 100dvh).",
            "Rebuild completo: docker compose build ravenna-home-web (não só up).",
            "Confirmar :5174 com Ctrl+F5 — bundle CSS > 400 bytes e com .tab-bar.",
        ]
        if "placeholder" in " ".join(gaps).lower():
            fixes.insert(0, "Remover placeholders (path/to/) do CSS.")
        for i, fix in enumerate(fixes[:5], 1):
            lines.append(f"{i}. {fix}")
    return "\n".join(lines)


def _extract_asset(html: str, ext: str) -> str | None:
    match = re.search(rf'/assets/index-[A-Za-z0-9_-]+\.{ext.replace(".", "")}', html)
    return match.group(0).split("/")[-1] if match else None


def parse_assets_from_html(html: str) -> dict[str, str]:
    return {
        "js": _extract_asset(html, ".js") or "",
        "css": _extract_asset(html, ".css") or "",
    }


def cursor_acceptance_summary(
    *,
    autonomy_passed: bool | None,
    fs_failures: list[str],
    prod_failures: list[str],
    training_failures: list[str] | None = None,
) -> dict[str, Any]:
    """Barra Cursor = filesystem + produção + gate treino autonomia."""
    all_failures = list(fs_failures) + list(prod_failures) + list(training_failures or [])
    approved = not all_failures
    return {
        "approved": approved,
        "verdict": "APROVADO" if approved else "REPROVADO",
        "failures": all_failures,
        "autonomy_passed": autonomy_passed,
    }
