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
from rupsaa.rag.pipeline import RagPipeline  # noqa: E402

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
                print("(conversation reset)\n")
                continue

            retrieved_context = None
            if rag_pipeline:
                retrieved_context, sources = rag_pipeline.query(user_input)
                if sources:
                    src_list = ", ".join(s["source_filename"] for s in sources)
                    print(f"  [retrieved from: {src_list}]")

            result = engine.chat(
                history=conversation.messages,
                user_message=user_input,
                retrieved_context=retrieved_context,
                generation_overrides=generation_overrides,
            )

            print(f"\nRupsaa: {result.text}\n")

            if not result.blocked:
                manager.append_turn(conversation, user_input, result.text)
    except KeyboardInterrupt:
        print("\n(interrupted)")

    print("Bye! 💕")


if __name__ == "__main__":
    main()
