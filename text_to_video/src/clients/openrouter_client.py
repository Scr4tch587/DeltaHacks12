"""OpenRouter API client for LLM completions."""

import requests
from typing import Dict


class OpenRouterClient:
    """Client for interacting with OpenRouter API."""

    def __init__(self, api_key: str, base_url: str = "https://openrouter.ai/api/v1", model: str = "anthropic/claude-sonnet-4.5"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

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
                        "required": ["character", "text", "images"],
                        "additionalProperties": False
                    }
                }
            },
            "required": ["title", "lines"],
            "additionalProperties": False
        }

    def generate_completion(self, prompt: str, character_names: list[str] = None) -> str:
        """
        Call the OpenRouter API with structured output.
        
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
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        response_schema = self._create_response_schema(character_names)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 10000,  # Limit tokens for short scripts (150-200 words)
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "strict": True,
                    "schema": response_schema
                }
            }
        }

        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload
        )

        if response.status_code != 200:
            raise Exception(f"API Error: {response.status_code} - {response.text}")

        result = response.json()
        return result["choices"][0]["message"]["content"]

