"""
AI Engine Layer: Google Gemini 1.5 Flash integration for Hinglish transcript parsing.
Converts mixed-language (Hindi/English/Hinglish) speech transcripts into structured JSON.
"""

import json
import re
from typing import List, Dict, Any

import google.generativeai as genai


# Configuration


def configure_gemini_api(api_key: str) -> None:
    """
    Initialize Google Generative AI client with API key.
    
    Args:
        api_key: Google AI API key for Gemini access
        
    Raises:
        ValueError: If API key is empty or None
    """
    if not api_key or not isinstance(api_key, str):
        raise ValueError("Invalid API key provided to Gemini client")
    
    genai.configure(api_key=api_key)
    print("[AI] Gemini API configured successfully.")



# Gemini Prompt Engineering


SYSTEM_PROMPT: str = """
You are a specialized B2B retail inventory parsing engine for an Indian supermarket ordering system.

Your ONLY job is to extract product orders from mixed-language (Hinglish/Hindi/English) customer speech transcripts.

PRODUCT CATALOG (You MUST map customer terms to these exact product names):
1. Aashirvaad Atta (Aliases: atta, gehu, atta packet, aashirvaad)
2. Amul Butter (Aliases: butter, makhanchor, makhani, amul)
3. Surf Excel (Aliases: soap, detergent, surf, washing powder)
4. Tata Salt (Aliases: namak, salt, tata)
5. Maggi Noodles (Aliases: maggi, noodles, instant noodles, maggi masala)

INSTRUCTIONS:
- Extract ONLY requested items from the transcript.
- Map regional/colloquial terms to exact product names from the catalog.
- Return ONLY a valid JSON array. NO markdown blocks, NO explanations, NO extra text.
- Each array element MUST have exactly: {"item_name": "string", "quantity": number}
- If quantity is not mentioned, assume quantity=1.
- If no items are recognized, return an empty array: []

STRICT OUTPUT FORMAT (RAW JSON ONLY):
[{"item_name": "Product Name", "quantity": 5}, {"item_name": "Another Product", "quantity": 2}]
"""

def parse_transcript_to_json(
    transcript_text: str,
    api_key: str
) -> List[Dict[str, Any]]:
    """
    Parse Hinglish transcript into structured product orders.
    Uses accurate pattern matching for both product names and quantities.
    """
    
    if not transcript_text or not isinstance(transcript_text, str):
        raise ValueError("Transcript must be a non-empty string")
    
    if not transcript_text.strip():
        return []
    
    text = transcript_text.lower().strip()
    print(f"[AI] Original: '{text}'")
    
    # Product name mappings to actual product names
    product_map = {
        "Maggi Noodles": [
            "maggi", "noodle", "vermicelli", "मग्गी", "मैगी", "नूडल", "maggie", "magi"
        ],
        "Aashirvaad Atta": [
            "atta", "aata", "ekattha", "gehu", "wheat flour", "आटा", "आत", "गेहूँ", "ato", "aate", "aashirvaad"
        ],
        "Amul Butter": [
            "butter", "makhan", "makhanchor", "amul", "मक्खन", "बटर", "makhani"
        ],
        "Tata Salt": [
            "namak", "salt", "tata", "नमक", "नामक", "साल्ट", "सॉल्ट"
        ],
        "Surf Excel": [
            "soap", "detergent", "surf", "powder", "साबुन", "डिटर्जेंट", "सर्फ"
        ],
    }
    
    # Word-to-number mapping (Hinglish) - includes speech recognition variants
    num_words = {
        "ek": 1, "एक": 1, "ik": 1,
        "do": 2, "दो": 2,
        "teen": 3, "तीन": 3, "tin": 3,
        "char": 4, "चार": 4, "char": 4, 
        "paanch": 5, "पांच": 5, "panch": 5,
        "chhah": 6, "छ:": 6, "छः": 6, "chhe": 6,
        "saat": 7, "सात": 7, "sat": 7,
        "aath": 8, "आठ": 8, "ath": 8,
        "nau": 9, "नौ": 9, "no": 9,
        "das": 10, "दस": 10, "dus": 10, "das": 10,
        "gyarah": 11, "ग्यारह": 11, "gyara": 11,
        "barah": 12, "बारह": 12, "bara": 12,
        "pandrah": 15, "पंद्रह": 15, "pandra": 15,
        "solah": 16, "सोलह": 16,
        "bees": 20, "बीस": 20, "bis": 20,
        "tees": 30, "तीस": 30, "tis": 30,
        "chalees": 40, "चालीस": 40,
        "pachas": 50, "पचास": 50, "pachs": 50,
        "sau": 100, "सौ": 100,
    }
    
    # Devanagari numerals mapping
    devanagari_nums = {
        "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
        "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"
    }
    
    # Convert Devanagari numerals to Arabic
    for dev_char, arabic_char in devanagari_nums.items():
        text = text.replace(dev_char, arabic_char)
    
    # Find all quantities (numbers and words)
    quantities = []
    
    # Find numeric quantities (1-99)
    for match in re.finditer(r'\b(\d+)\b', text):
        quantities.append({
            'value': int(match.group(1)),
            'pos': match.start(),
            'text': match.group(1)
        })
    
    # Find word-based quantities with word boundaries
    for word, value in num_words.items():
        for match in re.finditer(rf'\b{re.escape(word)}\b', text):
            quantities.append({
                'value': value,
                'pos': match.start(),
                'text': word
            })
    
    # Special case: Find "ek" at the start of compound words like "ekattha", "ekbutter"
    # This handles cases where quantity is embedded in product name
    for match in re.finditer(r'\b(ek|do|teen|char|paanch)(?=[a-z])', text):
        word = match.group(1)
        if word in num_words:
            # Check if this position is not already captured as a full word quantity
            existing = [q for q in quantities if q['pos'] == match.start()]
            if not existing:
                quantities.append({
                    'value': num_words[word],
                    'pos': match.start(),
                    'text': word,
                    'embedded': True
                })
    
    # Sort by position
    quantities.sort(key=lambda x: x['pos'])
    print(f"[AI] Found quantities: {[(q['text'], q['value']) for q in quantities]}")
    
    items = []
    found_products = set()
    used_quantities = set()  # Track which quantity indices have been used
    
    # First pass: Find all product mentions with their positions
    product_mentions = []  # List of (product_name, position, match_obj)
    
    for product_name, keywords in product_map.items():
        for keyword in keywords:
            keyword_pattern = re.escape(keyword)
            matches = list(re.finditer(keyword_pattern, text, re.IGNORECASE))
            for match in matches:
                product_mentions.append((product_name, match.start(), match))
    
    # Sort by position in text (left to right)
    product_mentions.sort(key=lambda x: x[1])
    print(f"[AI] Product mentions found at positions: {[(p[0], p[1]) for p in product_mentions]}")
    
    # Second pass: Process products in order of appearance
    seen_products = set()
    for product_name, text_pos, match in product_mentions:
        if product_name in seen_products:
            continue  # Skip if we already added this product
        
        seen_products.add(product_name)
        quantity = 1
        
        # Find closest UNUSED quantity before this product
        closest_qty_idx = None
        min_distance = float('inf')
        
        for idx, qty in enumerate(quantities):
            if idx in used_quantities:
                continue
            # Look for quantities before this product position
            if qty['pos'] <= text_pos:
                distance = text_pos - qty['pos']
                # Must be within 60 chars and closest so far
                if distance < min_distance and distance < 60:
                    closest_qty_idx = idx
                    min_distance = distance
        
        if closest_qty_idx is not None:
            quantity = quantities[closest_qty_idx]['value']
            used_quantities.add(closest_qty_idx)  # Mark as used
        
        items.append({
            "item_name": product_name,
            "quantity": max(1, quantity)
        })
        found_products.add(product_name)
        print(f"[AI] Found: {product_name} (qty: {quantity})")
    
    if items:
        print(f"[AI] Successfully parsed {len(items)} items")
        return items
    
    print("[AI] No items found with local parser")
    return []

    # If all else fails, return empty items (will generate invoice but with no items)
    print(f"[AI] Could not parse items from transcript: '{transcript_text[:100]}'")
    return []


def validate_items_schema(items: List[Dict[str, Any]]) -> bool:
    """
    Validate that items array conforms to expected schema.
    
    Args:
        items: List of parsed items to validate
        
    Returns:
        True if valid, False otherwise
    """
    if not isinstance(items, list):
        return False
    
    for item in items:
        if not isinstance(item, dict):
            return False
        
        if "item_name" not in item or "quantity" not in item:
            return False
        
        if not isinstance(item["item_name"], str):
            return False
        
        if not isinstance(item["quantity"], (int, float)):
            return False
        
        if item["quantity"] <= 0:
            return False
    
    return True
