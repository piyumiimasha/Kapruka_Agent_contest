def build_episode_summary_prompt(order_args: dict, conversation_history: list[dict]) -> str:
    history_text = "\n".join(
        f"{t['role'].capitalize()}: {t['content']}"
        for t in conversation_history[-10:]  # last 10 turns for context
    )

    return f"""You are summarizing a completed shopping session for long-term memory storage.
Write a single concise paragraph (2-4 sentences) summarizing what happened.
Include: what was ordered, who it was for, the city, the occasion if mentioned, and the approximate price if known.
Write in past tense. Be specific — use real product names and recipient names.

Order details:
{order_args}

Conversation context:
{history_text}

Write only the summary paragraph, nothing else."""