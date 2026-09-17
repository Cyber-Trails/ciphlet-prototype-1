"""Ciphlet application entry point.

Start command (once dependencies are installed, on the Pi):

    ciphlet chat                  # text conversation (free chain: Groq -> Gemini -> OpenRouter free -> local Ollama)
                                   # resumes the last conversation by default (cross-restart continuity, §5.2)
    ciphlet chat --new-session     # start a fresh conversation instead of resuming the last one
    ciphlet chat --local-only     # text conversation, local Ollama only, no network AI calls at all
    ciphlet chat --premium        # text conversation using Claude instead (opt-in, metered)
    ciphlet chat --no-memory      # text, nothing persisted, always a fresh scratch session (§5.3)
    ciphlet voice --ptt           # push-to-talk voice (fallback/recovery, §4.1)
    ciphlet voice --hands-free    # wake-word voice loop (primary interaction, §4.1)

or equivalently: `python -m ciphlet <chat|voice> ...`

Every reply also prints which provider/model actually served it (from
Orchestrator.last_brain — see orchestrator.py, brain/router.py
last_served), so that's observable in normal use without a debugger.
"""

from __future__ import annotations

import argparse
import sys

from ciphlet.brain import (
    BrainMode,
    BrainRouter,
    ClaudeBrainProvider,
    GeminiBrainProvider,
    GroqBrainProvider,
    OllamaBrainProvider,
    OpenRouterBrainProvider,
)
from ciphlet.config import Config
from ciphlet.embodiment.state import EmbodimentSink
from ciphlet.memory.store import MemoryStore
from ciphlet.orchestrator import Orchestrator
from ciphlet.session import Session
from ciphlet.voice.base import VoiceUnavailableError


def _resolve_session(memory: MemoryStore, *, no_memory: bool, new_session: bool, brain_mode: BrainMode) -> Session:
    """Cross-restart conversation continuity (§5.2), using the existing
    sessions/messages tables as-is: by default, resume the most recently
    started persisted session instead of always starting a blank one, so a
    fresh `ciphlet chat` invocation continues where the last one left off.
    --new-session or --no-memory opt out and start a scratch session."""
    if no_memory or new_session:
        return Session(no_memory=no_memory, brain_mode=brain_mode)

    resumed_id = memory.latest_session_id()
    if resumed_id:
        return Session(id=resumed_id, no_memory=False, brain_mode=brain_mode, resumed=True)

    return Session(no_memory=False, brain_mode=brain_mode)  # first run: nothing to resume yet


def _build_orchestrator(
    config: Config,
    *,
    no_memory: bool,
    premium: bool = False,
    local_only: bool = False,
    new_session: bool = False,
) -> Orchestrator:
    local = OllamaBrainProvider(
        host=config.ollama_host,
        model=config.ollama_model,
        timeout_s=config.ollama_timeout_s,
        num_ctx=config.ollama_num_ctx,
        num_predict=config.ollama_num_predict,
        history_messages=config.ollama_history_messages,
    )

    # Claude is only ever constructed/called when --premium is explicitly
    # passed. It replaces the whole AUTO route for this session — it is
    # never part of the free chain and never invoked automatically.
    if premium:
        brain = ClaudeBrainProvider(api_key=config.anthropic_api_key, model=config.premium_brain_model)
    else:
        free_chain = [
            GroqBrainProvider(api_key=config.groq_api_key, model=config.groq_model),
            GeminiBrainProvider(api_key=config.gemini_api_key, model=config.gemini_model),
            OpenRouterBrainProvider(api_key=config.openrouter_api_key, model=config.openrouter_model),
        ]
        brain = BrainRouter(free_chain=free_chain, local=local)

    memory = MemoryStore(config.db_path)
    brain_mode = BrainMode.LOCAL_ONLY if local_only else BrainMode.AUTO
    session = _resolve_session(memory, no_memory=no_memory, new_session=new_session, brain_mode=brain_mode)
    return Orchestrator(
        brain=brain,
        local_brain=local,
        memory=memory,
        session=session,
        embodiment=EmbodimentSink(),
    )


def run_chat(args: argparse.Namespace) -> None:
    config = Config.load()
    orchestrator = _build_orchestrator(
        config,
        no_memory=args.no_memory,
        premium=args.premium,
        local_only=args.local_only,
        new_session=args.new_session,
    )

    print("Ciphlet (text mode). Type 'exit' or Ctrl+D to quit.")
    print(f"(memory db: {config.db_path})")
    if not args.no_memory:
        if orchestrator.session.resumed:
            print(f"(resuming previous conversation — {orchestrator.history_count()} prior message(s))")
        else:
            print("(new session)")
    if args.local_only:
        print("(local-only mode: local Ollama only, no network AI calls)")
    if args.premium:
        print("(premium mode: using Claude — this will incur API cost)")
    if args.no_memory:
        print("(no-memory mode: this conversation will not be saved)")

    while True:
        try:
            user_text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_text:
            continue
        if user_text.lower() in {"exit", "quit"}:
            break

        # Stream output as it's generated when the active provider supports
        # it (currently Ollama) — user sees text appear incrementally
        # instead of waiting for the full reply. Providers that don't
        # stream never call this, so `streamed` stays False and the full
        # reply is printed normally afterward — no behavior change for them.
        streamed = False

        def _print_chunk(chunk: str) -> None:
            nonlocal streamed
            if not streamed:
                print("Ciphlet: ", end="", flush=True)
                streamed = True
            print(chunk, end="", flush=True)

        reply = orchestrator.handle_text(user_text, on_token=_print_chunk)
        if streamed:
            print()  # close the streamed line
        else:
            print(f"Ciphlet: {reply}")
        if orchestrator.last_brain:
            info = f"[brain] {orchestrator.last_brain} — {orchestrator.last_context_size} message(s) in context"
            if orchestrator.last_timing:
                info += f" — {orchestrator.last_timing}"
            print(info)


def run_voice(args: argparse.Namespace) -> None:
    config = Config.load()
    orchestrator = _build_orchestrator(
        config,
        no_memory=args.no_memory,
        premium=args.premium,
        local_only=args.local_only,
        new_session=args.new_session,
    )

    from ciphlet.voice.pipeline import HandsFreeVoiceSession, PTTVoiceSession
    from ciphlet.voice.providers import OpenWakeWordProvider, PiperTTS, VoskSTT, WebRTCVadAudioProcessor

    if not config.piper_model_path:
        print(
            "CIPHLET_PIPER_MODEL is not set — voice needs a Piper voice model path. "
            "Falling back to text mode.",
            file=sys.stderr,
        )
        return run_chat(args)
    if not config.vosk_model_path:
        print(
            "CIPHLET_VOSK_MODEL_PATH is not set — voice needs a VOSK model directory. "
            "Falling back to text mode.",
            file=sys.stderr,
        )
        return run_chat(args)

    stt = VoskSTT(model_path=config.vosk_model_path)
    tts = PiperTTS(model_path=config.piper_model_path, output_device=config.audio_output_device)

    def _print_brain_info(_reply: str) -> None:
        if orchestrator.last_brain:
            info = f"[brain] {orchestrator.last_brain} — {orchestrator.last_context_size} message(s) in context"
            if orchestrator.last_timing:
                info += f" — {orchestrator.last_timing}"
            print(info)

    try:
        if args.hands_free:
            audio = WebRTCVadAudioProcessor()
            wake = OpenWakeWordProvider(model_path=config.wake_model_path)
            session = HandsFreeVoiceSession(
                audio,
                wake,
                stt,
                tts,
                orchestrator.handle_text,
                input_device=config.audio_input_device,
                on_reply=_print_brain_info,
            )
            session.run_forever()
        else:
            session = PTTVoiceSession(stt, tts, orchestrator.handle_text, input_device=config.audio_input_device)
            while True:
                session.run_turn()
                _print_brain_info("")
    except VoiceUnavailableError as exc:
        print(f"Voice unavailable ({exc}). Falling back to text mode.", file=sys.stderr)
        run_chat(args)
    except KeyboardInterrupt:
        print()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ciphlet", description="Ciphlet — cybersecurity learning companion")
    sub = parser.add_subparsers(dest="command")

    chat_parser = sub.add_parser("chat", help="Text conversation (default)")
    chat_parser.add_argument("--no-memory", action="store_true", help="Don't persist this conversation (§5.3)")
    chat_parser.add_argument(
        "--new-session",
        action="store_true",
        help="Start a fresh conversation instead of resuming the last one (§5.2)",
    )
    chat_brain_mode = chat_parser.add_mutually_exclusive_group()
    chat_brain_mode.add_argument(
        "--premium",
        action="store_true",
        help="Use Claude instead of the free chain (metered, opt-in; never automatic)",
    )
    chat_brain_mode.add_argument(
        "--local-only",
        action="store_true",
        help="Bypass every cloud provider; local Ollama only, no network AI calls",
    )
    chat_parser.set_defaults(func=run_chat)

    voice_parser = sub.add_parser("voice", help="Voice conversation")
    voice_parser.add_argument("--no-memory", action="store_true")
    voice_parser.add_argument(
        "--new-session",
        action="store_true",
        help="Start a fresh conversation instead of resuming the last one (§5.2)",
    )
    voice_brain_mode = voice_parser.add_mutually_exclusive_group()
    voice_brain_mode.add_argument(
        "--premium",
        action="store_true",
        help="Use Claude instead of the free chain (metered, opt-in; never automatic)",
    )
    voice_brain_mode.add_argument(
        "--local-only",
        action="store_true",
        help="Bypass every cloud provider; local Ollama only, no network AI calls",
    )
    mode = voice_parser.add_mutually_exclusive_group()
    mode.add_argument("--ptt", action="store_true", help="Push-to-talk (fallback/recovery, §4.1) [default]")
    mode.add_argument("--hands-free", action="store_true", help="Wake-word loop (primary interaction, §4.1)")
    voice_parser.set_defaults(func=run_voice)

    return parser


def cli() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        args = parser.parse_args(["chat"])
    args.func(args)


if __name__ == "__main__":
    cli()
