from pathlib import Path

from learning_agent.core import agent_spec_builder, ravenna_home_delivery


def test_blocks_react_router_in_app_write():
    spec = {"ravennaHome": True, "ravennaHomeDeploy": True, "ravennaHomeUiMode": "space-chat"}
    content = "import { BrowserRouter } from 'react-router-dom';\nexport default function App() { return null; }\n"
    reason = ravenna_home_delivery.should_block_write("src/App.tsx", content, spec=spec)
    assert reason is not None
    assert "router" in reason.lower()


def test_blocks_package_json_write():
    spec = {"ravennaHome": True}
    reason = ravenna_home_delivery.should_block_write("package.json", "{}", spec=spec)
    assert reason is not None


def test_space_chat_spec_from_prompt():
    spec = agent_spec_builder.build_spec("rh-08-space-chat full-screen neon espaco", project_root="ravenna-home/frontend")
    assert spec.get("ravennaHomeUiMode") == "space-chat"
    assert spec.get("enforceAllowedPaths") is True
    assert spec.get("ravennaHomeLockApp") is True
    assert "frontend/src/App.tsx" not in (spec.get("allowedPaths") or [])
    assert "frontend/src/components/Chat.tsx" in (spec.get("allowedPaths") or [])


def test_blocks_locked_app_write():
    spec = {"ravennaHome": True, "ravennaHomeLockApp": True, "ravennaHomeUiMode": "space-chat"}
    reason = ravenna_home_delivery.should_block_write("src/App.tsx", "export default function App(){}", spec=spec)
    assert reason is not None
    assert "bloqueado" in reason.lower()


def test_seed_space_chat_baseline_writes_valid_app(tmp_path: Path):
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "src" / "App.tsx").write_text("import { BrowserRouter } from 'react-router-dom';\n", encoding="utf-8")
    (tmp_path / "src" / "Layout.tsx").write_text("export default function Layout({ children }) { return children; }\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"name":"ravenna-home-frontend","private":true,"type":"module","scripts":{"build":"vite build"},"dependencies":{"react":"^18.3.1","react-dom":"^18.3.1"}}',
        encoding="utf-8",
    )
    written = ravenna_home_delivery.seed_space_chat_baseline(tmp_path)
    assert written
    failures = ravenna_home_delivery.validate_filesystem(
        tmp_path,
        spec={"ravennaHomeUiMode": "space-chat", "ravennaHomeLockApp": True},
    )
    assert not any("router" in f.lower() for f in failures)


def test_validate_filesystem_rejects_router_app(tmp_path: Path):
    src = tmp_path / "src" / "components"
    src.mkdir(parents=True)
    (tmp_path / "src" / "Layout.tsx").write_text("export default function Layout({ children }) { return children; }\n", encoding="utf-8")
    (tmp_path / "package.json").write_text(
        '{"name":"ravenna-home-frontend","private":true,"type":"module","scripts":{"build":"vite build"},"dependencies":{"react":"^18.3.1","react-dom":"^18.3.1"}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "App.tsx").write_text(
        "import { BrowserRouter } from 'react-router-dom';\nimport Chat from './components/Chat';\nexport default function App(){return <Chat/>}\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "components" / "Chat.tsx").write_text(
        "import { api } from '../api';\nexport function Chat(){ return api('/x'); }\n",
        encoding="utf-8",
    )
    failures = ravenna_home_delivery.validate_filesystem(
        tmp_path,
        spec={"ravennaHomeDeploy": True, "ravennaHomeUiMode": "space-chat"},
    )
    assert any("router" in f.lower() for f in failures)


def test_voice_pwa_spec_from_prompt():
    spec = agent_spec_builder.build_spec("rh-09-voice-pwa microfone instalar app", project_root="ravenna-home/frontend")
    assert spec.get("ravennaHomeUiMode") == "voice-pwa"
    assert spec.get("ravennaHomeLockApp") is True
    assert "InstallPrompt.tsx" in " ".join(spec.get("allowedPaths") or [])


def test_validate_voice_pwa_requires_stt_tts(tmp_path: Path):
    (tmp_path / "src" / "components").mkdir(parents=True)
    (tmp_path / "public").mkdir(parents=True)
    (tmp_path / "src" / "App.tsx").write_text("export default function App(){return null}\n", encoding="utf-8")
    (tmp_path / "src" / "Layout.tsx").write_text("export default function Layout({c}){return c}\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"ravenna-home-frontend"}', encoding="utf-8")
    (tmp_path / "src" / "components" / "Chat.tsx").write_text(
        "export function Chat(){ return null; }\n",
        encoding="utf-8",
    )
    (tmp_path / "public" / "manifest.webmanifest").write_text(
        '{"name":"R","display":"standalone","icons":[{"src":"/icon-192.png","sizes":"192x192"}]}',
        encoding="utf-8",
    )
    failures = ravenna_home_delivery.validate_filesystem(
        tmp_path,
        spec={"ravennaHomeUiMode": "voice-pwa"},
    )
    assert any("stt" in f.lower() or "microfone" in f.lower() or "speech" in f.lower() for f in failures)
    assert any("tts" in f.lower() or "speechsynthesis" in f.lower() for f in failures)


def test_cursor_acceptance_requires_no_failures():
    summary = ravenna_home_delivery.cursor_acceptance_summary(
        autonomy_passed=True,
        fs_failures=["App.tsx sem abas"],
        prod_failures=[],
    )
    assert summary["approved"] is False
    assert summary["verdict"] == "REPROVADO"


def test_validate_production_css_rejects_stub():
    failures = ravenna_home_delivery.validate_production_css_body(
        ".space-bg{background:url(path/to/x.png)}",
        asset_name="index-stub.css",
    )
    assert any("stub" in f.lower() or "245" in f or "bytes" in f for f in failures)


def test_validate_production_visual_detects_tiny_bundle():
    html = '<html><link rel="stylesheet" href="/assets/index-abc.css"></html>'
    failures = ravenna_home_delivery.validate_production_visual(
        html,
        css_body=".x{color:red}",
    )
    assert any("stub" in f.lower() or "bytes" in f for f in failures)


def test_run_visual_vistoria_structure(tmp_path: Path, monkeypatch):
    (tmp_path / "src" / "components").mkdir(parents=True)
    (tmp_path / "src" / "Layout.tsx").write_text(
        "export default function Layout({ children }) { return children; }\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(
        '{"name":"ravenna-home-frontend","private":true,"type":"module","scripts":{"build":"vite build"},'
        '"dependencies":{"react":"^18.3.1","react-dom":"^18.3.1"}}',
        encoding="utf-8",
    )
    (tmp_path / "src" / "App.tsx").write_text(
        "import { useState } from 'react';\nimport Layout from './Layout';\n"
        "import { Chat } from './components/Chat';\n"
        "export default function App(){const [t,s]=useState('Chat');"
        "return <Layout><nav className='tab-bar'><button>Chat</button><button>Casa</button></nav>"
        "{t==='Chat'&&<Chat/>}</Layout>;}\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "components" / "Chat.tsx").write_text(
        "import { api } from '../api';\nexport function Chat(){ return <div className='chat-fullscreen' style={{height:'100dvh'}}/>; }\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "index.css").write_text(
        ".tab-bar{display:flex}.neon-glow{box-shadow:0 0 8px #a78bfa}"
        + ".chat-fullscreen{min-height:100dvh}" * 20,
        encoding="utf-8",
    )

    class FakeResp:
        text = '<link rel="stylesheet" href="/assets/index-x.css"><script src="/assets/index-x.js"></script>'

    monkeypatch.setattr(
        "httpx.get",
        lambda *a, **k: FakeResp(),
    )
    monkeypatch.setattr(
        ravenna_home_delivery,
        "fetch_production_css_body",
        lambda *a, **k: (".tab-bar{}", {"css": "index-x.css"}),
    )
    audit = ravenna_home_delivery.run_visual_vistoria(
        tmp_path,
        spec={"ravennaHomeUiMode": "voice-pwa"},
        home_url="http://test:5174",
    )
    assert "verdict" in audit
    assert "checks" in audit
    assert audit.get("root_cause")
