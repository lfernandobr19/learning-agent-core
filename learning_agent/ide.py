"""WebSocket handler para Ravenna IDE"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Set
from fastapi import WebSocket, WebSocketDisconnect
from learning_agent.core import chat, knowledge, graph
from learning_agent.identity import AGENT_NAME

class RavennaIDE:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients"""
        dead_connections = set()
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"Error broadcasting: {e}")
                dead_connections.add(connection)

        self.active_connections -= dead_connections

    async def broadcast_file_changed(self, path: str, *, action: str = "changed") -> None:
        """Notifica clientes IDE — explorer refresh (paridade VS Code watcher)."""
        await self.broadcast({
            "type": "file_changed",
            "payload": {"path": path.replace("\\", "/"), "action": action},
        })

    async def broadcast_theater(self, payload: dict):
        """Broadcast observador / multi-agent message to IDE clients."""
        await self.broadcast({"type": "theater", "payload": payload})
        await self.broadcast({
            "type": "state",
            "payload": {
                "active": True,
                "processingLevel": 0.9 if payload.get("role") != "ravenna" else 0.3,
                "concepts": [],
                "recentMessage": payload.get("content", "")[:120],
            },
        })

    async def broadcast_tool_call(
        self,
        name: str,
        *,
        status: str = "running",
        detail: str = "",
        result: str = "",
        source: str = "api",
    ) -> None:
        """Tool call visível na IDE (paridade Cursor agent steps)."""
        await self.broadcast({
            "type": "tool_call",
            "payload": {
                "id": f"tool-{uuid.uuid4().hex[:10]}",
                "name": name,
                "status": status,
                "detail": detail[:500],
                "result": result[:800],
                "source": source,
                "timestamp": datetime.now().isoformat(),
            },
        })

    async def handle_connection(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        
        # Send initial state
        await websocket.send_json({
            "type": "state",
            "payload": {
                "active": True,
                "processingLevel": 0,
                "concepts": [],
            }
        })
        
        try:
            while True:
                data = await websocket.receive_json()
                
                if data.get("type") == "message":
                    await self._handle_message(
                        websocket,
                        data["content"],
                        data.get("context") or "",
                        data.get("mode") or "chat",
                        data.get("agent") or "",
                        bool(data.get("auto_delegate")),
                        data.get("model_size") or "auto",
                        data.get("conversation_id") or "",
                    )
        except WebSocketDisconnect:
            self.active_connections.discard(websocket)
            print(f"Client disconnected. Active: {len(self.active_connections)}")

    async def _handle_message(
        self,
        websocket: WebSocket,
        content: str,
        context: str = "",
        mode: str = "chat",
        agent: str = "",
        auto_delegate: bool = False,
        model_size: str = "auto",
        conversation_id: str = "",
    ):
        """Chat com streaming token a token via WebSocket."""
        from learning_agent.core import agent_delegate
        from learning_agent.core.chat import suggest_model_size, resolve_conversation_id

        task_mode = mode if mode in {"chat", "agent", "fast"} else "chat"
        delegate = agent.strip() or None
        if not delegate and auto_delegate:
            routed = agent_delegate.suggest_delegate(content, context or "")
            delegate = routed.get("agent") or None
            if delegate:
                await websocket.send_json({
                    "type": "tool_call",
                    "payload": {
                        "name": "Delegate",
                        "status": "done",
                        "detail": routed.get("display_name") or delegate,
                        "result": routed.get("reason", ""),
                        "source": "auto",
                    },
                })
        elif delegate:
            await websocket.send_json({
                "type": "tool_call",
                "payload": {
                    "name": "Delegate",
                    "status": "done",
                    "detail": delegate,
                    "result": "delegação manual",
                    "source": "manual",
                },
            })
        conv_id = resolve_conversation_id(conversation_id or None, channel="ide")

        msg_id = f"msg-{uuid.uuid4().hex[:10]}"
        try:
            if (model_size or "auto").strip().lower() == "auto":
                resolved_size, size_reasons = suggest_model_size(
                    content,
                    task_mode=task_mode,
                    editor_context=context or "",
                    delegate_agent=delegate,
                )
                await websocket.send_json({
                    "type": "tool_call",
                    "payload": {
                        "name": "Modelo",
                        "status": "done",
                        "detail": f"{resolved_size} (auto)",
                        "result": ", ".join(size_reasons),
                        "source": "auto",
                    },
                })
            await websocket.send_json({
                "type": "state",
                "payload": {
                    "active": True,
                    "processingLevel": 0.8,
                    "concepts": [],
                    "recentMessage": content,
                },
            })
            await websocket.send_json({
                "type": "chat_start",
                "payload": {"id": msg_id, "role": "ravenna"},
            })

            loop = asyncio.get_event_loop()
            iterator = await loop.run_in_executor(
                None,
                lambda: chat.iter_reply_deltas(
                    content,
                    channel="ide",
                    user_id=conv_id,
                    include_context=True,
                    editor_context=context or "",
                    task_mode=task_mode,
                    delegate_agent=delegate,
                    model_size=model_size,
                ),
            )

            final: dict[str, Any] | None = None
            while True:
                item, done = await loop.run_in_executor(None, _next_or_stop, iterator)
                if done:
                    break
                if isinstance(item, dict):
                    final = item
                    break
                await websocket.send_json({
                    "type": "chat_delta",
                    "payload": {"id": msg_id, "delta": item},
                })

            if final and final.get("error"):
                await websocket.send_json({
                    "type": "message",
                    "payload": {
                        "id": msg_id,
                        "role": "ravenna",
                        "content": f"Erro: {final['error']}",
                        "reasoning": final.get("hint", ""),
                        "timestamp": datetime.now().isoformat(),
                    },
                })
            else:
                reply = (final or {}).get("reply", "")
                model = (final or {}).get("model", "unknown")
                agent = (final or {}).get("agent", AGENT_NAME)
                size = (final or {}).get("model_size", "")
                size_reasons = (final or {}).get("model_size_reasons") or []
                reasoning = f"Modelo: {model}"
                if size:
                    reasoning += f" · {size}"
                if size_reasons:
                    reasoning += f" ({', '.join(size_reasons)})"
                await websocket.send_json({
                    "type": "message",
                    "payload": {
                        "id": msg_id,
                        "role": "ravenna",
                        "agent": agent,
                        "content": reply,
                        "reasoning": reasoning,
                        "conversation_id": conv_id,
                        "timestamp": datetime.now().isoformat(),
                    },
                })

            await websocket.send_json({
                "type": "state",
                "payload": {
                    "active": True,
                    "processingLevel": 0,
                    "concepts": [],
                },
            })

        except Exception as e:
            print(f"Error handling message: {e}")
            await websocket.send_json({
                "type": "message",
                "payload": {
                    "id": msg_id,
                    "role": "ravenna",
                    "content": f"Erro ao processar: {str(e)}",
                    "timestamp": datetime.now().isoformat(),
                },
            })
            await websocket.send_json({
                "type": "state",
                "payload": {"active": True, "processingLevel": 0, "concepts": []},
            })

    async def _get_response(self, message: str, context: str = "") -> dict:
        """Fallback sync (sem stream) — testes e compat."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self._sync_get_response,
            message,
            context,
        )

    def _sync_get_response(self, message: str, context: str = "") -> dict:
        """Synchronous chat call"""
        try:
            result = chat.reply(
                message,
                channel="ide",
                user_id="ide-user",
                include_context=True,
                editor_context=context or "",
            )

            if not result.get("success"):
                return {
                    "message": f"Erro: {result.get('error', 'Desconhecido')}",
                    "reasoning": result.get("hint", ""),
                }

            return {
                "id": f"response-{id(result)}",
                "message": result.get("reply", ""),
                "reasoning": f"Modelo: {result.get('model', 'unknown')}",
                "concepts": [],
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            print(f"Error in sync_get_response: {e}")
            return {
                "message": "Desculpa, algo deu errado internamente.",
                "reasoning": str(e),
                "timestamp": datetime.now().isoformat(),
            }

    async def _extract_concepts(self, concept_ids: list) -> list:
        """Extract concept details from IDs"""
        try:
            concepts = []
            for concept_id in concept_ids[:5]:  # Limit to 5
                concept = graph.get_concept(concept_id)
                if concept:
                    concepts.append({
                        "id": concept_id,
                        "name": concept.get("name", "Unknown"),
                        "tags": concept.get("tags", []),
                        "connections": concept.get("connections", [])[:5],
                    })
            return concepts
        except Exception as e:
            print(f"Error extracting concepts: {e}")
            return []


# Global instance
ravenna_ide = RavennaIDE()


def _next_or_stop(iterator):
    try:
        return next(iterator), False
    except StopIteration:
        return None, True
