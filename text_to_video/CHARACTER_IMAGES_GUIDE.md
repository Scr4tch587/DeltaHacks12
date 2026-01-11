# Character Images Guide

## Required Structure
Each character needs: `assets/characters/{character_name}/default.png` (REQUIRED)

## Image Requirements (3 per character + default)

### Trump
- `default.png` (required)
- `boastful_trump.png` - For bragging, hype, "tremendous" moments
- `aggressive_trump.png` - For insults, pressure, "wrong" moments
- `excited_trump.png` - For "huge" opportunities, winning moments

### Biden
- `default.png` (required)
- `confused_biden.png` - For "what's that?", "is that the thing with the computer?"
- `defensive_biden.png` - For "will you shut up, man", defensive responses
- `surprised_biden.png` - For "come on, man", realization moments

### Obama
- `default.png` (required)
- `calm_obama.png` - For "let me be clear", professional explanations
- `sarcastic_obama.png` - For condescending corrections, "stick to the facts"
- `confident_obama.png` - For technical explanations, strategic points

### Stewie Griffin
- `default.png` (required)
- `exasperated_stewie.png` - Already exists - For frustration, "focus Christopher!"
- `smirking_stewie.png` - Already exists - For condescending, "you imbecile"
- `confident_stewie.png` - For "victory is mine", arrogant acceptance

### Chris Griffin
- `default.png` (required)
- `confused_chris.png` - For "I don't get it", scared responses
- `surprised_chris.png` - Already exists - For "oh wait, that's cool"
- `excited_chris.png` - For "okay I'm listening", acceptance

### Peter Griffin
- `default.png` (required)
- `excited_peter.png` - For "holy crap", "freakin' sweet" moments
- `confused_peter.png` - For misunderstanding tech jargon
- `laughing_peter.png` - For "road house", game show energy

### Brian Griffin
- `default.png` (required)
- `pretentious_brian.png` - For "I'm an artist", dismissive attitude
- `skeptical_brian.png` - For "what's the catch", questioning
- `excited_brian.png` - For "I'll take it", caving in to perks

### Spongebob
- `default.png` (required)
- `excited_spongebob.png` - For "I'M READY!", high energy moments
- `happy_spongebob.png` - For enthusiasm, "best day ever"
- `confident_spongebob.png` - For explaining, "grilled to perfection"

### Patrick
- `default.png` (required)
- `confused_patrick.png` - For "is Python an instrument?", blank stares
- `surprised_patrick.png` - For "wait, I get money?", realization
- `excited_patrick.png` - For "best idea ever", final acceptance

## Image Specifications
- Format: PNG with transparency support
- Size: 800x800px recommended
- Naming: lowercase with underscores (e.g., `excited_trump.png`)

## Notes
- The system will fall back to `default.png` if a specific image doesn't exist
- Start with `default.png` for each character, add variants as needed
- The LLM will select appropriate images based on the conversation context
