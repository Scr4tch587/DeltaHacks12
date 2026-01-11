import os
import json
import httpx
from typing import Any

# Global configuration - Gemini API
DEFAULT_MODEL = "gemini-2.5-flash-lite"

def get_gemini_url(model: str) -> str:
    """Get the Gemini API URL for a given model."""
    return f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

async def get_field_value(
    field_label: str,
    field_context: str,
    user_profile: dict[str, Any],
    job_description: str
) -> str:
    """
    Ask Gemini AI to determine the value for a form field.

    Args:
        field_label: The label of the input field.
        field_context: Additional context like attributes, type, or dropdown options.
        user_profile: The user's data.
        job_description: The text of the job description.

    Returns:
        The string value to fill in, or empty string if it decides to skip/unknown.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Warning: GEMINI_API_KEY not found.")
        return ""

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    # Construct the prompt
    prompt = f"""
You are an AI assistant helping a user fill out a job application form autonomously.
Your goal is to provide the EXACT value to fill into a specific form field based on the user's profile and the job description.

CONTEXT:
- Field Label: "{field_label}"
- Field Context/Attributes: {field_context}
- Job Description (summary): {job_description[:2000]}... (truncated)
- User Profile: {json.dumps(user_profile, default=str)}

INSTRUCTIONS:
1. If the field is a standard personal info field (Name, Email, Phone, etc.), use the User Profile strictly.
2. If the field asks about experience, skills, or specific questions (e.g. "Why do you want this job?"), generate a reasonable, professional answer based on the User Profile and Job Description.
3. If the field is a Dropdown (Select), the Field Context will likely contain options. YOU MUST RETURN ONE OF THE OPTIONS EXACTLY. Choose the best match.
4. If the question is about race, gender, veteran status, or disability (EEO questions) and you are unsure, or if "Prefer not to answer" is an option, select "Prefer not to answer" or "Decline to identify".
5. If the question asks for a URL (LinkedIn, Portfolio), provide it from the profile if available.
6. If the question is a marketing question (e.g., "How did you hear about us?", "When did you learn about..."), provide a generic, plausible answer (e.g., "LinkedIn", "Through online research", "Recently") if the profile doesn't specify.
7. If you absolutely cannot determine a value, return "SKIP".
8. RETURN ONLY THE VALUE. Do not add quotes or explanation.

FIELD TO FILL: {field_label}
"""

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": api_key
    }

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
        }
    }

    try:
        url = get_gemini_url(model)
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30.0)

            if response.status_code != 200:
                print(f"Gemini API Error {response.status_code}: {response.text}")
                return ""

            data = response.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                candidate = data["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    answer = candidate["content"]["parts"][0]["text"].strip()
                    if answer == "SKIP":
                        return ""
                    return answer
            return ""

    except Exception as e:
        print(f"Error getting AI value for {field_label}: {e}")
        return ""