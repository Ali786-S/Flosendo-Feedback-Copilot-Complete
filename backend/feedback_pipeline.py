import json
import re
from backend.llm_client import _get_client, build_file_parts, get_model_name


def generate_feedback(submission_text: str, rubric: dict, attachments: list | None = None) -> dict:
    """
    Central feedback pipeline.
    Sends the submission plus any image/PDF attachments to Gemini and 
    returns structured rubric-aligned feedback.
    Falls back to a safe mock if the API key is missing or the call fails,
    so the rest of the app keeps working in dev.
    """
    criteria = rubric.get("criteria", [])
    rubric_title = rubric.get("title", "your rubric")

    client = _get_client()
    if client is None:
        return _mock_feedback(submission_text, criteria)

    try:
        import google.generativeai as genai
    except Exception as e:
        print(f"[feedback_pipeline] google-genai not importable: {e}")
        return _mock_feedback(submission_text, criteria)

    system_prompt = _build_system_prompt(rubric_title, criteria)

    # Build the contents list
    file_parts = build_file_parts(attachments or [])
    if file_parts:
        # File is the primary work — text is just the student's note/question
        contents = ["The following file(s) contain the student's submitted work. Mark the work in the file(s) against the rubric."]
        if submission_text:
            contents.append(f"Student's note: {submission_text}")
        contents.extend(file_parts)
    else:
        contents = [f"Student submission:\n{submission_text}"]

    try:
        model = client.GenerativeModel(get_model_name(), system_instruction=system_prompt)
        response = model.generate_content(
            contents,
            generation_config={
                "temperature": 0.3,
                }
             )
        raw = (response.text or "").strip()
        feedback = json.loads(raw)
    except Exception as e:
        print(f"[feedback_pipeline] Gemini call failed: {e}")
        error_str = str(e)
        if "429" in error_str or "quota" in error_str:
            m = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', error_str)
            retry_seconds = int(m.group(1)) if m else 999
            if retry_seconds > 60 or "perday" in error_str.replace(" ", "").lower():
                return {"overall_summary": "The AI service has reached its daily usage limit. Your work has been saved — please check back tomorrow for feedback.", "rubric_breakdown": [], "next_steps": []}
        return _mock_feedback(submission_text, criteria)

    # Minimal shape validation - downstream code expects these keys
    if not isinstance(feedback, dict):
        return _mock_feedback(submission_text, criteria)
    if "rubric_breakdown" not in feedback or not isinstance(feedback["rubric_breakdown"], list):
        return _mock_feedback(submission_text, criteria)
    feedback.setdefault("overall_summary", "")
    feedback.setdefault("next_steps", [])
    return feedback


def _build_system_prompt(rubric_title: str, criteria: list) -> str:
    # Build a single system instruction with full rubric context
    lines = []
    for c in criteria:
        name = c.get("name", "")
        desc = c.get("description", "")
        lines.append(f"- {name}: {desc}" if desc else f"- {name}")
    criteria_text = "\n".join(lines) if lines else "- (no criteria provided)"

    return f"""You are a supportive AI feedback copilot for Flosendo, an enrichment education platform. You are giving formative feedback to learners aged 12-17 on their own work.

Rubric: {rubric_title}
Criteria:
{criteria_text}

Rules for your feedback:
- Use plain English that a 12-17 year old can follow.
- Be encouraging and constructive, never harsh.
- For every criterion, give a score from 1 to 5, a short strengths sentence, a short improvement sentence, and a short piece of evidence taken directly from the student's submission.
- Finish with exactly three clear next steps the student can act on.
- If an attachment is included, treat its content as part of the student's submission when judging the rubric.
- If the student's work appears to be a different subject or type than the rubric suggests, say so clearly at the start of overall_summary and advise them to resubmit with the correct rubric selected.
- Never mention AI, language models, or prompts. Speak as a supportive teacher.

Return ONLY valid JSON in this exact shape (no markdown fences, no preamble):
{{
  "overall_summary": "string",
  "rubric_breakdown": [
    {{"criterion": "string", "score": 3, "strengths": "string", "improvements": "string", "evidence": "string"}}
  ],
  "next_steps": ["string", "string", "string"]
}}"""


def _mock_feedback(submission_text: str, criteria: list) -> dict:
    # Safe fallback so the app works with no key or during outages
    breakdown = []
    for c in criteria:
        name = c.get("name", "Criterion")
        breakdown.append({
            "criterion": name,
            "score": 3,
            "strengths": f"The work demonstrates some understanding of {name.lower()}.",
            "improvements": f"Consider expanding on ideas related to {name.lower()}.",
            "evidence": (submission_text[:120] + "...") if len(submission_text) > 120 else submission_text,
        })
    return {
        "overall_summary": "This is a solid draft that meets several rubric criteria. With more detail and refinement, it could be improved further.",
        "rubric_breakdown": breakdown,
        "next_steps": [
            "Review the rubric criteria and focus on one area to improve.",
            "Add more examples to support your ideas.",
            "Revise the structure for clarity.",
        ],
    }