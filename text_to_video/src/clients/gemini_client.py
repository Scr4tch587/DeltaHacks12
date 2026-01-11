"""Gemini API client for LLM completions."""

import requests
from typing import Dict


class GeminiClient:
    """Client for interacting with Google Gemini API."""

    def __init__(self, api_key: str, model: str = "gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://generativelanguage.googleapis.com/v1beta"

    def _create_response_schema(self, character_names: list[str] = None) -> Dict:
        """
        Create the JSON schema for structured LLM output.

        Args:
            character_names: List of character names (lowercase) to use in enum.
                           If None, defaults to ["stewie", "chris"] for backward compatibility.
        """
        if character_names is None:
            character_names = ["stewie", "chris"]

        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Engaging, catchy title for the video (keep concise, under 60 characters)"
                },
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "character": {
                                "type": "string",
                                "enum": character_names
                            },
                            "text": {
                                "type": "string",
                                "description": "Full text with emotion suggestions included in format (emotion) text here. Can have multiple sentences with different emotions."
                            },
                            "images": {
                                "type": "array",
                                "items": {
                                    "type": "string"
                                },
                                "description": "Array of image names, one per sentence in the text. Can repeat images."
                            }
                        },
                        "required": ["character", "text", "images"]
                    }
                }
            },
            "required": ["title", "lines"]
        }

    def generate_completion(self, prompt: str, character_names: list[str] = None) -> str:
        """
        Call the Gemini API with structured output.

        Args:
            prompt: The prompt to send to the LLM
            character_names: List of character names (lowercase) to use in schema enum.
                           If None, defaults to ["stewie", "chris"] for backward compatibility.

        Returns:
            The JSON response content as a string

        Raises:
            Exception: If the API call fails
        """
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key
        }

        response_schema = self._create_response_schema(character_names)

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": 10000,
                "temperature": 1.0,
                "responseMimeType": "application/json",
                "responseSchema": response_schema
            }
        }

        url = f"{self.base_url}/models/{self.model}:generateContent"
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

        result = response.json()

        if "candidates" not in result or len(result["candidates"]) == 0:
            raise Exception(f"No candidates in response: {result}")

        candidate = result["candidates"][0]
        if "content" not in candidate or "parts" not in candidate["content"]:
            raise Exception(f"Unexpected response structure: {result}")

        return candidate["content"]["parts"][0]["text"]
