"""Fish.audio API client for text-to-speech generation following exact API format.

API Documentation: https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
"""

import aiohttp
from pathlib import Path
from typing import Optional, Dict, Any


class FishAudioClient:
    """Client for interacting with Fish.audio TTS API following exact API specification."""

    def __init__(self, api_key: str, url: str = "https://api.fish.audio/v1/tts", model: str = "s1"):
        """
        Initialize Fish Audio client.
        
        Args:
            api_key: Your Fish Audio API key (Bearer token)
            url: API endpoint URL (default: https://api.fish.audio/v1/tts)
            model: TTS model to use (default: s1)
        """
        self.api_key = api_key
        self.url = url
        self.model = model
        
        # Headers in exact order from API documentation
        self.headers = {
            "model": self.model,
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

    async def generate_audio(
        self,
        session: aiohttp.ClientSession,
        text: str,
        voice_id: str,
        output_path: Path,
        format: str = "mp3",
        temperature: float = 0.7,
        top_p: float = 0.7,
        chunk_length: int = 300,
        normalize: bool = True,
        latency: str = "normal",
        max_new_tokens: int = 1024,
        repetition_penalty: float = 1.2,
        min_chunk_length: int = 50,
        condition_on_previous_chunks: bool = True,
        early_stop_threshold: float = 1,
        **kwargs
    ) -> Path:
        """
        Generate speech audio for text using Fish.audio API.
        
        Follows exact format from API documentation.

        Args:
            session: aiohttp ClientSession for async requests
            text: Text to convert to speech (required)
            voice_id: Voice model ID (reference_id) for voice cloning
            output_path: Path where audio file should be saved
            format: Output audio format (default: mp3)
            temperature: Controls expressiveness 0-1 (default: 0.7)
            top_p: Controls diversity via nucleus sampling 0-1 (default: 0.7)
            chunk_length: Text segment size 100-300 (default: 300)
            normalize: Normalize text (default: True)
            latency: normal, balanced, low (default: normal)
            max_new_tokens: Maximum audio tokens (default: 1024)
            repetition_penalty: Penalty for repetition (default: 1.2)
            min_chunk_length: Minimum characters before splitting 0-100 (default: 50)
            condition_on_previous_chunks: Use previous audio as context (default: True)
            early_stop_threshold: Early stopping threshold 0-1 (default: 1)
            **kwargs: Additional optional parameters

        Returns:
            Path to the generated audio file

        Raises:
            Exception: If the API call fails
        """
        # Build payload following exact API format
        payload: Dict[str, Any] = {
            "text": text,
            "temperature": temperature,
            "top_p": top_p,
            "format": format,
            "normalize": normalize,
            "chunk_length": chunk_length,
            "latency": latency,
            "max_new_tokens": max_new_tokens,
            "repetition_penalty": repetition_penalty,
            "min_chunk_length": min_chunk_length,
            "condition_on_previous_chunks": condition_on_previous_chunks,
            "early_stop_threshold": early_stop_threshold,
            # Add prosody control for faster speech (1.3x speed)
            "prosody": {
                "speed": 1.3,  # 30% faster for 30-second video constraint
                "volume": 0    # Default volume
            }
        }
        
        # Add reference_id if provided (for voice cloning)
        if voice_id:
            payload["reference_id"] = voice_id
        
        # Add any additional optional parameters from kwargs
        optional_params = {
            'sample_rate', 'mp3_bitrate', 'opus_bitrate',
            'prosody', 'references'
        }
        for param in optional_params:
            if param in kwargs:
                payload[param] = kwargs[param]

        # Make request following exact API format
        async with session.post(self.url, json=payload, headers=self.headers) as response:
            if response.status == 200:
                # Success - save audio file
                audio_data = await response.read()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'wb') as f:
                    f.write(audio_data)
                return output_path
            elif response.status == 401:
                error_text = await response.text()
                raise Exception(f"Fish.audio API Authentication Error (401): {error_text}")
            elif response.status == 402:
                error_text = await response.text()
                raise Exception(
                    f"Fish.audio API Payment Error (402): {error_text}\n"
                    f"This usually means: Invalid API key or insufficient account balance.\n"
                    f"Please check your API key and account balance at https://fish.audio/app/api-keys/"
                )
            elif response.status == 422:
                error_text = await response.text()
                raise Exception(f"Fish.audio API Validation Error (422): {error_text}")
            else:
                error_text = await response.text()
                raise Exception(f"Fish.audio API Error ({response.status}): {error_text}")
