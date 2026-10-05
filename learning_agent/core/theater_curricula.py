"""Currículos do modo observador — trilhas de ensino por tema."""

from __future__ import annotations

from typing import Any

# 5 voltas × 7 trilhas = 35 ciclos
remoteapp_FRONTEND_VOLTAS = 5
remoteapp_FRONTEND_TRACKS_COUNT = 7
remoteapp_FRONTEND_MAX_CYCLES = remoteapp_FRONTEND_VOLTAS * remoteapp_FRONTEND_TRACKS_COUNT

# ~80s por ciclo (lições + pausas + síntese Ravenna)
remoteapp_CYCLE_SECONDS_EST = 80
remoteapp_SESSION_MINUTES_EST = (remoteapp_FRONTEND_MAX_CYCLES * remoteapp_CYCLE_SECONDS_EST) // 60

remoteapp_DESIGN = (
    "**Projeto RemoteApp** — identidade visual da Ravenna IDE: fundo `#050510`, grid cyber, "
    "glass panels (`backdrop-filter`), gradientes violeta→ciano, fontes Orbitron + Rajdhani, "
    "núcleo neural Three.js como ícone central (sinapses, partículas, anéis orbitais). "
    "Toda UI deve respirar essa estética futurista sem sacrificar legibilidade (WCAG AA)."
)

# 2 voltas × 4 trilhas = 8 ciclos (~11 min)
HTML_DETAILS_VOLTAS = 2
HTML_DETAILS_TRACKS_COUNT = 4
HTML_DETAILS_MAX_CYCLES = HTML_DETAILS_VOLTAS * HTML_DETAILS_TRACKS_COUNT
HTML_DETAILS_CYCLE_SECONDS_EST = 82
HTML_DETAILS_SESSION_MINUTES_EST = (HTML_DETAILS_MAX_CYCLES * HTML_DETAILS_CYCLE_SECONDS_EST) // 60

HTML_DETAILS_TRACKS: list[dict[str, Any]] = [
    {
        "id": "details-structure",
        "level": "HTML — details/summary estrutura DOM",
        "agent": "senior-fe",
        "agent_label": "Especialista HTML",
        "search": "NeuralReasoningDetails details summary ChatPanel",
        "lesson": (
            "`<details>` + `<summary>` formam disclosure nativo. **Regra:** `summary` é o primeiro "
            "filho direto de `details`; conteúdo revelado vem depois. "
            "Localizar no RemoteApp: `rg '<details'` — nunca grep só `summary` (ruído de API Python). "
            "Docs: `docs/frontend/html-details-summary.md`. "
            "Componente canônico: `NeuralReasoningDetails.tsx`."
        ),
        "superior": (
            "Próximo nível: validar árvore DOM no DevTools após cada refactor; "
            "proibir wrappers entre details e summary."
        ),
    },
    {
        "id": "details-react",
        "level": "React/TSX — realocar disclosures no chat",
        "agent": "senior-fe",
        "agent_label": "Eng. React Sênior",
        "search": "NeuralReasoningDetails ChatPanel time timestamp",
        "lesson": (
            "Padrão RemoteApp: bolha da mensagem só com texto principal; "
            "`<NeuralReasoningDetails>` **abaixo** do `<time>`, fora da bolha. "
            "Mover o bloco `details` inteiro — não separar summary do conteúdo. "
            "Extrair componente evita duplicação entre Chat e Observer. "
            "Falha comum registrada: mover só o `<p>` e quebrar hierarquia."
        ),
        "superior": (
            "Próximo nível: Storybook com variantes chat/observer; "
            "teste Testing Library no toggle do summary."
        ),
    },
    {
        "id": "details-a11y",
        "level": "A11y — disclosure e acordeão exclusivo",
        "agent": "reviewer",
        "agent_label": "Revisor A11y",
        "search": "ObserverPanel NeuralReasoningDetails name reasoning",
        "lesson": (
            "Disclosure nativo > div+onClick: summary focável, Enter/Espaço, SR anuncia estado. "
            "ObserverPanel: `name=\"remote_app-observer-reasoning\"` em todos os details com raciocínio — "
            "acordeão exclusivo HTML sem JS. "
            "Summary com texto descritivo ('Raciocínio neural', 'Raciocínio da lição'). "
            "Docs expert: `html-details-summary-expert.md`."
        ),
        "superior": (
            "Próximo nível: axe-core no CI para Chat/Observer; "
            "auditoria de foco visível no summary estilizado."
        ),
    },
    {
        "id": "details-css",
        "level": "CSS — .remote_app-details e motion seguro",
        "agent": "senior-fe",
        "agent_label": "Especialista CSS",
        "search": "remote_app-details globals.css summary",
        "lesson": (
            "Classe `.remote_app-details`: esconder marker (`list-style: none`, `::-webkit-details-marker`), "
            "indicador `summary::after` rotaciona em `details[open]`. "
            "Opcional: animar `::details-content` com opacity/translateY. "
            "`@media (prefers-reduced-motion: reduce)`: `animation: none` no conteúdo revelado. "
            "Manter contraste ciano/violeta sobre fundo mente infinita."
        ),
        "superior": (
            "Próximo nível: motion tokens RemoteApp para duração do reveal; "
            "regressão visual Playwright no toggle."
        ),
    },
]

remoteapp_FRONTEND_TRACKS: list[dict[str, Any]] = [
    {
        "id": "html-semantic",
        "level": "HTML — semântica & acessibilidade",
        "agent": "senior-fe",
        "agent_label": "Especialista HTML",
        "search": "index.html App.tsx ChatPanel NeuralReasoningDetails",
        "lesson": (
            "HTML não é div-soup: use landmarks (`header`, `main`, `nav`, `section`, `article`). "
            "Hierarquia de headings sem pular níveis; `alt` descritivo em imagens; formulários com "
            "`label` explícito e `aria-describedby` para erros. "
            "Disclosure: `<details>`/`<summary>` via `NeuralReasoningDetails` — summary primeiro filho. "
            "No RemoteApp: o chat é `main`, o núcleo neural é `aside` decorativo com `aria-hidden`, "
            "mensagens em `role=log` ou lista com `aria-live=polite` para novas respostas da Ravenna. "
            "Prefer `button` sobre `div onClick`; use `lang=pt-BR` e meta viewport corretos."
        ),
        "superior": (
            "Próximo nível: skip links, focus trap em modais, testes axe-core no CI, "
            "e documentação de padrões HTML no design system RemoteApp."
        ),
    },
    {
        "id": "css-modern",
        "level": "CSS — arquitetura & melhores práticas",
        "agent": "senior-fe",
        "agent_label": "Arquiteta CSS",
        "search": "globals.css tailwind glass-panel",
        "lesson": (
            "Organize CSS em camadas: reset → tokens → componentes → utilitários. "
            "Design tokens via custom properties (`--remote_app-violet`, `--remote_app-cyan`, `--glass-blur`). "
            "Tailwind para velocidade + classes semânticas `.glass-panel`, `.font-display` no RemoteApp. "
            "Evite especificidade alta; prefira `@layer components`. "
            "Container queries para painéis responsivos; `clamp()` para tipografia fluida. "
            "Nunca estilize por ID; mobile-first; teste contraste dos gradientes sobre `#050510`."
        ),
        "superior": (
            "Próximo nível: Style Dictionary para tokens, CSS Modules ou vanilla-extract por feature, "
            "e documentação Storybook com variantes RemoteApp."
        ),
    },
    {
        "id": "css-animations",
        "level": "CSS Animations — motion design nativo",
        "agent": "senior-fe",
        "agent_label": "Motion Designer CSS",
        "search": "globals.css animate keyframes scanline",
        "lesson": (
            "Separe **transition** (estado A→B) de **@keyframes** (loops e entradas). "
            "Use `transform` + `opacity` apenas (compositor-friendly); evite animar `width/height/top`. "
            "RemoteApp já usa: `msg-in-left/right`, `border-flow`, `scanline`, `neural-dot`, `chip-glow`. "
            "Sempre ofereça `prefers-reduced-motion: reduce` desligando scanlines e parallax. "
            "Scroll-driven animations (`animation-timeline: scroll()`) para revelar domínios aprendidos. "
            "View Transitions API para trocar Chat↔Observador sem flash."
        ),
        "superior": (
            "Próximo nível: biblioteca de motion tokens RemoteApp (`--duration-fast`, `--ease-spring`), "
            "e testes visuais de regressão em animações críticas."
        ),
    },
    {
        "id": "javascript-patterns",
        "level": "JavaScript — padrões avançados no front",
        "agent": "senior-fe",
        "agent_label": "Eng. JavaScript Sênior",
        "search": "websocket api.ts useEffect useState",
        "lesson": (
            "Módulos ES com boundaries claros: `api.ts`, `websocket.ts`, hooks dedicados. "
            "Estado: eleve o mínimo necessário; derive dados; evite effect chains frágeis. "
            "Async: abort controllers em fetch, retry com backoff no WS, idempotência em envios. "
            "Performance: memoize callbacks estáveis, lazy-load Three.js/NeuralCore, "
            "`requestAnimationFrame` para ler DOM após layout. "
            "TypeScript estrito; discriminated unions para `MessageRole`; nunca `any` em payloads WS."
        ),
        "superior": (
            "Próximo nível: Zustand para theater+chat, React Query para progress/API, "
            "Vitest + MSW para contratos REST/WS."
        ),
    },
    {
        "id": "canvas-svg",
        "level": "Canvas API & SVG — gráficos híbridos",
        "agent": "architect",
        "agent_label": "Arquiteta Gráficos Web",
        "search": "NeuralCore three canvas",
        "lesson": (
            "**Canvas 2D**: contexto único, `devicePixelRatio`, dirty rectangles, offscreen canvas para partículas. "
            "**SVG**: ícones RemoteApp escaláveis, filtros (`feGaussianBlur`, `feColorMatrix`) para glow do núcleo, "
            "`stroke-dashoffset` para sinapses animadas sem WebGL. "
            "Quando Canvas vs SVG vs WebGL (Three.js): Canvas para 2D dinâmico massivo; SVG para UI vetorial; "
            "Three.js para o núcleo neural 3D do RemoteApp. "
            "Híbrido: SVG overlay HUD sobre canvas WebGL — padrão do `NeuralCore.tsx`."
        ),
        "superior": (
            "Próximo nível: exportar ícone RemoteApp como SVG sprite sheet + fallback Canvas para mobile fraco, "
            "e layer compositing com `will-change` cirúrgico."
        ),
    },
    {
        "id": "gsap-motion",
        "level": "GSAP (GreenSock) — animação profissional",
        "agent": "senior-fe",
        "agent_label": "Especialista GSAP",
        "search": "NeuralCore ChatPanel animation",
        "lesson": (
            "GSAP Timeline orquestra sequências: entrada do chat, pulso do núcleo, stagger nas mensagens. "
            "`gsap.to('.synapse', { motionPath, duration })` para fios neurais; "
            "ScrollTrigger para revelar domínios no welcome screen. "
            "Integre com Three.js via `gsap.ticker` sincronizado ao render loop — não duplique RAF. "
            "SVG morph com MorphSVG (ou plugin free equivalente) para transição ícone RemoteApp. "
            "Respeite `matchMedia('(prefers-reduced-motion)')` com `gsap.globalTimeline.pause()`. "
            "Nunca anime layout properties; use transforms e CSS variables que o GSAP controla."
        ),
        "superior": (
            "Próximo nível: `@gsap/react` hooks, timeline compartilhada remoteappDesign.motion, "
            "e lazy import do GSAP só na rota que precisa."
        ),
    },
    {
        "id": "remote_app-architecture",
        "level": "Arquitetura Frontend RemoteApp — nível staff",
        "agent": "architect",
        "agent_label": "Arquiteta Frontend Staff",
        "search": "App.tsx components pages styles",
        "lesson": (
            f"{remoteapp_DESIGN}\n\n"
            "**Arquitetura em camadas (Feature-Sliced + Atomic):**\n"
            "`app/` (providers, layout RemoteApp shell) → `pages/` (ChatPage, ObserverPage) → "
            "`widgets/` (NeuralCoreWidget, ChatWidget) → `features/` (sendMessage, theaterStream) → "
            "`entities/` (Message, NeuralState) → `shared/` (ui, api, tokens, motion).\n"
            "Unidirecional: shared não importa features; features não importam pages.\n"
            "**Shell RemoteApp**: header fixo + main split (neural | content) + mode switcher Chat|Observador.\n"
            "**Dados**: REST para chat/progress; WS para theater em tempo real; estado UI local vs servidor.\n"
            "**Performance budget**: LCP < 2.5s, Three.js < 16ms/frame, bundle split por rota.\n"
            "**Testes**: Vitest unit, Testing Library integração, Playwright e2e do fluxo observador."
        ),
        "superior": (
            "Próximo nível: monorepo packages `@remote_app/tokens`, `@remote_app/motion`, `@remote_app/neural-core` "
            "publicáveis; ADRs documentando cada decisão; e Storybook como fonte única de verdade visual."
        ),
    },
]

# 3 voltas × 8 trilhas = 24 ciclos (~34 min)
BACKEND_MASTERY_VOLTAS = 3
BACKEND_MASTERY_TRACKS_COUNT = 8
BACKEND_MASTERY_MAX_CYCLES = BACKEND_MASTERY_VOLTAS * BACKEND_MASTERY_TRACKS_COUNT
BACKEND_CYCLE_SECONDS_EST = 85
BACKEND_SESSION_MINUTES_EST = (BACKEND_MASTERY_MAX_CYCLES * BACKEND_CYCLE_SECONDS_EST) // 60

BACKEND_MASTERY_TRACKS: list[dict[str, Any]] = [
    {
        "id": "http-rest",
        "level": "HTTP & REST — fundamentos de API",
        "agent": "senior-be",
        "agent_label": "Arquiteto de APIs",
        "search": "api.py theater start POST GET",
        "lesson": (
            "REST: recursos com substantivos, verbos HTTP corretos, status semânticos. "
            "Idempotência: GET/PUT/DELETE sim; POST não. "
            "No learning-agent: `/api/theater/start`, `/api/chat`, `/api/theater/status`. "
            "Apostila: `docs/backend/backend-mastery.md` §1. "
            "Richardson nível 2: recursos + HTTP verbs + status codes."
        ),
        "superior": (
            "Próximo nível: HATEOAS links em respostas; contrato OpenAPI versionado `/api/v1/`."
        ),
    },
    {
        "id": "python-async",
        "level": "Python — tipagem, async e módulos",
        "agent": "senior-be",
        "agent_label": "Eng. Python Sênior",
        "search": "async def run_in_executor asyncio theater",
        "lesson": (
            "Separe I/O async (`async def` routes) de CPU/sync (executor). "
            "Tipagem estrita + Pydantic nas fronteiras. "
            "Pacote `core/` por domínio — não god-module. "
            "Teatro: `wait_for` no LLM, `run_in_executor` no SQLite/RAG. "
            "Nunca `time.sleep` em coroutine — use `asyncio.sleep`."
        ),
        "superior": (
            "Próximo nível: aiosqlite; pydantic-settings; structlog JSON."
        ),
    },
    {
        "id": "fastapi-patterns",
        "level": "FastAPI — padrões de excelência",
        "agent": "senior-be",
        "agent_label": "Especialista FastAPI",
        "search": "api.py FastAPI WebSocket ChatRequest",
        "lesson": (
            "Handlers finos → delegam para `core/`. "
            "Pydantic models: ChatRequest, TheaterPostRequest. "
            "Background: `asyncio.create_task` no teatro. "
            "WebSocket `/ws` via `ravenna_ide.handle_connection`. "
            "Depends para DB session e auth futura. "
            "Documentação automática em `/docs` — mantenha exemplos atualizados."
        ),
        "superior": (
            "Próximo nível: lifespan context; middleware request_id; exception handlers globais."
        ),
    },
    {
        "id": "database-sql",
        "level": "SQL, SQLite & persistência",
        "agent": "senior-be",
        "agent_label": "Eng. de Dados",
        "search": "db.py get_connection quiz_items learning_notes",
        "lesson": (
            "SQLite em `db.py` — context manager, queries parametrizadas. "
            "Tabelas: learning_notes, quiz_items, learning_errors, knowledge_edges. "
            "Índices em next_review, created_at. "
            "Transações curtas; evitar lock em writes longos durante teatro. "
            "Migrations explícitas ao evoluir schema."
        ),
        "superior": (
            "Próximo nível: Alembic migrations; Postgres + pool para multi-instância."
        ),
    },
    {
        "id": "api-design",
        "level": "Design de API & contratos",
        "agent": "architect",
        "agent_label": "Arquiteta de Contratos",
        "search": "theater messages limit consolidation",
        "lesson": (
            "Erros estruturados com `detail` + código interno. "
            "Paginação: `limit` cap (ex. 120 em theater messages). "
            "WS + REST: mesmo schema de Message para observador. "
            "Currículos whitelist em start_theater. "
            "Consolidação retorna nota mestra + quiz_count — contrato estável."
        ),
        "superior": (
            "Próximo nível: JSON Schema publicado; breaking change policy semver API."
        ),
    },
    {
        "id": "security",
        "level": "Segurança backend",
        "agent": "reviewer",
        "agent_label": "Revisor Segurança",
        "search": "CORS api key Groq environment",
        "lesson": (
            "Validar todo input (Pydantic + limites). "
            "CORS: localhost em dev; restrito em prod. "
            "Secrets: GROQ_API_KEY, nunca em repo. "
            "Rate limit em /api/chat público. "
            "Auth JWT antes de expor na internet. "
            "Logs sem PII/tokens."
        ),
        "superior": (
            "Próximo nível: OWASP API Top 10 checklist no CI; dependabot."
        ),
    },
    {
        "id": "testing-observability",
        "level": "Testes & observabilidade",
        "agent": "mentor",
        "agent_label": "Mentor Qualidade",
        "search": "pytest proofs health theater status",
        "lesson": (
            "pytest: unit em core/, TestClient integração API. "
            "Mock LLM em testes de teatro — determinismo. "
            "prove_python_code para código gerado. "
            "Health: DB + LLM reachable. "
            "Logs estruturados; métricas latência p95 por rota."
        ),
        "superior": (
            "Próximo nível: OpenTelemetry traces teatro→LLM→DB; coverage gate 80% core/."
        ),
    },
    {
        "id": "architecture-staff",
        "level": "Arquitetura backend — nível staff",
        "agent": "architect",
        "agent_label": "Arquiteta Staff",
        "search": "consolidation theater_curricula mcp_server core",
        "lesson": (
            "Camadas: api/mcp → core → db. Bounded contexts: aprendizado, teatro, IDE. "
            "Currículo backend-mastery: trilhas em theater_curricula, quiz dedicado, consolidação. "
            "Polyglot: Go/Node/Java/Rust — mesmos princípios (camadas, contratos, falha explícita). "
            "Doc expert: `docs/backend/backend-mastery-expert.md`. "
            "Escala: filas para indexação, Redis pub/sub para WS multi-instância."
        ),
        "superior": (
            "Próximo nível: ADRs; extrair `@ravenna/core` package; event-driven consolidation."
        ),
    },
]

# 2 voltas × 6 trilhas = 12 ciclos (~10 min) — reforço pós-quiz
REINFORCE_WEAK_VOLTAS = 2
REINFORCE_WEAK_TRACKS_COUNT = 6
REINFORCE_WEAK_MAX_CYCLES = REINFORCE_WEAK_VOLTAS * REINFORCE_WEAK_TRACKS_COUNT
REINFORCE_WEAK_CYCLE_SECONDS_EST = 70
REINFORCE_WEAK_SESSION_MINUTES_EST = (
    REINFORCE_WEAK_MAX_CYCLES * REINFORCE_WEAK_CYCLE_SECONDS_EST
) // 60

REINFORCE_WEAK_TRACKS: list[dict[str, Any]] = [
    {
        "id": "reinforce-be-http",
        "level": "Reforço — HTTP, status e contratos Pydantic",
        "agent": "senior-be",
        "agent_label": "Arquiteto de APIs",
        "search": "Status HTTP 422 409 Pydantic ChatRequest validation",
        "lesson": (
            "**Falhas em quiz:** Status HTTP, Pydantic & contratos, Design de API. "
            "Mapa obrigatório: 422 validação Pydantic; 409 teatro já ativo; 504/503 LLM timeout; "
            "404 recurso. Nunca 200 com erro no body. "
            "Models nas fronteiras: ChatRequest, TheaterPostRequest — campos tipados, limites explícitos. "
            "Design: erros com `detail` + código interno; paginação com `limit` cap; "
            "contrato estável em consolidação (nota mestra + quiz_count). "
            "Apostila: `docs/reinforcement/weak-areas-refocus.md` §Backend HTTP."
        ),
        "superior": (
            "Próximo nível: exception handler global FastAPI mapeando exceções → status; "
            "OpenAPI exemplos de erro por rota."
        ),
    },
    {
        "id": "reinforce-be-fastapi",
        "level": "Reforço — FastAPI camadas, testes e cenário staff",
        "agent": "senior-be",
        "agent_label": "Especialista FastAPI",
        "search": "api.py core handlers pytest TestClient theater",
        "lesson": (
            "**Falhas em quiz:** FastAPI camadas, Testes, cenário especialista backend. "
            "Handlers finos em `api.py` → delegam para `core/theater`, `core/consolidation`. "
            "Testes: pytest unit em core/; TestClient para `/api/theater/start`; "
            "mock LLM para determinismo no teatro. "
            "Cenário staff: adicionar currículo = theater_curricula + consolidation + whitelist + quiz. "
            "`insert_curriculum_questions` evita duplicar quizzes idênticos."
        ),
        "superior": (
            "Próximo nível: teste e2e teatro max_cycles=1 com mock; lifespan + middleware request_id."
        ),
    },
    {
        "id": "reinforce-be-ops",
        "level": "Reforço — segurança, observabilidade e polyglot",
        "agent": "reviewer",
        "agent_label": "Revisor Segurança",
        "search": "health CORS rate limit Go Node observability logs",
        "lesson": (
            "**Falhas em quiz:** Segurança, Observabilidade, Go vs Python, Node/NestJS. "
            "Segurança: Pydantic + limites; CORS restrito em prod; secrets fora do repo; "
            "rate limit em /api/chat; logs sem tokens. "
            "Observabilidade: GET /health (SQLite + teatro + weak_areas); logs estruturados; p95 por rota. "
            "Polyglot: Go (workers/throughput), Node/Nest (DI/controllers) — mesmos princípios: "
            "camadas, contratos explícitos, falha visível."
        ),
        "superior": (
            "Próximo nível: OWASP API checklist no CI; OpenTelemetry trace teatro→LLM→DB."
        ),
    },
    {
        "id": "reinforce-fe-details-dom",
        "level": "Reforço — DOM, React e realocação no chat",
        "agent": "senior-fe",
        "agent_label": "Especialista HTML",
        "search": "NeuralReasoningDetails ChatPanel time summary first child",
        "lesson": (
            "**Falhas em quiz:** estrutura DOM, realocar no chat, componente React. "
            "Regra de ouro: `<summary>` é o **primeiro filho direto** de `<details>`. "
            "Chat RemoteApp: bolha só com `<p>`; `<time>`; depois `<NeuralReasoningDetails>` como irmão. "
            "Mover o bloco `details` inteiro — nunca só o `<p>` interno. "
            "Componente único `NeuralReasoningDetails.tsx` evita drift Chat vs Observer."
        ),
        "superior": (
            "Próximo nível: Testing Library no toggle; Storybook variantes chat/observer."
        ),
    },
    {
        "id": "reinforce-fe-details-a11y",
        "level": "Reforço — a11y, CSS marker e motion seguro",
        "agent": "reviewer",
        "agent_label": "Revisor A11y",
        "search": "remote_app-details globals.css prefers-reduced-motion name acordeão",
        "lesson": (
            "**Falhas em quiz:** a11y teclado/SR, CSS marker RemoteApp, motion reduzido, estado controlado. "
            "Summary focável: Enter/Espaço; SR anuncia expanded/collapsed. "
            "Observer: `name=\"remote_app-observer-reasoning\"` — acordeão exclusivo HTML. "
            "CSS `.remote_app-details`: esconder marker nativo; `summary::after` rotaciona em `[open]`. "
            "`prefers-reduced-motion: reduce` → `animation: none` no conteúdo revelado. "
            "Estado controlado: `open` prop só quando necessário — default uncontrolled."
        ),
        "superior": (
            "Próximo nível: axe-core no CI; regressão Playwright no toggle com reduced-motion."
        ),
    },
    {
        "id": "reinforce-fe-details-expert",
        "level": "Reforço — cenário especialista details/summary",
        "agent": "architect",
        "agent_label": "Arquiteta Frontend",
        "search": "html-details-summary-expert disclosure nested details",
        "lesson": (
            "**Falha em quiz:** cenário especialista Details. "
            "Checklist expert: (1) localizar com `rg '<details'` + componente canônico; "
            "(2) hierarquia summary primeiro filho; (3) acordeão exclusivo no observador; "
            "(4) motion seguro; (5) sem quebrar bolha/time no chat. "
            "Anti-padrões: div+onClick disclosure; summary estilizado sem foco visível; "
            "details aninhados sem necessidade. "
            "Docs: `html-details-summary-expert.md` + nota reforço #213."
        ),
        "superior": (
            "Próximo nível: ADR disclosure pattern RemoteApp; prova e2e observador com raciocínio expandido."
        ),
    },
]

IDE_TESTING_VOLTAS = 1
IDE_TESTING_TRACKS_COUNT = 7
IDE_TESTING_MAX_CYCLES = IDE_TESTING_VOLTAS * IDE_TESTING_TRACKS_COUNT
IDE_TESTING_CYCLE_SECONDS_EST = 90
IDE_TESTING_SESSION_MINUTES_EST = (IDE_TESTING_MAX_CYCLES * IDE_TESTING_CYCLE_SECONDS_EST) // 60

IDE_TESTING_TRACKS: list[dict[str, Any]] = [
    {
        "id": "testing-pyramid",
        "level": "IDE — Pirâmide de testes",
        "agent": "mentor",
        "agent_label": "Mentor de Testes",
        "search": "ide-testing-mastery pytest vitest playwright",
        "lesson": (
            "**Pirâmide staff:** pytest (services) → Vitest (components) → Playwright (e2e) → run_proofs.\n"
            "Cada camada prova algo distinto; verde em unit não substitui smoke no browser.\n"
            "Docs: `docs/frontend/ide-testing-mastery.md`. CI: `.github/workflows/ide-ci.yml`."
        ),
        "superior": (
            "Próximo nível: schemathesis OpenAPI; cobertura 80% em `learning_agent/core`."
        ),
    },
    {
        "id": "testing-workspace",
        "level": "IDE — Testes Explorer/Editor",
        "agent": "senior-be",
        "agent_label": "Eng. Backend QA",
        "search": "test_workspace_api resolve_path write_file",
        "lesson": (
            "`tests/test_workspace_api.py` — jail path, GET/PUT arquivos, traversal 400/403.\n"
            "Ravenna deve rodar antes de entregar fase 1–2. Scratch files em `tests/_scratch_*`."
        ),
        "superior": "Próximo nível: property-based tests em `resolve_path` com Hypothesis.",
    },
    {
        "id": "testing-terminal-attachments",
        "level": "IDE — Testes Terminal + Anexos",
        "agent": "reviewer",
        "agent_label": "Revisor QA",
        "search": "test_terminal_backend test_attachments AttachmentError",
        "lesson": (
            "Terminal: `create_backend()` retorna pty ou pipe. Anexos: whitelist MIME, RAG index.\n"
            "Supervisão: `py -m learning_agent.scripts.run_ide_test_supervision`."
        ),
        "superior": "Próximo nível: WS fake client pytest para `/ws/terminal` resize + input.",
    },
    {
        "id": "testing-mcp-git",
        "level": "IDE — Testes MCP + Git",
        "agent": "architect",
        "agent_label": "Arquiteta QA",
        "search": "test_mcp_api test_git_api mcp_bridge git_ops",
        "lesson": (
            "MCP: list/invoke via bridge; tools perigosas 403 na IDE. Git: sandbox tmp, commit isolado.\n"
            "Nunca passar flags git arbitrários do usuário."
        ),
        "superior": "Próximo nível: audit log de invocações MCP na IDE.",
    },
    {
        "id": "testing-vitest",
        "level": "IDE — Vitest componentes",
        "agent": "senior-fe",
        "agent_label": "Eng. Frontend QA",
        "search": "NeuralReasoningDetails.test.tsx vitest",
        "lesson": (
            "`npm run test` no frontend — Testing Library, jsdom, summary antes do conteúdo no DOM.\n"
            "Cada painel flutuante (Explorer, MCP, Git) deve ganhar teste de render."
        ),
        "superior": "Próximo nível: Storybook + testes visuais Chromatic.",
    },
    {
        "id": "testing-playwright",
        "level": "IDE — Playwright e2e",
        "agent": "senior-fe",
        "agent_label": "Eng. E2E",
        "search": "ide-smoke.spec.ts playwright fab-explorer",
        "lesson": (
            "`e2e/ide-smoke.spec.ts` — shell, FABs, API health/MCP/Git.\n"
            "Reinicie API :8000 após novas rotas; Vite proxy `/api` e `/health`."
        ),
        "superior": "Próximo nível: fluxo completo editor + terminal + upload no Playwright.",
    },
    {
        "id": "testing-proofs",
        "level": "IDE — Provas reais pós-teste",
        "agent": "mentor",
        "agent_label": "Mentor de Provas",
        "search": "run_proofs prove_learning_result",
        "lesson": (
            "Após pytest/vitest/e2e verdes: `run-proofs` confirma DB + Chroma + execução Python.\n"
            "Aprendizado só persiste se provas e notas KB existirem."
        ),
        "superior": "Próximo nível: gate de merge — IDE CI obrigatório em PR.",
    },
]

CURRICULA: dict[str, dict[str, Any]] = {
    "default": {
        "id": "default",
        "title": "Excelência geral (MVP → IDE)",
        "tracks": None,  # usa TEACHING_TRACKS em theater.py
        "voltas_default": None,
        "tags": ["theater", "ravenna-ide", "excelencia"],
        "note_prefix": "[Teatro]",
    },
    "remote-frontend": {
        "id": "remote-frontend",
        "title": "RemoteApp Frontend Mastery — HTML, CSS, JS, Canvas, SVG, GSAP",
        "tracks": remoteapp_FRONTEND_TRACKS,
        "voltas_default": remoteapp_FRONTEND_VOLTAS,
        "max_cycles_default": remoteapp_FRONTEND_MAX_CYCLES,
        "estimated_minutes": remoteapp_SESSION_MINUTES_EST,
        "cycle_seconds_est": remoteapp_CYCLE_SECONDS_EST,
        "tags": ["theater", "remote_app", "frontend", "html", "css", "javascript", "gsap", "canvas", "svg"],
        "note_prefix": "[RemoteApp Frontend]",
    },
    "html-details-mastery": {
        "id": "html-details-mastery",
        "title": "HTML details/summary — maestria RemoteApp",
        "tracks": HTML_DETAILS_TRACKS,
        "voltas_default": HTML_DETAILS_VOLTAS,
        "max_cycles_default": HTML_DETAILS_MAX_CYCLES,
        "estimated_minutes": HTML_DETAILS_SESSION_MINUTES_EST,
        "cycle_seconds_est": HTML_DETAILS_CYCLE_SECONDS_EST,
        "tags": ["theater", "html", "details", "summary", "remote_app", "frontend", "a11y"],
        "note_prefix": "[HTML Details]",
    },
    "backend-mastery": {
        "id": "backend-mastery",
        "title": "Backend Mastery — Python, FastAPI, SQL, arquitetura staff",
        "tracks": BACKEND_MASTERY_TRACKS,
        "voltas_default": BACKEND_MASTERY_VOLTAS,
        "max_cycles_default": BACKEND_MASTERY_MAX_CYCLES,
        "estimated_minutes": BACKEND_SESSION_MINUTES_EST,
        "cycle_seconds_est": BACKEND_CYCLE_SECONDS_EST,
        "tags": ["theater", "backend", "python", "fastapi", "sql", "api", "security", "architecture"],
        "note_prefix": "[Backend Mastery]",
    },
    "reinforce-weak": {
        "id": "reinforce-weak",
        "title": "Reforço — áreas fracas (quiz Backend + Details)",
        "tracks": REINFORCE_WEAK_TRACKS,
        "voltas_default": REINFORCE_WEAK_VOLTAS,
        "max_cycles_default": REINFORCE_WEAK_MAX_CYCLES,
        "estimated_minutes": REINFORCE_WEAK_SESSION_MINUTES_EST,
        "cycle_seconds_est": REINFORCE_WEAK_CYCLE_SECONDS_EST,
        "tags": ["theater", "reforço", "quiz", "backend", "details", "weak-areas"],
        "note_prefix": "[Reforço]",
    },
    "ide-testing-mastery": {
        "id": "ide-testing-mastery",
        "title": "IDE Testing Mastery — pytest, Vitest, Playwright, provas",
        "tracks": IDE_TESTING_TRACKS,
        "voltas_default": IDE_TESTING_VOLTAS,
        "max_cycles_default": IDE_TESTING_MAX_CYCLES,
        "estimated_minutes": IDE_TESTING_SESSION_MINUTES_EST,
        "cycle_seconds_est": IDE_TESTING_CYCLE_SECONDS_EST,
        "tags": ["theater", "testing", "pytest", "vitest", "playwright", "e2e", "qa", "ravenna-ide"],
        "note_prefix": "[IDE Testing]",
    },
}


def get_curriculum(curriculum_id: str) -> dict[str, Any]:
    return CURRICULA.get(curriculum_id, CURRICULA["default"])


def volta_info(cycle: int, tracks_count: int) -> dict[str, int]:
    if cycle < 1:
        return {"volta": 0, "volta_cycle": 0}
    return {
        "volta": (cycle - 1) // tracks_count + 1,
        "volta_cycle": (cycle - 1) % tracks_count + 1,
    }
