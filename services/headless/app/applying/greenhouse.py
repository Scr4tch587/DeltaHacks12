"""Greenhouse job application form automation."""

import asyncio
import hashlib
import json
import os
import random
import re
from typing import Any

from playwright.async_api import async_playwright, Page, Browser

from app.ai import get_field_value
from app.rate_limiter import BROWSER_SEMAPHORE, ai_rate_limiter


# Standard field patterns for cache key matching
STANDARD_FIELD_PATTERNS: dict[str, str] = {
    r"first\s*name": "first_name",
    r"last\s*name": "last_name",
    r"email": "email",
    r"phone|telephone|mobile": "phone",
    r"linkedin": "linkedin_url",
    r"github": "github_url",
    r"portfolio|website": "website_url",
    r"years?\s*(of)?\s*experience": "years_of_experience",
    r"authorized?\s*(to)?\s*work": "work_authorization",
    r"sponsor(ship)?|visa\s*(requirement|status)|require.*sponsor": "requires_sponsorship",
    r"gender": "gender",
    r"race|ethnicity": "race_ethnicity",
    r"veteran": "veteran_status",
    r"disability": "disability_status",
    r"^country$|country\s*code|phone.*country": "country",
    r"affirmation|signature|sign\s*here|type.*name.*agree|consent": "signature",
    r"salary|compensation|pay\s*expectation": "salary",
    r"state\s*(of)?\s*residen|current\s*state|what\s*state|from.*state.*work": "state",
    r"pronoun": "pronoun",
}


def get_cache_key(label: str) -> tuple[str, str]:
    """
    Get the cache key for a field label.

    Returns:
        Tuple of (cache_type, cache_key) where cache_type is 'standard' or 'custom'
    """
    normalized = label.lower().strip()

    # Check standard fields
    for pattern, key in STANDARD_FIELD_PATTERNS.items():
        if re.search(pattern, normalized):
            return ("standard", key)

    # Custom field - use hash
    question_hash = hashlib.md5(normalized.encode()).hexdigest()[:16]
    return ("custom", question_hash)


def compute_form_fingerprint(fields: list[dict[str, Any]]) -> str:
    """
    Compute a fingerprint of the form structure.

    Used to detect if form changed between analyze and submit.
    """
    # Sort fields by field_id for consistency
    sorted_fields = sorted(fields, key=lambda f: f.get("field_id", ""))

    # Create a signature from field structure (not values)
    signature_parts = []
    for f in sorted_fields:
        part = f"{f.get('field_id', '')}:{f.get('field_type', '')}:{f.get('label', '')}"
        if f.get("options"):
            part += ":" + ",".join(sorted(f["options"]))
        signature_parts.append(part)

    signature = "|".join(signature_parts)
    return hashlib.sha256(signature.encode()).hexdigest()[:16]


class GreenhouseApplier:
    """Handles Greenhouse job application form automation."""

    def __init__(self, headless: bool = True):
        self.headless = headless

    async def analyze_form(
        self,
        url: str,
        user_profile: dict[str, Any],
        job_description: str = "",
        cached_responses: dict[str, Any] | None = None,
        pre_analyzed_fields: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        """
        Analyze a job application form and generate recommended values.

        Does NOT fill or submit the form.

        Args:
            url: Job application URL
            user_profile: User's profile data
            job_description: Job description text for AI context
            cached_responses: User's cached form responses
            pre_analyzed_fields: Optional list of fields from DB to skip browser extraction

        Returns:
            Dict with 'fields' list and 'form_fingerprint'
        """
        cached_responses = cached_responses or {"standard": {}, "custom": {}}

        # FAST PATH: Use pre-analyzed fields if available
        if pre_analyzed_fields:
            print(f"Using {len(pre_analyzed_fields)} pre-analyzed fields (skipping browser extraction)")
            fields = pre_analyzed_fields
            
            # Generate recommendations for each field (AI)
            # This is fast and CPU-bound, no browser needed
            await self._generate_recommendations(
                fields, user_profile, job_description, cached_responses
            )

            # Compute fingerprint
            fingerprint = compute_form_fingerprint(fields)

            return {
                "status": "success",
                "fields": fields,
                "form_fingerprint": fingerprint
            }

        # SLOW PATH: Launch browser and extract
        async with BROWSER_SEMAPHORE:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context()
                    page = await context.new_page()

                    await page.goto(url)

                    try:
                        await page.wait_for_selector("form", timeout=10000)
                    except Exception:
                        return {"status": "error", "message": "Form not found on page.", "fields": []}

                    # Wait for form to settle
                    await page.wait_for_timeout(2000)

                    # Extract all form fields
                    fields = await self._extract_form_fields(page)

                    # Generate recommendations for each field
                    await self._generate_recommendations(
                        fields, user_profile, job_description, cached_responses
                    )

                    # Compute fingerprint
                    fingerprint = compute_form_fingerprint(fields)

                    return {
                        "status": "success",
                        "fields": fields,
                        "form_fingerprint": fingerprint
                    }
                finally:
                    await browser.close()

    async def fill_and_submit(
        self,
        url: str,
        fields: list[dict[str, Any]],
        user_profile: dict[str, Any] | None = None,
        job_description: str = "",
        expected_fingerprint: str | None = None,
        submit: bool = True,
        keep_open: bool = False,
        output_path: str | None = None,
        verification_callback: Any | None = None
    ) -> dict[str, Any]:
        """
        Fill and optionally submit a job application form.

        Args:
            url: Job application URL
            fields: List of fields with final_value set
            user_profile: Optional user profile for filling conditional fields
            job_description: Optional job description for AI context on conditional fields
            expected_fingerprint: If provided, verify form hasn't changed
            submit: Whether to click submit
            keep_open: Whether to keep browser open after completion (waits for user input)
            output_path: Optional path to save the final HTML content

        Returns:
            Result dict with status and message
        """
        async with BROWSER_SEMAPHORE:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=self.headless)
                try:
                    context = await browser.new_context()
                    page = await context.new_page()

                    await page.goto(url)

                    try:
                        await page.wait_for_selector("form", timeout=10000)
                    except Exception:
                        return {"status": "error", "message": "Form not found on page."}

                    # Verify fingerprint if provided
                    if expected_fingerprint:
                        current_fields = await self._extract_form_fields(page)
                        current_fingerprint = compute_form_fingerprint(current_fields)
                        if current_fingerprint != expected_fingerprint:
                            return {
                                "status": "form_changed",
                                "message": "Form structure has changed since analysis. Please re-analyze."
                            }

                    # Fill all known fields
                    await self._fill_form_fields(page, fields, user_profile=user_profile)

                    # --- SECOND PASS: CHECK FOR NEW FIELDS (Conditional Logic) ---
                    if user_profile:
                        # Wait a moment for UI to update (e.g. Race field appearing)
                        await page.wait_for_timeout(1000)
                        
                        current_fields = await self._extract_form_fields(page)
                        existing_ids = set(f.get("field_id") for f in fields)
                        
                        # Identify truly new fields
                        new_fields = []
                        for f in current_fields:
                            if f.get("field_id") not in existing_ids:
                                # Also check if we accidentally missed it by ID but matched by selector?
                                # Ideally field_id is unique enough.
                                new_fields.append(f)
                        
                        if new_fields:
                            print(f"Detected {len(new_fields)} new fields after initial fill. Attempting to fill...")
                            # Generate values for new fields
                            # We pass empty cache for now as we don't want to block on cache lookup for dynamic fields
                            await self._generate_recommendations(new_fields, user_profile, job_description, {"standard": {}, "custom": {}})
                            
                            # Promote recommended to final
                            for nf in new_fields:
                                if not nf.get("final_value"):
                                    nf["final_value"] = nf.get("recommended_value")
                            
                            # Fill new fields
                            await self._fill_form_fields(page, new_fields, user_profile=user_profile)
                    # -------------------------------------------------------------

                    result = {"status": "dry_run", "message": "Form filled, submit skipped."}
                    if submit:
                        result = await self._submit_form(page, verification_callback=verification_callback)
                    
                    # Save output HTML if requested
                    if output_path:
                        try:
                            content = await page.content()
                            with open(output_path, "w", encoding="utf-8") as f:
                                f.write(content)
                            # print(f"DEBUG: Page HTML saved to {output_path}")
                        except Exception as e:
                            print(f"Failed to save output HTML: {e}")

                    if keep_open:
                        print(f"\nBrowser kept open. Status: {result['status']}")
                        print("Press Enter to close browser and finish...")
                        await asyncio.get_event_loop().run_in_executor(None, input)
                        
                    return result
                finally:
                    await browser.close()

    async def _extract_form_fields(self, page: Page) -> list[dict[str, Any]]:
        """Extract all form fields from the page."""
        fields: list[dict[str, Any]] = []
        field_counter = 0

        # 1. Handle React-Select / custom dropdowns
        custom_selects = await page.query_selector_all(".select__control, div[role='combobox']")
        for cs in custom_selects:
            try:
                # Debug logging for visibility
                is_visible = await cs.is_visible()
                if not is_visible:
                    # Try to identify what we are skipping
                    selector_debug = await self._get_unique_selector(cs)
                    # print(f"DEBUG: Skipping invisible react-select: {selector_debug}")
                    continue

                # Try to get the associated input
                inp = await cs.query_selector("input")
                field_id = None
                if inp:
                    field_id = await inp.get_attribute("id") or await inp.get_attribute("name")

                if not field_id:
                    field_id = f"react_select_{field_counter}"
                    field_counter += 1

                # Get label
                label = await self._get_field_label(page, cs, field_id)

                # Check if required (including label check)
                required = False
                if label and ("*" in label or "required" in label.lower()):
                    required = True

                # Try to get options by clicking and reading menu
                options = await self._get_react_select_options(page, cs)

                # Get selector for this element
                selector = await self._get_unique_selector(cs)

                fields.append({
                    "field_id": field_id,
                    "selector": selector,
                    "label": label or field_id,
                    "field_type": "react_select",
                    "required": required,
                    "options": options,
                    "recommended_value": None,
                    "final_value": None,
                    "source": "manual",
                    "confidence": 0.0,
                    "reasoning": None
                })
            except Exception as e:
                print(f"Error extracting react-select: {e}")

        # 2. Handle Checkbox / Radio Groups
        groups = await page.query_selector_all("fieldset.checkbox, fieldset.radio, .checkbox-group, .radio-group")
        for group in groups:
            try:
                if not await group.is_visible():
                    continue
                
                # Get the label from legend or label
                label_el = await group.query_selector("legend, .label, label")
                label = ""
                if label_el:
                    label = await label_el.text_content()
                
                if not label:
                    # Fallback to id
                    label = await group.get_attribute("id") or f"group_{field_counter}"
                
                field_id = await group.get_attribute("id") or await group.get_attribute("name") or f"group_{field_counter}"
                field_counter += 1

                # Determine options
                options = []
                option_labels = await group.query_selector_all("label")
                for ol in option_labels:
                    txt = await ol.text_content()
                    if txt:
                        options.append(txt.strip())
                
                field_type = "checkbox_group" if "checkbox" in (await group.get_attribute("class") or "").lower() else "radio_group"
                required = await group.get_attribute("aria-required") == "true" or "*" in label

                selector = await self._get_unique_selector(group)

                fields.append({
                    "field_id": field_id,
                    "selector": selector,
                    "label": label.strip(),
                    "field_type": field_type,
                    "required": required,
                    "options": options,
                    "recommended_value": None,
                    "final_value": None,
                    "source": "manual",
                    "confidence": 0.0,
                    "reasoning": None
                })
            except Exception as e:
                print(f"Error extracting group: {e}")

        # 3. Handle standard inputs, textareas, selects
        elements = await page.query_selector_all(
            "input:not([type='hidden']):not([type='submit']):not([type='button']):not([type='reset']):not([type='checkbox']):not([type='radio']), "
            "textarea, select"
        )

        for el in elements:
            try:
                if not await el.is_visible():
                    # File inputs might be hidden but still usable
                    type_attr = await el.get_attribute("type")
                    if type_attr != "file":
                        # print(f"DEBUG: Skipping invisible input: {await self._get_unique_selector(el)}")
                        continue

                # Skip elements that are effectively hidden (accessibility/react-select helpers)
                aria_hidden = await el.get_attribute("aria-hidden")
                if aria_hidden == "true":
                    continue
                
                class_name = await el.get_attribute("class") or ""
                if "requiredInput" in class_name:
                    continue

                # Skip if inside a react-select (already handled)
                is_react_child = await el.evaluate("""e => {
                    return !!e.closest('.select__control') || !!e.closest('div[role="combobox"]');
                }""")
                if is_react_child:
                    continue

                tag_name = await el.evaluate("e => e.tagName.toLowerCase()")
                type_attr = await el.get_attribute("type") or "text"
                field_id = await el.get_attribute("id") or await el.get_attribute("name")

                if not field_id:
                    field_id = f"{tag_name}_{field_counter}"
                    field_counter += 1

                # Skip certain types
                if type_attr in ["checkbox", "radio", "image"]:
                    continue

                # Determine field type
                if tag_name == "select":
                    field_type = "select"
                elif tag_name == "textarea":
                    field_type = "textarea"
                elif type_attr == "file":
                    field_type = "file"
                else:
                    field_type = "text"

                # Get label
                label = await self._get_field_label(page, el, field_id)

                # Get options for select
                options = None
                if field_type == "select":
                    options = await self._get_select_options(el)

                # Check if required
                required = await el.get_attribute("required") is not None
                aria_required = await el.get_attribute("aria-required")
                if aria_required == "true":
                    required = True
                
                # Special check for Greenhouse file uploads (container has aria-required)
                if field_type == "file":
                    # Check parent .file-upload container
                    is_gh_required = await el.evaluate("""e => {
                        const container = e.closest('.file-upload');
                        return container ? container.getAttribute('aria-required') === 'true' : false;
                    }""")
                    if is_gh_required:
                        required = True
                
                # Fallback: Check label for *
                if not required and label and ("*" in label or "required" in label.lower()):
                    required = True

                # Get selector
                selector = await self._get_unique_selector(el)

                fields.append({
                    "field_id": field_id,
                    "selector": selector,
                    "label": label or field_id,
                    "field_type": field_type,
                    "required": required,
                    "options": options,
                    "recommended_value": None,
                    "final_value": None,
                    "source": "manual",
                    "confidence": 0.0,
                    "reasoning": None
                })
            except Exception as e:
                print(f"Error extracting field: {e}")

        return fields

    async def _get_field_label(self, page: Page, element, field_id: str | None) -> str:
        """Get the label text for a form field."""
        label_text = ""

        # 0. Greenhouse specific: Look for parent .input-wrapper's label
        # This is very common in Greenhouse forms
        label_text = await element.evaluate("""e => {
            const wrapper = e.closest('.input-wrapper');
            if (wrapper) {
                const label = wrapper.querySelector('label');
                if (label) return label.innerText;
            }
            return '';
        }""")
        
        if label_text:
            return label_text.strip()

        # 1. Try 'for' attribute
        if field_id:
            labels = await page.query_selector_all(f"label[for='{field_id}']")
            if labels:
                label_text = await labels[0].text_content() or ""

        # 2. Try aria-labelledby
        if not label_text:
            aria_labelledby = await element.get_attribute("aria-labelledby")
            if aria_labelledby:
                lbl_el = await page.query_selector(f"#{aria_labelledby}")
                if lbl_el:
                    label_text = await lbl_el.text_content() or ""

        # 3. Try aria-label
        if not label_text:
            label_text = await element.get_attribute("aria-label") or ""

        # 4. Try placeholder
        if not label_text:
            label_text = await element.get_attribute("placeholder") or ""

        # 5. Try closest label (generic fallback)
        if not label_text:
            label_text = await element.evaluate("""e => {
                let label = e.closest('label');
                if (!label) {
                    const container = e.closest('.field, .form-group');
                    if (container) {
                        label = container.querySelector('label');
                    }
                }
                return label ? label.innerText : '';
            }""") or ""

        return label_text.strip()

    async def _get_select_options(self, select_element) -> list[str]:
        """Get options from a standard select element."""
        options = []
        option_elements = await select_element.query_selector_all("option")
        for opt in option_elements:
            text = await opt.text_content()
            value = await opt.get_attribute("value")
            # Prefer text, fall back to value
            opt_text = (text or value or "").strip()
            if opt_text:
                options.append(opt_text)
        return options

    async def _get_react_select_options(self, page: Page, control_element) -> list[str]:
        """Try to get options from a React-Select dropdown."""
        options = []
        try:
            # Click to open menu
            await control_element.click()
            await page.wait_for_timeout(300)

            # Look for menu options
            option_els = await page.query_selector_all(
                ".select__option, [class*='option'], div[id*='option']"
            )

            for opt in option_els[:20]:  # Limit to prevent too many
                if await opt.is_visible():
                    text = await opt.text_content()
                    if text:
                        options.append(text.strip())

            # Press Escape to close menu
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(100)
        except Exception as e:
            print(f"Error getting react-select options: {e}")

        return options

    async def _get_unique_selector(self, element) -> str:
        """Generate a unique CSS selector for an element."""
        try:
            # Try ID first
            el_id = await element.get_attribute("id")
            if el_id:
                return f"#{el_id}"

            # Try name
            name = await element.get_attribute("name")
            tag = await element.evaluate("e => e.tagName.toLowerCase()")
            if name:
                return f"{tag}[name='{name}']"

            # Fall back to generating a path
            selector = await element.evaluate("""e => {
                const path = [];
                while (e) {
                    if (e.id) {
                        path.unshift('#' + e.id);
                        break;
                    }
                    let selector = e.tagName.toLowerCase();
                    if (e.parentElement) {
                        const siblings = Array.from(e.parentElement.children).filter(
                            s => s.tagName === e.tagName
                        );
                        if (siblings.length > 1) {
                            selector += ':nth-of-type(' + (siblings.indexOf(e) + 1) + ')';
                        }
                    }
                    path.unshift(selector);
                    e = e.parentElement;
                }
                return path.join(' > ');
            }""")
            return selector
        except Exception:
            return ""

    async def _generate_recommendations(
        self,
        fields: list[dict[str, Any]],
        user_profile: dict[str, Any],
        job_description: str,
        cached_responses: dict[str, Any]
    ):
        """Generate AI recommendations for each field."""
        tasks = []

        for field in fields:
            # Skip file fields - handled separately
            if field["field_type"] == "file":
                field["recommended_value"] = "[Resume will be uploaded]"
                field["source"] = "profile"
                field["confidence"] = 1.0
                continue

            label = field["label"]
            cache_type, cache_key = get_cache_key(label)

            # Check profile first for core fields
            profile_value = self._get_profile_value(field, user_profile)
            print(f"Debug: _get_profile_value for '{label}' returned: '{profile_value}'")
            if profile_value:
                field["recommended_value"] = profile_value
                field["source"] = "profile"
                field["confidence"] = 1.0
                field["reasoning"] = "From your profile"
                continue

            # Check cached responses
            if cache_type == "standard":
                cached_value = cached_responses.get("standard", {}).get(cache_key)
                if cached_value:
                    field["recommended_value"] = cached_value
                    field["source"] = "cached"
                    field["confidence"] = 0.9
                    field["reasoning"] = "Previously used answer"
                    continue
            else:
                custom_cache = cached_responses.get("custom", {}).get(cache_key)
                if custom_cache:
                    field["recommended_value"] = custom_cache.get("answer")
                    field["source"] = "cached"
                    field["confidence"] = 0.9
                    field["reasoning"] = "Previously used answer"
                    continue

            # Need AI for this field
            tasks.append(self._get_ai_recommendation(field, user_profile, job_description))

        # Run AI tasks concurrently
        if tasks:
            await asyncio.gather(*tasks)

    def _get_profile_value(self, field: dict[str, Any], profile: dict[str, Any]) -> str | None:
        """Try to get a value directly from the user profile."""
        label_lower = field["label"].lower()
        field_id_lower = str(field.get("field_id", "")).lower()

        # HARDCODED: Always use this phone number for all applications
        phone_patterns = ["phone", "telephone", "mobile", "contact number"]
        if any(pattern in label_lower or pattern in field_id_lower for pattern in phone_patterns):
            # Check if it's not country-related (avoid matching "phone country" fields)
            if "country" not in label_lower:
                return "+1 3052475339"

        # Direct mappings
        mappings = {
            "first_name": ["first name", "firstname", "first_name"],
            "last_name": ["last name", "lastname", "last_name"],
            "email": ["email", "e-mail"],
            "linkedin_url": ["linkedin"],
            "github_url": ["github"],
            "website_url": ["website", "portfolio"],
            "location": ["location", "address"],
            "race": ["race", "ethnicity", "latino", "hispanic"],
            "gender": ["gender", "sex"],
            "veteran_status": ["veteran"],
            "disability": ["disability", "handicap"],
            "authorization": ["authorized to work", "work authorization"],
            "sponsorship": ["sponsorship", "sponsor", "visa requirement", "visa status", "require visa"],
            "salary": ["salary", "compensation", "pay expectation", "desired salary"],
        }

        for profile_key, patterns in mappings.items():
            for pattern in patterns:
                if pattern in label_lower or pattern in field_id_lower:
                    # Special handling for location: Don't match if it looks like a specific address part
                    # (e.g. "City", "Zip Code") but the pattern matched "address"
                    # Also skip if it contains "pronoun" (e.g. "we address you with the appropriate pronoun")
                    if profile_key == "location":
                        address_parts = ["city", "state", "province", "region", "zip", "postal", "code", "street", "line", "country", "pronoun"]
                        if any(part in label_lower for part in address_parts):
                            continue

                    value = profile.get(profile_key)
                    if value:
                        # Debug match
                        # print(f"Matched field '{field['label']}' to profile key '{profile_key}' via pattern '{pattern}'")
                        return str(value)

        # Special handling for country field - extract from location
        if "country" in label_lower or "country" in field_id_lower:
            location = profile.get("location", "")
            if location:
                # Try to extract country from location string like "New York, NY, USA"
                loc_lower = location.lower()
                if "usa" in loc_lower or "united states" in loc_lower or ", us" in loc_lower:
                    return "United States"
                elif "canada" in loc_lower:
                    return "Canada"
                elif "uk" in loc_lower or "united kingdom" in loc_lower:
                    return "United Kingdom"
                # For phone country selectors, they often want country code format
                # Return the last part of location as a guess
                parts = location.split(",")
                if len(parts) >= 1:
                    country_guess = parts[-1].strip()
                    if country_guess.upper() == "USA":
                        return "United States"
                    return country_guess

        # Special handling for affirmation/signature fields - use full name
        # These are fields where the user types their name as consent/acknowledgement
        affirmation_patterns = ["affirmation", "signature", "sign here", "type your name", "type name", "consent", "acknowledge"]
        if any(p in label_lower for p in affirmation_patterns):
            first = profile.get("first_name", "")
            last = profile.get("last_name", "")
            if first and last:
                return f"{first} {last}"

        # Special handling for state field - extract from location
        state_patterns = ["state of residen", "current state", "what state", "from what state", "state do you", "plan to work"]
        if any(p in label_lower for p in state_patterns):
            print(f"Debug: State pattern matched for label: '{label_lower}'")
            location = profile.get("location", "")
            print(f"Debug: Location from profile: '{location}'")
            if location:
                # Parse "New York, NY, USA" or "San Francisco, CA, USA"
                parts = [p.strip() for p in location.split(",")]
                if len(parts) >= 2:
                    # Second part is usually state abbreviation (NY, CA, etc.)
                    state_abbrev = parts[1].strip().upper()
                    # Return abbreviation directly - dropdowns usually use abbreviations
                    # and typing "NY" will filter to show "New York" or "NY" options
                    print(f"Debug: Returning state abbreviation: '{state_abbrev}'")
                    return state_abbrev

        # Special handling for pronoun field
        if "pronoun" in label_lower:
            print(f"Debug: Pronoun pattern matched for label: '{label_lower}'")
            # Default to "Prefer not to say" for privacy
            return "Prefer not to say"

        return None

    async def _get_ai_recommendation(
        self,
        field: dict[str, Any],
        user_profile: dict[str, Any],
        job_description: str
    ):
        """Get AI recommendation for a single field."""
        await ai_rate_limiter.acquire()

        # Build context string
        context_parts = [f"Type: {field['field_type']}"]
        if field.get("options"):
            context_parts.append(f"Options: {json.dumps(field['options'])}")
        context_str = ", ".join(context_parts)

        try:
            value = await get_field_value(
                field["label"],
                context_str,
                user_profile,
                job_description
            )

            if value:
                field["recommended_value"] = value
                field["source"] = "ai"
                field["confidence"] = 0.7
                field["reasoning"] = "AI-generated based on your profile"

                # For dropdowns, verify the value matches an option
                if field.get("options") and value not in field["options"]:
                    # Try to find closest match
                    value_lower = value.lower()
                    for opt in field["options"]:
                        if value_lower in opt.lower() or opt.lower() in value_lower:
                            field["recommended_value"] = opt
                            field["reasoning"] = f"AI suggested '{value}', matched to '{opt}'"
                            break
        except Exception as e:
            print(f"AI error for field {field['label']}: {e}")
            field["confidence"] = 0.0

    async def _fill_file_field(self, page: Page, selector: str, file_path: str):
        """Upload a file to a file input field."""
        import os
        from pathlib import Path
        
        # Relative path from this module: app/applying/greenhouse.py -> app/data/resumes/...
        # Go up 2 levels (applying -> app) then into data/resumes
        module_dir = Path(__file__).parent.parent
        hardcoded_path = module_dir / "data" / "resumes" / "thomasariogpt_gmail_com" / "resume.pdf"
        
        # Use hardcoded path if it exists, otherwise try the provided path
        if os.path.exists(hardcoded_path):
            actual_path = hardcoded_path
            print(f"Using hardcoded resume path: {actual_path}")
        elif file_path and os.path.exists(file_path):
            actual_path = file_path
            print(f"Using provided resume path: {actual_path}")
        else:
            print(f"File not found: {file_path}")
            return
        
        try:
            # Try Greenhouse-specific selectors first
            # The resume input is typically id="resume" but visually hidden
            file_input = page.locator("#resume").first
            
            if await file_input.count() == 0:
                # Try cover_letter
                file_input = page.locator("#cover_letter").first
            
            if await file_input.count() == 0:
                # Try the provided selector
                file_input = page.locator(selector).first
            
            if await file_input.count() == 0:
                # Generic fallback
                file_input = page.locator("input[type='file']").first
            
            if await file_input.count() > 0:
                await file_input.set_input_files(actual_path)
                print(f"✓ Resume uploaded successfully: {Path(actual_path).name}")
                await page.wait_for_timeout(1000)  # Wait for upload to process
            else:
                print(f"File input not found with selector: {selector}")
        except Exception as e:
            print(f"Error uploading file: {e}")


    async def _fill_form_fields(self, page: Page, fields: list[dict[str, Any]], user_profile: dict[str, Any] | None = None):
        """Fill all form fields with their final values."""
        
        # 1. Determine Country Hint for Phone Fields
        country_hint = None
        explicit_country_field_exists = False
        
        for field in fields:
            label = field.get("label", "").lower()
            val = field.get("final_value") or field.get("recommended_value")
            if "country" in label and val:
                # Extract name before any code: "United States +1" -> "United States"
                country_hint = val.split('+')[0].strip()
                explicit_country_field_exists = True
                break
        
        if not country_hint and user_profile:
            # Try to infer from location
            loc = user_profile.get("location", "").lower()
            if "usa" in loc or "united states" in loc:
                country_hint = "United States"
            elif "canada" in loc:
                country_hint = "Canada"
            elif "uk" in loc or "united kingdom" in loc:
                country_hint = "United Kingdom"
        
        if country_hint:
            print(f"Debug: Country hint for phone fields: {country_hint} (Explicit field: {explicit_country_field_exists})")

        # 2. Fill fields
        for field in fields:
            value = field.get("final_value") or field.get("recommended_value")
            label = field.get("label")
            field_type = field.get("field_type")
            is_required = field.get("required")

            # FILTER: Only fill required fields (unless it's a file/resume)
            if not is_required and field_type != "file":
                print(f"Skipping OPTIONAL field: '{label}'")
                continue
            
            if not value:
                # Special handling for groups: try to find a "None" / "N/A" option if required
                if is_required and field_type in ["checkbox_group", "radio_group"]:
                     print(f"Required group '{label}' has no value. Attempting auto-fill of negative option.")
                     # proceed with empty value to let the fill method handle fallback
                elif is_required:
                    print(f"Skipping required field with NO value: '{label}'")
                    continue
                else:
                    continue

            print(f"Filling field '{label}' (Type: {field_type}) with value: '{str(value)[:50]}...'")
            
            selector = field.get("selector")

            try:
                if field_type == "file":
                    # Fix: If AI returned a placeholder string, use the actual resume path from profile
                    # This fixes the issue where AI says "[Resume will be uploaded]" but we need the real path
                    # Check for common resume field labels: resume, cv, attach
                    if user_profile and ("resume" in label.lower() or "cv" in label.lower() or "attach" in label.lower()):
                         actual_path = user_profile.get("resume_path")
                         if actual_path:
                             print(f"Overriding file value with path from profile: {actual_path}")
                             value = actual_path

                    await self._fill_file_field(page, selector, value)
                elif field_type == "react_select":
                    await self._fill_react_select(page, selector, value, label)
                elif field_type == "select":
                    await self._fill_standard_select(page, selector, value)
                elif field_type == "checkbox_group":
                    await self._fill_checkbox_group(page, selector, value, required=is_required)
                elif field_type == "radio_group":
                    await self._fill_radio_group(page, selector, value, required=is_required)
                else:
                    # Pass explicit_country_field_exists to avoid double-setting flag
                    await self._fill_text_field(
                        page, 
                        selector, 
                        value, 
                        country_hint=country_hint, 
                        skip_iti_flag=explicit_country_field_exists
                    )
            except Exception as e:
                print(f"Error filling {label}: {e}")

        # 3. Post-fill: Go through all REQUIRED select fields, open dropdown and press enter to select first option
        # This helps trigger onChange handlers and validates selections
        print("\n--- POST-FILL: Opening dropdowns and selecting first option (REQUIRED fields only) ---")
        # Only process required select fields, but EXCLUDE country selectors that are part of phone widgets
        select_fields = []
        for f in fields:
            if f.get("field_type") in ["select", "react_select"] and f.get("required"):
                label = f.get("label", "").lower()
                # Skip country selectors (they're usually part of phone input widgets)
                if "country" not in label:
                    select_fields.append(f)
                else:
                    print(f"Skipping country selector '{f.get('label')}' (likely part of phone widget)")
        
        # Safety: Cap at reasonable number to prevent infinite loops
        max_fields = min(len(select_fields), 50)
        
        for idx in range(max_fields):
            field = select_fields[idx]
            selector = field.get("selector")
            field_type = field.get("field_type")
            label = field.get("label", "Unknown")
            
            if not selector:
                continue
                
            try:
                print(f"Post-fill [{idx+1}/{max_fields}]: Processing {field_type} field '{label}'")
                
                if field_type == "select":
                    # Standard HTML select element
                    locator = page.locator(selector).first
                    if await locator.count() > 0 and await locator.is_visible():
                        # Click to open dropdown
                        await locator.click()
                        await page.wait_for_timeout(300)
                        
                        # Press Enter to select the highlighted option
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(200)
                        
                        # Press Escape to ensure dropdown is closed
                        await page.keyboard.press("Escape")
                        await page.wait_for_timeout(100)
                
                elif field_type == "react_select":
                    # React-Select component
                    target = page.locator(selector).first
                    if await target.count() > 0 and await target.is_visible():
                        # Click to open the dropdown menu
                        await target.click()
                        await page.wait_for_timeout(500)  # Give more time for menu to open
                        
                        # Check if dropdown menu is actually visible
                        try:
                            menu_visible = await page.locator(".select__menu, .select__menu-list, [class*='menu']").first.is_visible()
                        except:
                            menu_visible = False
                        
                        if menu_visible:
                            # Press Enter to select the first/highlighted option
                            await page.keyboard.press("Enter")
                            await page.wait_for_timeout(200)
                        else:
                            # Menu didn't open, just press Escape to close and move on
                            await page.keyboard.press("Escape")
                            await page.wait_for_timeout(100)
                        
            except Exception as e:
                print(f"Error in post-fill for {label}: {e}")
                # Try to close any open dropdown before continuing
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(100)
                except:
                    pass
                # Continue to next field

        # Post-fill validation: check for fields with validation errors
        try:
            error_fields = await page.query_selector_all("[aria-invalid='true'], .input-wrapper--error")
            if len(error_fields) > 0:
                print(f"Warning: {len(error_fields)} field(s) have validation errors after filling")
                for ef in error_fields[:5]:  # Log first 5
                    label_attr = await ef.get_attribute("aria-label") or await ef.get_attribute("id") or "unknown"
                    print(f"  - Field with error: {label_attr}")
        except Exception as e:
            print(f"Debug: Could not check validation errors: {e}")

    async def _fill_checkbox_group(self, page: Page, selector: str, value: Any, required: bool = False):
        """Fill a checkbox group."""
        if not selector:
            return
        
        container = page.locator(selector).first
        if await container.count() == 0:
            return

        # Prepare selected options
        selected_options = []
        if value:
            if isinstance(value, str):
                selected_options = [v.strip().lower() for v in value.split(",")]
            elif isinstance(value, list):
                selected_options = [str(v).lower() for v in value]
            else:
                selected_options = [str(value).lower()]
        
        # Check if we should look for a "None" / "N/A" option
        # Trigger if:
        # 1. No options selected but field is required
        # 2. Value explicitly says "none", "n/a", etc.
        none_keywords = ["none", "n/a", "not applicable", "no", "false"]
        should_pick_none = False
        
        if not selected_options and required:
            should_pick_none = True
        elif any(k in (selected_options[0] if selected_options else "") for k in none_keywords) and len(selected_options) == 1:
            should_pick_none = True

        checkbox_wrappers = await container.locator(".checkbox__wrapper, div").all()
        for wrapper in checkbox_wrappers:
            label_el = wrapper.locator("label")
            if await label_el.count() > 0:
                label_text = (await label_el.text_content() or "").strip().lower()
                input_el = wrapper.locator("input[type='checkbox']")
                
                # Check match
                is_match = False
                if selected_options:
                    # Strict match first, then substring
                    if any(opt == label_text for opt in selected_options):
                        is_match = True
                    elif any(opt in label_text or label_text in opt for opt in selected_options):
                        # Avoid over-matching "No" with "North"
                        is_match = True
                
                # If we are in "pick none" mode, look for N/A labels
                if should_pick_none:
                    if any(k == label_text or k in label_text for k in none_keywords):
                        is_match = True

                if is_match:
                    if not await input_el.is_checked():
                        await input_el.check()

    async def _fill_radio_group(self, page: Page, selector: str, value: str, required: bool = False):
        """Fill a radio group."""
        if not selector:
            return
        
        container = page.locator(selector).first
        if await container.count() == 0:
            return

        val_lower = str(value).lower() if value else ""
        
        # Check for fallback
        none_keywords = ["none", "n/a", "not applicable", "no", "false"]
        should_pick_none = False
        if not val_lower and required:
            should_pick_none = True
        elif val_lower in none_keywords:
            should_pick_none = True

        radio_wrappers = await container.locator("div").all()
        best_match = None
        
        for wrapper in radio_wrappers:
            label_el = wrapper.locator("label")
            if await label_el.count() > 0:
                label_text = (await label_el.text_content() or "").strip().lower()
                input_el = wrapper.locator("input[type='radio']")
                
                if val_lower:
                    if val_lower == label_text:
                        best_match = input_el
                        break
                    elif val_lower in label_text or label_text in val_lower:
                        if not best_match:
                            best_match = input_el
                
                if should_pick_none:
                    if any(k == label_text or k in label_text for k in none_keywords):
                        best_match = input_el
                        # Don't break immediately, prioritize exact "No" over "Not sure" if both exist? 
                        # Usually just taking the first N/A is fine.
                        break
        
        if best_match:
            await best_match.check()

    async def _fill_text_field(self, page: Page, selector: str, value: str, country_hint: str | None = None, skip_iti_flag: bool = False):
        """Fill a text input or textarea."""
        if not selector:
            return
            
        locator = page.locator(selector).first
        if await locator.count() > 0 and await locator.is_visible():
            await locator.scroll_into_view_if_needed()
            
            # Special handling for phone fields (often use intl-tel-input which needs typing)
            is_phone = "phone" in selector.lower() or await locator.get_attribute("type") == "tel"

            # Strip all non-digit characters from phone numbers for cleaner input
            if is_phone:
                import re
                value = re.sub(r'\D', '', str(value))

            # Always click and clear first
            await locator.click()
            await locator.clear()

            if is_phone:
                # Handle intl-tel-input (iti) dropdown if present
                try:
                    # Look for the iti container wrapping this input
                    iti_container = page.locator(".iti").filter(has=locator).first
                    if await iti_container.count() > 0:
                        selected_country_btn = iti_container.locator(".iti__selected-country").first
                        if await selected_country_btn.count() > 0:
                            # Only attempt to change country if:
                            # 1. We are NOT skipping flag (no separate country field)
                            # 2. Value doesn't have a '+' prefix (which might imply full international format)
                            # 3. We have a hint
                            if not skip_iti_flag and not str(value).startswith("+") and country_hint:
                                await selected_country_btn.click()
                                await page.wait_for_timeout(300)

                                # Wait for dropdown to become visible (iti__hide class removed)
                                dropdown = page.locator(".iti__dropdown-content:not(.iti__hide)").first
                                try:
                                    await dropdown.wait_for(state="visible", timeout=2000)
                                except Exception:
                                    # Dropdown may have different structure, continue anyway
                                    pass

                                # ITI usually has a search input in the dropdown
                                search_input = page.locator(".iti__search-input").first
                                if await search_input.count() > 0:
                                    await search_input.fill(country_hint)
                                    await page.wait_for_timeout(500)
                                    # Try to click first visible matching country
                                    first_match = page.locator(".iti__country:not(.iti__hidden)").first
                                    if await first_match.count() > 0:
                                        await first_match.click()
                                    else:
                                        await page.keyboard.press("Enter")
                                    await page.wait_for_timeout(300)
                except Exception as e:
                    print(f"Debug: Failed to set ITI country code: {e}")

            # Use sequences for ALL text fields to trigger React/event listeners reliably
            await locator.press_sequentially(str(value), delay=20)
        else:
             print(f"Text field not found: {selector}")

    async def _fill_standard_select(self, page: Page, selector: str, value: str):
        """Fill a standard HTML select element."""
        if not selector:
            return

        locator = page.locator(selector).first
        if await locator.count() == 0:
            print(f"Select field not found: {selector}")
            return
            
        # Try to select by visible text first, then by value
        try:
            await locator.select_option(label=value)
        except Exception:
            try:
                await locator.select_option(value=value)
            except Exception:
                # Try partial match
                # Use evaluate to find the matching option
                option_val = await locator.evaluate(f"""(select, text) => {{
                    const options = Array.from(select.options);
                    const match = options.find(o => o.text.toLowerCase().includes(text.toLowerCase()));
                    return match ? match.value : null;
                }}""", value)
                
                if option_val:
                    await locator.select_option(value=option_val)

    async def _fill_react_select(self, page: Page, selector: str, value: str, label: str = ""):
        """Fill a React-Select component."""
        # Strategy: Use Locator with multiple fallback selectors
        target = None
        
        # 1. Try the specific selector
        if selector:
            target = page.locator(selector).first
            if not await target.is_visible():
                target = None

        # 2. Try by Label if selector failed
        if not target and label:
            try:
                # Find label element
                label_el = page.get_by_text(label, exact=True).first
                if await label_el.count() > 0:
                    # Check for 'for' attribute
                    for_attr = await label_el.get_attribute("for")
                    if for_attr:
                        # React-select often uses the input ID, but the click target is the control
                        # Try finding control by aria-labelledby or container of the input
                        target = page.locator(f".select__control:has(input[id='{for_attr}'])").first
                    
                    if not target or not await target.is_visible():
                        # Go up to a container that has a select__control
                        # Use a more flexible xpath to find the control in the same container
                        target = label_el.locator("xpath=ancestor::div[contains(@class, 'field') or contains(@class, 'input-wrapper') or contains(@class, 'select')]//div[contains(@class, 'select__control')]").first
            except Exception:
                pass

        if not target or not await target.is_visible():
             # Last ditch: try finding by value if it's already filled? No, we want to fill it.
             # Try finding ANY react select near the label text
             if label:
                 try:
                     target = page.locator(f"div:has-text('{label}') >> .select__control").first
                 except:
                     pass

        if not target or not await target.is_visible():
             if selector:
                 print(f"React select not found by selector: {selector}")
             return

        await target.scroll_into_view_if_needed()
        
        # Determine if this is likely an async field
        # ... (rest of the function remains the same)
        try:
            field_id = await target.get_attribute("id") or ""
        except:
            field_id = ""
            
        field_info_str = (selector + " " + label + " " + field_id).lower()
        is_async = "location" in field_info_str or "city" in field_info_str or "school" in field_info_str or "university" in field_info_str
        
        try:
            # 1. Click to open menu
            await target.click()
            await page.wait_for_timeout(300)

            # 2. Check if we should type first (Async or Long List)
            # Quick check for option count
            option_count = await page.locator(".select__option, [class*='option'], div[id*='option']").count()
            should_type_first = is_async or option_count > 20

            if should_type_first:
                # Type to filter
                await page.keyboard.type(value, delay=50)
                await page.wait_for_timeout(1500 if is_async else 500)
            
            # 3. Iterate visible options to find a match and CLICK it
            option_els = await page.locator(".select__option, [class*='option'], div[id*='option']").all()
            
            # Keywords for "Decline" / "Prefer not to answer"
            decline_keywords = [
                "decline", "prefer not", "do not wish", "not specify", "wish to answer",
                "rather not", "choose not", "don't wish", "no answer", "i prefer not",
                "prefer to not", "not to disclose", "do not want", "choose to not", "opt out"
            ]
            val_lower = value.lower()
            is_decline_value = any(k in val_lower for k in decline_keywords)
            
            best_match_el = None
            debug_options = []

            # Collect all options first to make better decision
            visible_options = []
            for opt in option_els:
                if await opt.is_visible():
                    text = await opt.text_content()
                    if text:
                        visible_options.append((text.strip(), opt))
                        debug_options.append(text.strip())

            # Decision Logic
            match_found = False
            
            # 1. Priority: Decline explicitly
            if is_decline_value:
                for text, opt in visible_options:
                    if any(k in text.lower() for k in decline_keywords):
                        best_match_el = opt
                        match_found = True
                        break
            
            # 2. Exact Match
            if not match_found:
                for text, opt in visible_options:
                    if val_lower == text.lower():
                        best_match_el = opt
                        match_found = True
                        break
            
            # 3. Special handling for Yes/No type answers
            # If the value implies "no" (contains "do not", "not require", etc.), match "No"
            # If the value implies "yes" (contains "i am", "will", etc.), match "Yes"
            if not match_found:
                # Negative indicators - phrases that imply "No" answer
                negative_indicators = ["do not", "don't", "not require", "no sponsor", "not need", "won't", "cannot", "can not", "am not"]
                # Positive indicators - phrases that imply "Yes" answer
                positive_indicators = ["i am", "i will", "i can", "yes", "am authorized", "am legally", "am comfortable", "willing to"]

                is_negative = any(ind in val_lower for ind in negative_indicators)
                is_positive = any(ind in val_lower for ind in positive_indicators)

                # IMPORTANT: Negative takes precedence (e.g., "do not require" beats "require")
                if is_negative:
                    # First try explicit "No"
                    for text, opt in visible_options:
                        opt_lower = text.lower()
                        if opt_lower in ["no", "no,"]:
                            best_match_el = opt
                            match_found = True
                            break
                    # If no "No" option found, try "None" / "Not required" type options
                    # (common for visa type dropdowns where the answer is "I don't need a visa")
                    if not match_found:
                        none_keywords = ["none", "not required", "n/a", "not applicable", "does not apply",
                                        "do not require", "don't need", "not needed", "no visa", "no sponsorship"]
                        for text, opt in visible_options:
                            opt_lower = text.lower()
                            if any(nk in opt_lower for nk in none_keywords):
                                best_match_el = opt
                                match_found = True
                                break
                elif is_positive:
                    for text, opt in visible_options:
                        opt_lower = text.lower()
                        if opt_lower in ["yes", "yes,"]:
                            best_match_el = opt
                            match_found = True
                            break

            # 4. Fuzzy/Substring (Restricted)
            if not match_found:
                for text, opt in visible_options:
                    opt_lower = text.lower()
                    # Guard against "No" in "Prefer NOT..." - skip short options
                    if opt_lower in ["no", "yes"]:
                        continue

                    if val_lower in opt_lower or opt_lower in val_lower:
                        best_match_el = opt
                        match_found = True
                        break

            if best_match_el:
                await best_match_el.click()
                return

            # If we typed but didn't find a clickable match, maybe try Enter (for free text)
            if should_type_first:
                await page.keyboard.press("Enter")
                return
            
            # If we didn't type (short list) and didn't find match, print warning
            print(f"Warning: Value '{value}' not found in options for {label}.")
            print(f"  Available options: {debug_options[:15]}...")
            await page.keyboard.press("Escape")

        except Exception as e:
            print(f"Error filling react-select {label}: {e}")




    async def _submit_form(self, page: Page, verification_callback: Any | None = None) -> dict[str, Any]:
        """Submit the form and wait for confirmation."""
        # Find submit button
        submit_btn = await page.query_selector("#submit_app")
        if not submit_btn:
            submit_btn = await page.query_selector("input[type='submit']")
        if not submit_btn:
            submit_btn = await page.query_selector("button[type='submit']")

        if not submit_btn:
            return {"status": "error", "message": "Submit button not found."}

        # Wait a moment for any validation scripts to run
        await page.wait_for_timeout(1000)
        await submit_btn.click()

        # Check for immediate verification modal
        try:
            # Wait for either confirmation OR verification modal
            # .email-verification is the class for the modal container
            # #application_confirmation is success
            
            # We poll for both conditions
            for _ in range(90): # Increased to 90s per user request
                # 1. Success
                if await page.locator("#application_confirmation").count() > 0:
                    return {"status": "success", "message": "Application submitted successfully."}
                
                # Check for validation errors
                error_elem = page.locator("#error_message, .error-message, .field-error-msg").first
                if await error_elem.count() > 0 and await error_elem.is_visible():
                     error_text = await error_elem.inner_text()
                     return {"status": "failed", "message": f"Validation Error detected: {error_text}"}

                # 2. Verification Modal
                if await page.locator(".email-verification").count() > 0:
                     print("EMAIL VERIFICATION REQUIRED")
                     if not verification_callback:
                         return {"status": "error", "message": "Email verification required but no callback provided."}
                     
                     # Call callback to get code
                     code = await verification_callback()
                     if not code or len(code) != 8:
                         return {"status": "error", "message": "Invalid verification code provided."}
                     
                     # Fill inputs
                     print(f"Filling verification code: {code}")
                     inputs = await page.locator(".email-verification__wrapper input").all()
                     for idx, char in enumerate(code):
                         if idx < len(inputs):
                             await inputs[idx].fill(char)
                             await page.wait_for_timeout(50)
                     
                     # Wait a moment
                     await page.wait_for_timeout(500)

                     # Click Verify/Submit button in modal
                     verify_btn = page.locator(".email-verification button, #email-verification-submit, button:has-text('Verify'), button:has-text('Submit Code')").first
                     if await verify_btn.count() > 0 and await verify_btn.is_visible():
                         print("Clicking verify button...")
                         await verify_btn.click()
                     else:
                         print("Verify button not found, assuming auto-submit or using main submit...")
                         if submit_btn and await submit_btn.is_visible():
                             print("Re-clicking main submit button...")
                             await submit_btn.click()
                             
                     # Wait for post-verification submit check
                     await page.wait_for_timeout(2000)
                
                # Check URL changes (confirmation page)
                current_url = page.url
                if "thank" in current_url.lower() or "confirm" in current_url.lower():
                     return {"status": "success", "message": "Application submitted (confirmation page detected)."}

                await page.wait_for_timeout(1000)
            
            # Timeout
            current_url = page.url
            try:
                title = await page.title()
            except:
                title = "Unknown"
                
            print(f"Submission timed out. Final URL: {current_url}, Title: {title}")
            
            if "jobs/" in current_url and "thank" not in current_url.lower() and "confirm" not in current_url.lower():
                 return {"status": "unknown", "message": f"Submit clicked but still on job page: {current_url} (possible validation error?)"}

            return {"status": "unknown", "message": f"Submit clicked but confirmation not detected. Final URL: {current_url}"}
            
        except Exception as e:
            print(f"Error during submission check: {e}")
            return {"status": "error", "message": str(e)}

    # Legacy method for backwards compatibility
    async def apply(
        self,
        url: str,
        candidate_data: dict[str, Any],
        submit: bool = False,
        keep_open: bool = False,
        debug_fields: bool = False,
        job_description: str = ""
    ) -> dict[str, Any]:
        """
        Legacy method - applies to a job using the old approach.

        For new code, use analyze_form() + fill_and_submit() instead.
        """
        # Convert candidate_data to expected format
        user_profile = candidate_data

        # Analyze form
        analysis = await self.analyze_form(
            url=url,
            user_profile=user_profile,
            job_description=job_description,
            cached_responses=None
        )

        if analysis.get("status") == "error":
            return analysis

        # Set final values from recommendations
        fields = analysis.get("fields", [])
        for field in fields:
            field["final_value"] = field.get("recommended_value")

        # Fill and optionally submit
        result = await self.fill_and_submit(
            url=url,
            fields=fields,
            expected_fingerprint=None,  # Skip fingerprint check for legacy
            submit=submit
        )

        return result
