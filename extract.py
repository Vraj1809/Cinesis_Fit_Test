"""
Cinesis Good Fit Test — Part A: Extract structured driver profile from transcript.

This module handles non-deterministic extraction safely by using temperature=0,
schema validation, bounds checking, and the official Anthropic SDK for automatic 
retries on transient API failures (e.g., HTTP 529).
"""

import json
import logging
import os
import sys
from dataclasses import dataclass
import anthropic

logger = logging.getLogger(__name__)

# --- Configuration ---
MODEL = "claude-3-5-sonnet-20240620"  # Assuming standard naming convention
MAX_TOKENS = 1024
EXTRACTION_TEMPERATURE = 0


@dataclass
class DriverProfile:
    current_location: str
    current_lat: float
    current_lon: float
    home_base: str
    home_lat: float
    home_lon: float
    min_rate_per_mile: float
    equipment_types: tuple
    weight_capacity_lb: float
    weight_capacity_note: str = ""


def build_extraction_prompt(transcript: str) -> str:
    """Builds the extraction prompt dynamically around the provided transcript."""
    return f"""
You are a freight dispatch AI. Read the following phone call transcript between a dispatcher and a truck driver.
Extract the driver profile as a JSON object with EXACTLY these fields:

{{
  "current_location": "City, ST",
  "current_lat": float,
  "current_lon": float,
  "home_base": "City, ST",
  "home_lat": float,
  "home_lon": float,
  "min_rate_per_mile": float,
  "equipment_types": ["type1", "type2"],
  "weight_capacity_lb": float,
  "weight_capacity_note": "explanation of how you inferred this"
}}

Rules:
- current_location: where the driver physically is RIGHT NOW
- home_base: where the driver is normally based
- lat/lon: standard decimal degrees for the cities (e.g., New York City NY ≈ 40.7128, -74.0060; Los Angeles CA ≈ 34.0522, -118.2437). Use your geographic knowledge to determine coordinates for whatever cities appear.
- min_rate_per_mile: the minimum $/mile the driver will accept (as a float, e.g. 2.0)
- equipment_types: list of trailer types the driver runs, all lowercase (e.g. ["hotshot", "gooseneck"])
- weight_capacity_lb: infer from equipment type if not stated. A hotshot gooseneck typically handles up to ~16,500 lb of cargo.
- weight_capacity_note: explain your inference

Return ONLY valid JSON. No preamble, no markdown fences.

TRANSCRIPT:
{transcript}
"""


def _validate_profile(parsed: dict) -> None:
    """Validates the extracted JSON to prevent silent downstream corruption."""
    lat, lon = float(parsed["current_lat"]), float(parsed["current_lon"])
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        raise ValueError(f"Current coordinates ({lat}, {lon}) are out of range.")
        
    hlat, hlon = float(parsed["home_lat"]), float(parsed["home_lon"])
    if not (-90 <= hlat <= 90) or not (-180 <= hlon <= 180):
        raise ValueError(f"Home coordinates ({hlat}, {hlon}) are out of range.")
        
    rate = float(parsed["min_rate_per_mile"])
    if rate <= 0:
        raise ValueError(f"min_rate_per_mile must be positive, got {rate}")
        
    equipment = parsed.get("equipment_types", [])
    if not equipment:
        raise ValueError("equipment_types is empty — extraction failed to identify trailer types.")
        
    capacity = float(parsed["weight_capacity_lb"])
    if capacity <= 0:
        raise ValueError(f"weight_capacity_lb must be positive, got {capacity}")


def extract_profile_via_llm(api_key: str, transcript: str) -> DriverProfile:
    """Calls Anthropic SDK to extract the profile and validates the result."""
    client = anthropic.Anthropic(api_key=api_key)
    
    logger.info("Calling Anthropic API for profile extraction...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        temperature=EXTRACTION_TEMPERATURE,
        messages=[{"role": "user", "content": build_extraction_prompt(transcript)}],
    )
    
    # Safely handle the response block (checking for 'text' block type)
    text_blocks = [b.text for b in response.content if b.type == "text"]
    if not text_blocks:
        raise ValueError(
            f"No text block in API response. Stop reason: {response.stop_reason}. "
            f"Content types: {[b.type for b in response.content]}"
        )
        
    raw = text_blocks[0].strip()
    parsed = json.loads(raw)
    
    # Validate the data before trusting it
    _validate_profile(parsed)
    
    return DriverProfile(
        current_location=parsed["current_location"],
        current_lat=float(parsed["current_lat"]),
        current_lon=float(parsed["current_lon"]),
        home_base=parsed["home_base"],
        home_lat=float(parsed["home_lat"]),
        home_lon=float(parsed["home_lon"]),
        min_rate_per_mile=float(parsed["min_rate_per_mile"]),
        equipment_types=tuple(e.lower() for e in parsed["equipment_types"]),
        weight_capacity_lb=float(parsed["weight_capacity_lb"]),
        weight_capacity_note=parsed.get("weight_capacity_note", ""),
    )


def get_driver_profile(transcript: str) -> DriverProfile:
    """
    Retrieve the driver profile from the transcript.
    The API key is read from the ANTHROPIC_API_KEY environment variable.
    Raises EnvironmentError if the key is absent.
    Raises RuntimeError if the LLM call or JSON parsing fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Set it before running this script."
        )
        
    try:
        profile = extract_profile_via_llm(api_key, transcript)
        logger.info("LLM extraction and validation succeeded.")
        return profile
    except Exception as e:
        logger.error(f"Failed to extract profile: {e}")
        raise RuntimeError(f"LLM extraction failed: {e}") from e


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    
    # Provide a sample transcript for local testing if not piped via stdin
    SAMPLE_TRANSCRIPT = """
    Driver: Like, tell me a little bit about how y'all can assist me.
    Dispatch: I think you're based out in San Antonio. Is that correct?
    Driver: Yes, that's correct. I'm usually in that area, but I'm in Dallas.
    Dispatch: I've got one coming out of San Antonio to Huntsville...
    Driver: Do y'all deal with hotshots too, like flatbeds or goosenecks?
    Dispatch: Yes, we work with hotshots.
    Driver: I might only run two or three days a week, but I still make good money—like $2,300 to $2,500 going Corpus to Odessa, or $1,800 to $2,000 from San Antonio to Midland. I run a hotshot gooseneck trailer.
    Driver: As long as it's above $2 per mile, I'll consider it.
    """
    
    if not sys.stdin.isatty():
        transcript_text = sys.stdin.read()
    else:
        logger.warning(
            "\n*** NO TRANSCRIPT PROVIDED VIA STDIN ***\n"
            "To test extraction with a live file, you can pipe it in (e.g., `cat transcript.txt | python extract.py`).\n"
            "Falling back to the embedded sample transcript string to continue execution...\n"
        )
        transcript_text = SAMPLE_TRANSCRIPT
        
    p = get_driver_profile(transcript_text)
    
    # Use print for intended program output
    print(f"\nDriver Profile")
    print(f"  Current location : {p.current_location}  ({p.current_lat}, {p.current_lon})")
    print(f"  Home base        : {p.home_base}  ({p.home_lat}, {p.home_lon})")
    print(f"  Min rate/mile    : ${p.min_rate_per_mile:.2f}")
    print(f"  Equipment        : {', '.join(p.equipment_types)}")
    print(f"  Weight capacity  : {p.weight_capacity_lb:,.0f} lb")
    print(f"  Weight note      : {p.weight_capacity_note}")