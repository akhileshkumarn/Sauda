"""ADK root agent, runner and a dedicated event-loop thread for agent turns (sync tools may block it
without stalling the FastAPI loop that streams SSE)."""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Callable

from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from ..deps import settings
from .prompts import OWNER_INSTRUCTION
from .tools import TOOLS

log = logging.getLogger("buyer_agent.agent")
APP_NAME = "sauda_buyer"
CONFIRM_FN = "adk_request_confirmation"

root_agent = Agent(
    name="sauda_buyer",
    model=settings().gemini_model,
    instruction=OWNER_INSTRUCTION,
    tools=TOOLS,
    generate_content_config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=2048),
)

session_service = InMemorySessionService()
runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)

_loop = asyncio.new_event_loop()
_thread = threading.Thread(target=_loop.run_forever, name="adk-loop", daemon=True)
_thread.start()


async def _ensure_session(user_id: str, session_id: str, state: dict) -> None:
    s = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if s is None:
        await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id, state=state)


async def _run(user_id: str, session_id: str, content: types.Content, state: dict, push: Callable[[dict], None],
               invocation_id: str | None = None) -> None:
    await _ensure_session(user_id, session_id, state)
    kwargs: dict[str, Any] = dict(user_id=user_id, session_id=session_id, new_message=content, state_delta=state)
    if invocation_id:
        kwargs["invocation_id"] = invocation_id
    async for ev in runner.run_async(**kwargs):
        push({"adk_event": ev})


def run_turn(user_id: str, session_id: str, text: str, state: dict, push: Callable[[dict], None]):
    """Submit an owner message; returns a concurrent.futures.Future."""
    content = types.Content(role="user", parts=[types.Part(text=text)])
    return asyncio.run_coroutine_threadsafe(_run(user_id, session_id, content, state, push), _loop)


def resume_confirmation(user_id: str, session_id: str, function_call_id: str, confirmed: bool, state: dict,
                        push: Callable[[dict], None], invocation_id: str | None = None):
    """SM-3 step 4/5: function response for adk_request_confirmation -> ADK replays place_order."""
    part = types.Part(function_response=types.FunctionResponse(id=function_call_id, name=CONFIRM_FN,
                                                                 response={"confirmed": confirmed}))
    content = types.Content(role="user", parts=[part])
    return asyncio.run_coroutine_threadsafe(_run(user_id, session_id, content, state, push, invocation_id), _loop)
