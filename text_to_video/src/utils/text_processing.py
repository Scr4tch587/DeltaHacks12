"""Text processing utilities for emotion markers and sentence splitting."""

import re
from typing import List


def strip_emotion_markers(text: str) -> str:
    """
    Remove Fish Audio emotion markers from text.
    
    Emotion markers are in format: (emotion) text here
    This function removes all emotion markers, keeping only the actual text.
    
    Args:
        text: Text that may contain emotion markers
        
    Returns:
        Text with emotion markers removed
    """
    # Remove all emotion markers: (emotion) followed by optional space
    text = re.sub(r'\([^)]+\)\s*', '', text.strip())
    return text


def strip_image_names_from_text(text: str) -> str:
    """
    Remove image names that were incorrectly placed in text.
    
    Image names typically contain underscores and character names like:
    (pretentious_brian), (laughing_peter), (excited_chris)
    
    Valid emotions are single words without underscores like:
    (excited), (confused), (confident)
    
    Args:
        text: Text that may contain image names in parentheses
        
    Returns:
        Text with image names removed (but valid single-word emotions kept)
    """
    # Pattern to match image names: (word_word) or (word_word_word) etc
    # Valid emotions are single words: (word)
    # So we remove anything with underscores or multiple words
    text = re.sub(r'\([^)]*_[^)]+\)\s*', '', text)  # Remove (word_word) patterns
    return text.strip()


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences.
    
    Args:
        text: Text to split
        
    Returns:
        List of sentences
    """
    # Remove emotion markers first
    clean_text = strip_emotion_markers(text)
    
    # Simple sentence splitting on common sentence endings
    # Split on . ! ? followed by space or end of string
    sentences = re.split(r'([.!?]+(?:\s+|$))', clean_text)
    
    # Recombine sentences with their punctuation
    result = []
    i = 0
    while i < len(sentences):
        if i + 1 < len(sentences):
            # Combine sentence with its punctuation
            sentence = (sentences[i] + sentences[i + 1]).strip()
            if sentence:
                result.append(sentence)
            i += 2
        else:
            # Last item without punctuation
            sentence = sentences[i].strip()
            if sentence:
                result.append(sentence)
            i += 1
    
    return result if result else [clean_text]

