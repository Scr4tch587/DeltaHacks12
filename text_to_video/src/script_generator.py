"""Script generation using OpenRouter LLM."""

import json
import re
from pathlib import Path
from typing import Dict

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_BASE_URL,
    DEFAULT_MODEL,
    get_topic_dirs,
    get_available_images,
)
from clients.openrouter_client import OpenRouterClient
from prompts.script_prompt_builder import ScriptPromptBuilder
from utils.cache import load_script_cache, save_script_cache


class ScriptGenerator:
    """Generates dialogue scripts using LLM."""

    def __init__(self, api_key: str = OPENROUTER_API_KEY, model: str = DEFAULT_MODEL):
        self.api_client = OpenRouterClient(
            api_key=api_key,
            base_url=OPENROUTER_BASE_URL,
            model=model
        )
        self.prompt_builder = ScriptPromptBuilder()

    def _get_cache_path(self, cache_key: str) -> Path:
        """Generate cache file path based on cache key (includes job description, character group, and template)."""
        topic_dirs = get_topic_dirs(cache_key)
        return topic_dirs['scripts'] / "script.json"

    def _load_from_cache(self, cache_key: str) -> Dict | None:
        """Load script from cache if it exists.
        
        Args:
            cache_key: Cache key (can be just job_description or full key with character_group|template)
        """
        cache_path = self._get_cache_path(cache_key)
        script = load_script_cache(cache_path)
        if script:
            return script
        
        # If not found with exact key, try to find any cached script
        # This handles the case where we're loading with just job_description but script was cached with full key
        from config import CACHE_DIR
        from pathlib import Path
        # Search for script.json files in cache directories
        cache_root = CACHE_DIR
        script_files = list(cache_root.glob("*/scripts/script.json"))
        # Try each one until we find a match (could be improved to match by job description content)
        for script_file in script_files:
            cached_script = load_script_cache(script_file)
            if cached_script and cached_script.get("topic", "").strip() == cache_key.strip():
                return cached_script
        
        return None

    def _save_to_cache(self, job_description: str, script: Dict):
        """Save script to cache."""
        cache_path = self._get_cache_path(job_description)
        save_script_cache(cache_path, script)

    def generate_script(self, job_description: str, force_regenerate: bool = False) -> Dict:
        """
        Generate a dialogue script between characters discussing a job description.

        Args:
            job_description: The job description text to discuss
            force_regenerate: If True, bypass cache and regenerate

        Returns:
            Dictionary with script structure:
            {
                "topic": str,
                "title": str,  # LLM-generated engaging title
                "lines": [
                    {
                        "character": "character_name",
                        "text": "Full text here (emotion) with emotion suggestions included. Second sentence here.",
                        "images": ["image1", "image2"]  // one image per sentence
                    },
                    ...
                ]
            }
        """
        # Generate new script
        # Since we randomly select characters/templates, we generate new scripts each time
        # unless force_regenerate is False AND a specific cached combination is requested
        print(f"Generating script for job description: {job_description[:100]}...")
        
        # Select character group and template BEFORE generating
        # This ensures each run gets a potentially different combination
        self.prompt_builder._select_random_group()
        self.prompt_builder._select_appropriate_template(job_description)
        
        selected_group = self.prompt_builder.get_selected_group()
        selected_template = self.prompt_builder._selected_template
        
        print(f"Selected: {selected_group['name']} with template '{selected_template['name']}'")
        
        # Create cache key that includes character group and template for uniqueness
        # This way each combination has its own cache, but random selection means different combos each run
        cache_key = f"{job_description}|{selected_group['name']}|{selected_template['name']}"
        
        # Check cache only if force_regenerate is False
        # Note: Since we randomly select, you'll likely get different combos each time anyway
        if not force_regenerate:
            cached_script = self._load_from_cache(cache_key)
            if cached_script:
                print(f"Loaded cached script for {selected_group['name']} with template '{selected_template['name']}'")
                return cached_script

        print(f"Generating new script with {selected_group['name']} and template '{selected_template['name']}'")

        prompt = self.prompt_builder.create_prompt(job_description)
        # Get character names for dynamic schema
        character_names = self.prompt_builder.get_selected_character_names()
        llm_response = self.api_client.generate_completion(prompt, character_names=character_names)

        # Parse and structure the response
        structured_script = self._parse_script(llm_response, job_description)
        
        # Store the cache key in the script for later reference (so audio files can use the same cache directory)
        structured_script["_cache_key"] = cache_key

        # Save to cache with the unique key
        self._save_to_cache(cache_key, structured_script)

        return structured_script

    def _validate_and_fix_images(self, script: Dict) -> Dict:
        """
        Validate that all image names exist. If an image doesn't exist, fall back to default or a valid alternative.
        Works dynamically with any characters based on the selected character group.

        Args:
            script: The parsed script dictionary

        Returns:
            Script with valid image names
        """
        # Get the selected character group to know which characters are in use
        selected_group = self.prompt_builder.get_selected_group()
        if not selected_group:
            # Fallback: use hardcoded characters if no group selected
            character_image_map = {
                "stewie": set(get_available_images("stewie")),
                "chris": set(get_available_images("chris"))
            }
        else:
            # Build dynamic character image map
            character_image_map = {}
            for char in selected_group['characters']:
                # Use the same method as prompt builder to get directory name
                char_dir_name = self.prompt_builder._get_character_directory_name(char['name'])
                available_images = get_available_images(char_dir_name)
                character_image_map[char_dir_name] = set(available_images)
                # Also map the character name as it appears in the script (might be different)
                # Script uses lowercase first word, so map that too
                script_char_name = char['name'].split()[0].lower()
                if script_char_name != char_dir_name:
                    character_image_map[script_char_name] = set(available_images)

        for line in script.get("lines", []):
            character = line.get("character", "").lower()
            # Get valid images for this character, or empty set if character not found
            valid_images = character_image_map.get(character, set())

            # Fix each image in the images array
            fixed_images = []
            for image in line.get("images", []):
                # "default" is always valid for any character
                if image == "default":
                    fixed_images.append("default")
                elif image in valid_images:
                    # Image is valid, keep it
                    fixed_images.append(image)
                else:
                    # Image doesn't exist, use default
                    print(f"Warning: Image '{image}' not found for {character}, using 'default'")
                    fixed_images.append("default")

            line["images"] = fixed_images

        return script

    def _parse_script(self, llm_response: str, job_description: str) -> Dict:
        """Parse LLM response into structured script format."""
        # Strip whitespace and remove markdown code block formatting if present
        llm_response = llm_response.strip()

        # Remove markdown code blocks (```json ... ```)
        if llm_response.startswith("```"):
            # Find the first newline after the opening ```
            start_idx = llm_response.find("\n")
            if start_idx != -1:
                llm_response = llm_response[start_idx + 1:]

        # Remove closing ``` if present
        if llm_response.endswith("```"):
            llm_response = llm_response[:-3]

        llm_response = llm_response.strip()

        try:
            parsed = json.loads(llm_response)
            
            # Use LLM-generated title (it should be in "Company - Position" format per prompt)
            llm_title = parsed.get("title", "Tech Job Opportunity")
            
            # Clean up the title: remove newlines and extra whitespace
            llm_title = llm_title.strip()
            llm_title = re.sub(r'\s+', ' ', llm_title)  # Replace all whitespace with single space
            llm_title = llm_title.replace('\n', ' ').replace('\r', ' ')
            
            script = {
                "topic": job_description,  # Keep "topic" key for backward compatibility
                "title": llm_title,  # LLM-generated title in "Company - Position" format
                "lines": parsed.get("lines", [])
            }

            # Validate that we have lines (schema should enforce this)
            if not script["lines"]:
                raise ValueError("No lines in script")

            # Validate and fix image names
            script = self._validate_and_fix_images(script)

            return script

        except json.JSONDecodeError as e:
            raise Exception(f"Failed to parse LLM response as JSON: {e}\nResponse: {llm_response}")


if __name__ == "__main__":
    # Test the script generator
    generator = ScriptGenerator()
    test_job_description = """
    Software Engineer - Full Stack
    Company: TechCorp
    Location: Remote
    Salary: $120k - $180k
    
    We're looking for a Full Stack Engineer to join our team. You'll work with React, Node.js, and Python.
    Requirements: 3+ years experience, React, Node.js, Python, AWS.
    Benefits: Health insurance, 401k, unlimited PTO, remote work.
    """
    script = generator.generate_script(test_job_description, force_regenerate=True)
    print(json.dumps(script, indent=2))
