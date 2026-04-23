import json
import re
import time
from backend.llm_client import _get_client, build_file_parts, get_model_name


def generate_chat_reply(mode: str, message: str, context: dict | None = None) -> str:
    """
    Route chat requests through Gemini with retry + rate limit handling.
    Falls back to mock ONLY if all retries fail.
    """
    context = context or {}
    client = _get_client()

    if client is None:
        return "[ERROR] Gemini is not configured. Please check API key."

    system_prompt = _build_system_prompt(mode, context)

    # Build contents
    contents = [message]
    attachments = context.get("attachments") or []
    file_parts = build_file_parts(attachments)

    if file_parts:
        contents.append("The user has also attached the following file(s):")
        for part in file_parts:
            contents.append(part)

    # Create model
    model = client.GenerativeModel(get_model_name(), system_instruction=system_prompt)

    # Retry settings
    max_retries = 3
    base_delay = 2  # seconds

    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                contents,
                generation_config={
                    "temperature": 0.4,
                }
            )

            reply = (response.text or "").strip()

            if reply:
                return reply
            else:
                raise Exception("Empty response from Gemini")

        except Exception as e:
            error_str = str(e).lower()

            print("=== GEMINI ERROR ===")
            print(e)
            print("====================")

            # Handle rate limit (429)
            if "429" in error_str or "quota" in error_str:
                # Parse the retry_delay the API asks for
                m = re.search(r'retry_delay\s*\{\s*seconds:\s*(\d+)', str(e))
                retry_seconds = int(m.group(1)) if m else 0

                # Daily quota hit — retrying won't help, tell the user clearly
                if retry_seconds > 60 or "perday" in error_str.replace(" ", "").lower() or "per_day" in error_str.lower():
                    return "The AI service has reached its daily usage limit. Please try again tomorrow, or ask your teacher for help."

                wait_time = retry_seconds if retry_seconds > 0 else base_delay * (2 ** attempt)
                print(f"[chat_pipeline] Rate limited. Retrying in {wait_time}s...")

                if attempt < max_retries - 1:
                    time.sleep(wait_time)
                    continue
                else:
                    return "The AI service is busy right now. Please wait a minute and try again."

            # ❌ Non-rate-limit errors → don't retry too much
            if attempt < max_retries - 1:
                time.sleep(1)
                continue

            return f"[ERROR] Gemini failed: {str(e)}"

    # Final fallback (very rare now)
    return _mock_reply(mode, message, context)


def _build_system_prompt(mode: str, context: dict) -> str:
    if mode == "teacher":
        return (
            "You are a Teacher Copilot for Flosendo. "
            "Provide structured, practical teaching support. British English."
        )

    if mode == "feedback":
        rubric_title = context.get("rubric_title") or "the rubric"
        submission_text = (context.get("submission_text") or "").strip()
        feedback = context.get("feedback") or {}

        try:
            feedback_json = json.dumps(feedback, ensure_ascii=False)
        except Exception:
            feedback_json = "{}"

        return (
            f"You are helping a student improve their work using {rubric_title}. "
            f"Be clear, supportive, and specific.\n\n"
            f"Student's submission:\n{submission_text[:2000]}\n\n"
            f"Feedback:\n{feedback_json}"
        )

    return (
        "You are a helpful tutor for students aged 12–17. "
        "Give clear, simple, encouraging answers. British English."
    )


def _mock_reply(mode: str, message: str, context: dict) -> str:
    return "The AI service is temporarily unavailable. Please try again shortly."