"""Prompt building for script generation."""

import json
import random
from pathlib import Path
from config import (
    get_available_images,
    AVAILABLE_EMOTIONS
)


class ScriptPromptBuilder:
    """Builds prompts for script generation."""

    def __init__(self):
        # Load character dynamics from JSON
        self._char_dynamics_path = Path(__file__).parent / "char_dynamics.json"
        self._char_groups = None
        self._selected_group = None
        self._load_character_dynamics()
        
        # Load conversation templates from JSON
        self._templates_path = Path(__file__).parent / "conversation_templates.json"
        self._templates = None
        self._selected_template = None
        self._load_conversation_templates()
        
        # Note: Random group and template selection happens on each request in create_prompt()
    
    def _load_character_dynamics(self):
        """Load character dynamics from JSON file."""
        try:
            with open(self._char_dynamics_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._char_groups = data.get('groups', [])
        except FileNotFoundError:
            raise FileNotFoundError(f"Character dynamics file not found: {self._char_dynamics_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in character dynamics file: {e}")
    
    def _load_conversation_templates(self):
        """Load conversation templates from JSON file."""
        try:
            with open(self._templates_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self._templates = data.get('templates', [])
        except FileNotFoundError:
            raise FileNotFoundError(f"Conversation templates file not found: {self._templates_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in conversation templates file: {e}")
    
    def _select_random_group(self):
        """Randomly select a character group from available groups."""
        if not self._char_groups:
            raise ValueError("No character groups available")
        self._selected_group = random.choice(self._char_groups)
    
    def _select_appropriate_template(self, job_description: str):
        """Select the most appropriate conversation template based on job description content."""
        if not self._templates:
            raise ValueError("No conversation templates available")
        
        job_lower = job_description.lower()
        
        # Score each template based on job description content
        template_scores = {}
        
        for template in self._templates:
            score = 0
            template_name = template['name'].lower()
            template_desc = template['description'].lower()
            
            # The Bag Alert - High salary or great benefits
            if template_name == "the bag alert":
                if any(keyword in job_lower for keyword in ['$', 'salary', 'compensation', '180', '200', '250', '300', 'high', 'competitive']):
                    score += 10
                if any(keyword in job_lower for keyword in ['benefits', 'insurance', '401k', 'pto', 'unlimited']):
                    score += 5
            
            # The Bed Rotter - Remote work focus
            elif template_name == "the bed rotter":
                if any(keyword in job_lower for keyword in ['remote', 'work from home', 'wfh', 'fully remote', 'anywhere', 'digital nomad']):
                    score += 15
                if any(keyword in job_lower for keyword in ['flexible', 'timezone', 'async']):
                    score += 5
            
            # The Moonshot - Startup/Equity focus
            elif template_name == "the moonshot":
                if any(keyword in job_lower for keyword in ['startup', 'equity', 'stock options', 'pre-series', 'series a', 'series b', 'ai startup', 'fintech', 'crypto']):
                    score += 15
                if any(keyword in job_lower for keyword in ['equity', 'stock', 'options', 'shares']):
                    score += 10
            
            # The Rocket Ship - Early-stage startup
            elif template_name == "the rocket ship":
                if any(keyword in job_lower for keyword in ['startup', 'early-stage', 'fast-growing', 'scaling', 'rapidly', 'pre-series']):
                    score += 12
                if any(keyword in job_lower for keyword in ['equity', 'stock options']):
                    score += 8
            
            # The Baby Gronk - Internship/Junior role
            elif template_name == "the baby gronk":
                if any(keyword in job_lower for keyword in ['intern', 'internship', 'junior', 'entry-level', 'new grad', 'no experience', 'recent graduate']):
                    score += 15
                if any(keyword in job_lower for keyword in ['mentorship', 'training', 'learn', 'growth']):
                    score += 8
            
            # The Golden Handcuffs - Big Tech / Corporate
            elif template_name == "the golden handcuffs":
                if any(keyword in job_lower for keyword in ['google', 'microsoft', 'amazon', 'meta', 'apple', 'netflix', 'corporate', 'fortune 500', 'enterprise']):
                    score += 15
                if any(keyword in job_lower for keyword in ['benefits', 'perks', 'stability', 'work-life balance']):
                    score += 8
            
            # The Code Necromancer - Legacy/Niche firms
            elif template_name == "the code necromancer":
                if any(keyword in job_lower for keyword in ['java', 'c++', '.net', 'cobol', 'legacy', 'bank', 'healthcare', 'logistics', 'financial services']):
                    score += 12
                if any(keyword in job_lower for keyword in ['security', 'stability', 'established', 'long-term']):
                    score += 8
            
            # The Skill Check - Very hard and competitive
            elif template_name == "the skill check":
                if any(keyword in job_lower for keyword in ['senior', 'lead', 'principal', 'architect', 'expert', 'advanced', '5+ years', '7+ years', '10+ years']):
                    score += 10
                if any(keyword in job_lower for keyword in ['competitive', 'challenging', 'complex', 'difficult']):
                    score += 8
            
            # The Hype Hook - Default/prestigious companies
            elif template_name == "the hype hook":
                # Default fallback - give it a base score
                score = 5
                if any(keyword in job_lower for keyword in ['prestigious', 'top', 'leading', 'industry leader']):
                    score += 5
            
            template_scores[template_name] = score
        
        # Select template with highest score, or random if tied
        max_score = max(template_scores.values())
        best_templates = [t for t in self._templates if template_scores[t['name'].lower()] == max_score]
        self._selected_template = random.choice(best_templates)
        
        print(f"Selected template: {self._selected_template['name']} (score: {max_score})")
    
    def get_selected_group(self):
        """Get the currently selected character group."""
        return self._selected_group
    
    def get_selected_character_names(self):
        """Get list of selected character names in lowercase (first word only for directory lookup)."""
        if not self._selected_group:
            return []
        return [self._get_character_directory_name(char['name']) for char in self._selected_group['characters']]

    def _get_character_descriptions(self) -> str:
        """Get the character descriptions section of the prompt from selected group."""
        if not self._selected_group:
            raise ValueError("No character group selected")
        
        characters_section = "CHARACTERS:\n\n"
        for char in self._selected_group['characters']:
            characters_section += f"{char['name']}:\n{char['description']}\n\n"
        
        return characters_section.strip()

    def _get_template_structure(self) -> str:
        """Get the template structure section based on selected template."""
        if not self._selected_template:
            raise ValueError("No template selected")
        
        template_name = self._selected_template['name']
        template_desc = self._selected_template['description']
        sections = self._selected_template['sections']
        
        structure = f"""CONVERSATION STRUCTURE (Template: "{template_name}"):
{template_desc}

Follow this exact order and focus for each section:

"""
        for i, section in enumerate(sections, 1):
            structure += f"{i}. {section['name']} ({section['role']}): {section['description']}\n"
        
        structure += "\nIMPORTANT: The conversation must cover ALL of these sections in the order specified above. "
        structure += "Make sure to include Company Intro, Role & Tech, Requirements, and Compensation information "
        structure += "as they appear in the job description, following the template's order and emphasis."
        
        return structure
    
    def _get_entertainment_tips(self) -> str:
        """Get the entertainment tips section of the prompt."""
        char_names = [char['name'] for char in self._selected_group['characters']]
        char_list = " + ".join(char_names)
        
        # Identify recruiter vs non-recruiter (usually first character is recruiter)
        recruiter = self._selected_group['characters'][0]['name'] if self._selected_group['characters'] else "Recruiter"
        non_recruiter = self._selected_group['characters'][1]['name'] if len(self._selected_group['characters']) > 1 else "Candidate"
        
        return f"""ENTERTAINMENT TIPS - CRITICAL CONVERSATION ARC:

CONFLICT-RESOLUTION STRUCTURE (MANDATORY):
1. OPENING (Skeptical/Resistant): {non_recruiter} should start DISMISSIVE, SKEPTICAL, CONFUSED, or NEGATIVE about the job
   - Express disinterest, doubt, or confusion
   - Play devil's advocate by pointing out flaws or asking stupid questions
   - Act like they don't need it, don't understand it, or think it's fake/scam
   - Examples: "I don't need this", "What's the catch?", "Is that the thing with the computer?", "This sounds fake"

2. MIDDLE (Convincing/Addressing Concerns): {recruiter} must CONVINCE {non_recruiter} by:
   - Addressing their specific concerns and objections
   - Explaining things in terms they understand
   - Using compelling details (salary, equity, tech stack, benefits) to win them over
   - Being persistent but not overly aggressive
   - Examples: "Forget the pension! It has equity!", "It's the future!", "This is for killers only"

3. CLIMAX (The Turning Point): {non_recruiter} shows signs of being convinced:
   - Expresses curiosity or interest
   - Asks follow-up questions that show engagement
   - Stops being dismissive and starts listening

4. RESOLUTION (Acceptance/Excitement): {non_recruiter} comes around:
   - Reluctantly accepts or gets excited
   - Acknowledges they were wrong or that it's compelling
   - Shows they're on board
   - Examples: "Alright, maybe you're right", "Okay, I'm listening", "This is actually pretty cool", "Victory is mine!"

CONVERSATION FLOW:
- Create TENSION and CONFLICT early - don't make it too positive or one-sided
- {non_recruiter} should act STUPID, SKEPTICAL, or NEGATIVE initially
- {recruiter} must WORK to convince them - don't make it easy
- Include back-and-forth exchanges with objections and responses
- Use humor through {non_recruiter}'s confusion or {recruiter}'s frustration
- Follow the conversation structure template exactly
- Make sure all required sections (Company Intro, Role & Tech, Requirements, Compensation) are covered
- End with {non_recruiter} being convinced and on board"""

    def _get_character_directory_name(self, character_name: str) -> str:
        """Get the directory name for a character (first word, lowercased)."""
        # Extract first word and lowercase it for directory lookup
        # "Stewie Griffin" -> "stewie", "Trump" -> "trump"
        return character_name.split()[0].lower()
    
    def _format_available_resources(self) -> str:
        """Format available images and emotions for the prompt based on selected characters."""
        if not self._selected_group:
            raise ValueError("No character group selected")
        
        images_section = "CRITICAL - Available images (ONLY use these exact names, do NOT invent new ones):\n"
        for char in self._selected_group['characters']:
            char_dir_name = self._get_character_directory_name(char['name'])
            char_images = get_available_images(char_dir_name)
            # Format as list with quotes for clarity
            if char_images:
                char_images_list = ", ".join([f'"{img}"' for img in sorted(char_images)])
            else:
                char_images_list = '"default"'
            images_section += f"- {char['name']} ({char_dir_name}): {char_images_list}\n"
        
        images_section += "\nIMPORTANT RULES:\n"
        images_section += "- You MUST only use image names from the list above for each character\n"
        images_section += "- Image names follow the format: '{emotion}_{character}' or 'default'\n"
        images_section += "- If a character doesn't have a specific emotion image, use 'default'\n"
        images_section += "- NEVER create new image names like 'proud_chris' or 'happy_stewie' unless they appear in the list above\n"
        
        emotions_str = ", ".join(AVAILABLE_EMOTIONS)
        images_section += f"\nAvailable emotions for TTS (use in text with (emotion) format): {emotions_str}"
        
        return images_section

    def _create_conversation_intro(self, job_description: str) -> str:
        """Create the introduction/context for the conversation prompt."""
        if not self._selected_group:
            raise ValueError("No character group selected")
        if not self._selected_template:
            raise ValueError("No template selected")
        
        char_names = [char['name'] for char in self._selected_group['characters']]
        char_list = " and ".join(char_names)
        template_name = self._selected_template['name']
        
        return f"""Write an entertaining conversation (20-30 SECONDS MAX) featuring {char_list} discussing a tech job opportunity.

CRITICAL TIMING CONSTRAINT:
- The conversation MUST be 20-30 seconds when spoken aloud
- This typically means 6-10 short lines of dialogue total
- Keep lines BRIEF and PUNCHY - no long explanations
- Get to the point quickly - this is for YouTube Shorts/TikTok

CONTEXT:
You will be given a job description below. The conversation should cover:
- Company Introduction
- Role & Technologies used
- Requirements/Qualifications needed
- Compensation (salary, benefits, equity, etc.)

The conversation should follow the "{template_name}" template structure, which determines the order and emphasis of these sections.

CRITICAL: This conversation MUST have a CONFLICT-RESOLUTION ARC:
- The non-recruiter character should start SKEPTICAL, NEGATIVE, CONFUSED, or DISMISSIVE
- They should play devil's advocate, express doubt, act stupid, or show disinterest
- The recruiter must CONVINCE them through the conversation
- By the end, the non-recruiter should come around and be on board
- This creates tension, humor, and engagement - don't make it too positive or one-sided!

Make it entertaining and engaging for short-form content (YouTube Shorts, Instagram Reels). Assume the viewer is interested in tech jobs but may not know all the details.

JOB DESCRIPTION:
{job_description}"""

    def _create_character_context(self, job_description: str) -> str:
        """Create the character and situation context for the prompt."""
        intro = self._create_conversation_intro(job_description)
        characters = self._get_character_descriptions()
        template_structure = self._get_template_structure()
        entertainment_tips = self._get_entertainment_tips()
        resources = self._format_available_resources()

        return f"""{intro}

{characters}

{template_structure}

{entertainment_tips}

{resources}"""

    def _create_output_format_instructions(self) -> str:
        """Create the output format instructions for the prompt."""
        if not self._selected_group:
            raise ValueError("No character group selected")
        
        char_names_lower = [self._get_character_directory_name(char['name']) for char in self._selected_group['characters']]
        example_chars = char_names_lower[:2] if len(char_names_lower) >= 2 else char_names_lower
        
        return f"""Format:
- TITLE: Extract the company name and position title from the job description provided above
- Format the title as: "Company Name - Position Title"
- Examples: "Ripple - Software Engineer Intern" or "Manulife & John Hancock - Agentic AI Developer"
- Use the actual company name as it appears in the job description (e.g., if it says "About Manulife And John Hancock", use "Manulife & John Hancock")
- Use the position title from the first line or job title section (e.g., "Agentic AI Developer", "Software Engineer Intern")
- Keep it concise, under 60 characters total
- Do NOT create creative titles - use the actual company and position from the job description
- Each line is one character's turn with full text
- Include emotion suggestions in the text using (emotion) format at the start of sentences/phrases
- Example: "(confident) This is how it works. (excited) Let's try it!"
- CRITICAL: In the text, use ONLY single-word emotion words like (confident), (excited), (confused), (sarcastic)
- CRITICAL: NEVER put image names in the text - image names contain underscores like "pretentious_brian" or "laughing_peter"
- CRITICAL: If you see an image name like "pretentious_brian" in the available images, DO NOT put "(pretentious_brian)" in the text
- CRITICAL: Instead, use a similar emotion word like "(pretentious)" or "(arrogant)" in the text, and put "pretentious_brian" in the images array
- CRITICAL: The text field is ONLY for spoken dialogue with emotion markers - NEVER include image names
- Provide an images array with one image name per sentence (can repeat images)
- CRITICAL: The images array MUST contain ONLY image names that exist in the "Available images" list above
- CRITICAL: For each character, you can ONLY use their specific image names (e.g., for chris: "confused_chris", "excited_chris", "surprised_chris", or "default")
- CRITICAL: Do NOT invent new image names like "proud_chris" or "happy_stewie" - only use what's listed above
- IMPORTANT: Character names in the JSON must be lowercase (e.g., "{example_chars[0] if example_chars else 'character'}").
- If a character doesn't have a specific emotion image available, use "default" as a safe fallback.
- Use emotions naturally to enhance delivery rather than forcing them in every line.

Return JSON:
{{
  "title": "Title here",
  "lines": [
    {{
      "character": "{example_chars[0] if example_chars else 'character1'}",
      "text": "(confident) This is interesting! (excited) Let me explain.",
      "images": ["default", "default"]
    }},
    {{
      "character": "{example_chars[1] if len(example_chars) > 1 else example_chars[0] if example_chars else 'character2'}",
      "text": "(curious) Wait, what does that mean?",
      "images": ["default"]
    }}
  ]
}}"""

    def create_prompt(self, job_description: str) -> str:
        """
        Create the complete prompt for the LLM by combining all sections.
        
        Note: Character group and template selection should happen BEFORE calling this method
        (in generate_script) so we can use them for cache keys.
        
        Args:
            job_description: The job description text to generate content about
            
        Returns:
            Complete prompt string
        """
        # Ensure group and template are selected (should already be done, but safety check)
        if not self._selected_group:
            self._select_random_group()
        if not self._selected_template:
            self._select_appropriate_template(job_description)
        
        character_context = self._create_character_context(job_description)
        output_format = self._create_output_format_instructions()
        
        return f"""{character_context}

{output_format}"""

