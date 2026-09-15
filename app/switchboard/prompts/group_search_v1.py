# switchboard/prompts/group_search_v1.py
#
# Prompt templates for the group_search Switchboard route.
# Inkwell returns JSON: {answer, found, used_chunk_indices}
# Spec: decisions/surfaces/clio-search-spec.md

SYSTEM_PROMPT = """\
You are answering a question about {group_name}'s shared knowledge.
You will be given retrieved excerpts from the group's content. Use only these excerpts to answer.

Guidelines:
- If the answer is clearly in the excerpts, answer directly and specifically.
  Name the source in your response when it helps (e.g. "The Summer Market event notes say the door code is 4821.").
- If the answer is not in the excerpts, respond with exactly:
  "I couldn't find that in {group_name}'s data."
- Never guess, infer, or use knowledge outside the provided excerpts.
- Keep the response to 1–4 sentences.
- Do not enumerate the sources in your response body — they will be shown separately.

Respond in JSON:
{{
  "answer": "<your response>",
  "found": <true|false>,
  "used_chunk_indices": [<0-based indices of the chunks your answer draws from>]
}}"""


def format_user_prompt(*, group_name: str, query: str, chunks: list[dict]) -> str:
    """Format the user-turn prompt from retrieved chunks.

    Each chunk dict must have: text (str), source_label (str).
    """
    lines = [f"Group: {group_name}", f"Query: {query}", "", f"Excerpts ({len(chunks)} retrieved):"]
    for i, chunk in enumerate(chunks):
        lines.append(f"[{i}] Source: {chunk['source_label']}")
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines)


def format_system_prompt(*, group_name: str) -> str:
    return SYSTEM_PROMPT.format(group_name=group_name)
