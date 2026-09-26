#!/usr/bin/env python3
"""Interactive terminal chat with Rupsaa.

Usage:
    python scripts/chat.py
    python scripts/chat.py --no-adapter          # base model only, skip LoRA
    python scripts/chat.py --rag                 # enable RAG retrieval
    python scripts/chat.py --temperature 0.9 --top-p 0.95 --max-new-tokens 300

In-chat commands:
    /reset   clear conversation history
    /exit    quit (Ctrl+C also works cleanly)

Uses the exact same RupsaaEngine (rupsaa/model/inference.py) as the FastAPI
backend — this script is a thin CLI, not a separate model stack.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rupsaa.conversation.manager import ConversationManager  # noqa: E402
from rupsaa.model.inference import RupsaaEngine  # noqa: E402
from rupsaa.config import PROJECT_ROOT, get_settings  # noqa: E402
from rupsaa.conversation.language_control import directive_for  # noqa: E402
from rupsaa.rag.context_builder import build_turn_knowledge  # noqa: E402
from rupsaa.rag.dance import DanceStore  # noqa: E402
from rupsaa.rag.pipeline import RagPipeline  # noqa: E402
from rupsaa.rag.terminology import TerminologyStore  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-adapter", action="store_true", help="Serve the base model only, skip the LoRA adapter.")
    parser.add_argument("--adapter-path", default=None)
    parser.add_argument("--rag", action="store_true", help="Enable RAG retrieval over knowledge/documents/.")
    parser.add_argument("--system-prompt", default=None, help="Override the default Rupsaa system prompt entirely (advanced).")
    parser.add_argument("--temperature", type=float, default=None)
    parser.add_argument("--top-p", type=float, default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--max-new-tokens", type=int, default=None)
    parser.add_argument("--repetition-penalty", type=float, default=None)
    args = parser.parse_args()

    print("Loading Rupsaa... (first run downloads/quantizes the base model, this can take a while)")
    engine = RupsaaEngine.load(use_adapter=not args.no_adapter, adapter_path=args.adapter_path)
    print(f"Base model: {engine.loaded.base_model_id}")
    print(f"Adapter:    {engine.loaded.adapter_path or '(none — base model only)'}")

    rag_pipeline = RagPipeline() if args.rag else None
    if rag_pipeline:
        print(f"RAG enabled — index has {len(rag_pipeline.store)} chunk(s). Run scripts/ingest_knowledge.py to (re)build it.")

    manager = ConversationManager()
    conversation = manager.get_or_create(None)

    generation_overrides = {
        "temperature": args.temperature,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "max_new_tokens": args.max_new_tokens,
        "repetition_penalty": args.repetition_penalty,
    }

    print("\nRupsaa is ready. Type /reset to clear history, /exit to quit.\n")

    try:
        terminology = TerminologyStore(PROJECT_ROOT / get_settings().knowledge_terminology_dir)
        dance = DanceStore(PROJECT_ROOT / get_settings().knowledge_dance_dir)
        last_terms: list[str] | None = None
        language_state: dict | None = None
        while True:
            try:
                user_input = input("You: ").strip()
            except EOFError:
                break

            if not user_input:
                continue
            if user_input == "/exit":
                break
            if user_input == "/reset":
                manager.reset(conversation.conversation_id)
                conversation = manager.get_or_create(None)
                last_terms, language_state = None, None
                print("(conversation reset)\n")
                continue

            # Same routing/knowledge path as the API (rupsaa/rag/context_builder.py).
            knowledge = build_turn_knowledge(
                user_input,
                use_rag=rag_pipeline is not None,
                rag_query=(lambda q, strict=False: rag_pipeline.query(q, strict=strict)) if rag_pipeline else None,
                terminology=terminology,
                previous_terms=last_terms,
                history_messages=len(conversation.messages),
                history_truncated=conversation.dropped_messages > 0,
                history=conversation.messages,
                language_state=language_state,
                dance=dance,
            )
            language_state = knowledge.language_state
            if knowledge.sources:
                src_list = ", ".join(s["source_filename"] for s in knowledge.sources)
                print(f"  [retrieved from: {src_list}]")
            if knowledge.terms_used:
                print(f"  [terminology: {', '.join(knowledge.terms_used)}]")

            result = engine.chat(
                history=conversation.messages,
                user_message=user_input,
                retrieved_context=knowledge.retrieved_context,
                terminology_context=knowledge.terminology_context,
                conversation_note=knowledge.conversation_note,
                language_directive=directive_for(knowledge.language_state if knowledge.language else None),
                dance_context=knowledge.dance_context,
                generation_overrides=generation_overrides,
            )
            if knowledge.terms_used:
                last_terms = knowledge.terms_used
            elif knowledge.route not in ("followup", "memory"):
                last_terms = None

            print(f"\nRupsaa: {result.text}\n")

            if not result.blocked:
                manager.append_turn(conversation, user_input, result.text)
    except KeyboardInterrupt:
        print("\n(interrupted)")

    print("Bye! 💕")


if __name__ == "__main__":
    main()
