"""
Optional AI-generated writing feedback via the Anthropic API.

Requires an ANTHROPIC_API_KEY environment variable. If it isn't set, the
app still works fine -- the writing section just stores your submission
without a band estimate, and you can self/teacher-mark it instead.

Get a key at https://console.anthropic.com/
"""
import os
import json

_SYSTEM_PROMPT = """You are an experienced IELTS Writing examiner. Assess the
essay below against the four official IELTS Writing band descriptors:
Task Achievement/Response, Coherence and Cohesion, Lexical Resource, and
Grammatical Range and Accuracy. Give a band score (0-9, in 0.5 increments)
for each of the four criteria plus an overall band. Then give concise,
actionable feedback (max ~150 words) on the single biggest thing the writer
should improve.

This is indicative practice feedback, not an official score.

Respond ONLY with JSON in exactly this shape, no other text:
{
  "task_achievement": 6.5,
  "coherence_cohesion": 6.0,
  "lexical_resource": 6.5,
  "grammar_accuracy": 6.0,
  "overall_band": 6.5,
  "feedback": "..."
}
"""


def get_feedback(task_type, prompt_description, essay_text):
    """
    task_type: "task1" or "task2"
    prompt_description: short plain-text description of what was asked
                         (e.g. "Task 1: describe the bar chart" -- NOT the
                         full copyrighted prompt text, just enough context)
    essay_text: the user's own writing
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not set. Skipping AI feedback."}

    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic package not installed. Run: pip install anthropic"}

    client = anthropic.Anthropic(api_key=api_key)
    user_msg = f"{task_type.upper()} — {prompt_description}\n\nESSAY:\n{essay_text}"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=600,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = "".join(block.text for block in response.content if block.type == "text")
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Could not parse model response", "raw": raw}
