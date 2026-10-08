# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import json
import math
import os
from typing import Any, Dict, List, Optional
import urllib.request
import uuid
from zoneinfo import ZoneInfo

from google import genai
from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.cloud import firestore
from google.cloud import storage
from google.genai import types

from .a2ui_prompt import A2UI_INSTRUCTION
from .a2ui_utils import a2ui_callback

GCP_PROJECT_ID = "qwiklabs-gcp-03-b7b4fdff7b64"
STORAGE_BUCKET_NAME = "roampoint-concierge-assets-11836"
MODEL = "gemini-3.8-flash"

db = firestore.Client(project=GCP_PROJECT_ID)
storage_client = storage.Client(project=GCP_PROJECT_ID)
genai_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")


def search_flight_deals(
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    cabin_class: Optional[str] = None,
    max_points: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Search award flight deals from the Firestore catalog.

    Args:
        origin: Optional 3-letter airport code (e.g. 'JFK', 'SFO', 'ORD', 'MIA', 'LAX') or city name.
        destination: Optional 3-letter airport code (e.g. 'CDG', 'HND', 'LHR', 'MAD', 'SYD') or city name.
        cabin_class: Optional cabin class ('economy' or 'business').
        max_points: Optional maximum points/miles required.

    Returns:
        A list of matching flight deals with points cost, cash copay, airline program, and CPP valuation.
    """
    collection_ref = db.collection("flight_deals")
    docs = collection_ref.stream()

    deals = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id

        if origin:
            org = origin.strip().upper()
            if org != data.get("origin", "").upper() and org not in data.get("origin_city", "").upper():
                continue

        if destination:
            dst = destination.strip().upper()
            if dst != data.get("destination", "").upper() and dst not in data.get("destination_city", "").upper():
                continue

        if cabin_class:
            if cabin_class.strip().lower() != data.get("cabin_class", "").lower():
                continue

        if max_points is not None:
            if data.get("points_cost", 0) > max_points:
                continue

        deals.append(data)

    return deals


def save_flight_deal(
    origin: str,
    destination: str,
    airline: str,
    program: str,
    cabin_class: str,
    points_cost: int,
    cash_copay_usd: float,
    cash_fare_usd: float,
    description: str,
    origin_city: Optional[str] = None,
    destination_city: Optional[str] = None,
    transfer_sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Save or create a new award flight deal to the Firestore catalog.

    Args:
        origin: 3-letter airport code (e.g. 'JFK').
        destination: 3-letter airport code (e.g. 'CDG').
        airline: Operating airline (e.g. 'Air France').
        program: Frequent flyer program to book through (e.g. 'Flying Blue').
        cabin_class: Cabin class, typically 'economy' or 'business'.
        points_cost: Points/miles cost.
        cash_copay_usd: Taxes and fees copay in USD.
        cash_fare_usd: Equivalent cash ticket price in USD.
        description: Summary or details of the flight deal.
        origin_city: Optional city name of origin.
        destination_city: Optional city name of destination.
        transfer_sources: Optional list of transfer partners (e.g. ['Chase', 'Capital One']).

    Returns:
        A dictionary confirming the deal was saved with its calculated CPP and document ID.
    """
    net_cash = max(0.0, cash_fare_usd - cash_copay_usd)
    cpp = round((net_cash / points_cost) * 100, 2) if points_cost > 0 else 0.0

    doc_id = f"deal-{origin.lower()}-{destination.lower()}-{cabin_class.lower()[:3]}-{points_cost}"
    deal_data = {
        "id": doc_id,
        "origin": origin.strip().upper(),
        "origin_city": origin_city or origin.strip().upper(),
        "destination": destination.strip().upper(),
        "destination_city": destination_city or destination.strip().upper(),
        "airline": airline.strip(),
        "program": program.strip(),
        "transfer_sources": transfer_sources or ["Chase", "Capital One"],
        "cabin_class": cabin_class.strip().lower(),
        "points_cost": points_cost,
        "cash_copay_usd": float(cash_copay_usd),
        "cash_fare_usd": float(cash_fare_usd),
        "cpp": cpp,
        "description": description.strip(),
    }

    db.collection("flight_deals").document(doc_id).set(deal_data)
    return {"status": "success", "id": doc_id, "deal": deal_data}


TRANSFER_PARTNERS_DB = [
    {
        "program": "Virgin Atlantic Flying Club",
        "alliances_and_partners": ["SkyTeam", "ANA", "Delta", "Air France-KLM"],
        "bank_partners": [
            {
                "bank": "Chase Ultimate Rewards",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 30,
                "notes": "30% transfer bonus active through end of month (1,000 Chase pts = 1,300 Virgin pts).",
            },
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 transfer ratio.",
            },
        ],
        "sweet_spots": [
            "ANA Business Class (US West Coast to Tokyo for 47,500 pts one-way)",
            "Delta One Business Class US to Europe (from 50,000 pts with low fees)",
        ],
    },
    {
        "program": "Air France-KLM Flying Blue",
        "alliances_and_partners": ["SkyTeam", "Delta", "Virgin Atlantic"],
        "bank_partners": [
            {
                "bank": "Chase Ultimate Rewards",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 instant transfer.",
            },
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 20,
                "notes": "20% transfer bonus active (1,000 CapOne miles = 1,200 Flying Blue miles).",
            },
        ],
        "sweet_spots": [
            "US to Europe Business Class starting at 50,000 miles",
            "Monthly Promo Rewards with up to 25% off award redemptions",
        ],
    },
    {
        "program": "Air Canada Aeroplan",
        "alliances_and_partners": ["Star Alliance", "United", "Lufthansa", "Singapore Airlines", "Emirates", "Etihad"],
        "bank_partners": [
            {
                "bank": "Chase Ultimate Rewards",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 transfer. Chase Aeroplan cardholders also receive 10% bonus on 50k+ transfers.",
            },
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 instant transfer.",
            },
        ],
        "sweet_spots": [
            "Extensive partner network with no carrier-imposed fuel surcharges",
            "US to Europe/Asia starting at 60,000-75,000 miles in Business Class",
        ],
    },
    {
        "program": "British Airways Executive Club (Avios)",
        "alliances_and_partners": ["oneworld", "American Airlines", "Alaska Airlines", "Qatar Airways", "Iberia", "Finnair"],
        "bank_partners": [
            {
                "bank": "Chase Ultimate Rewards",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 instant transfer.",
            },
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 0,
                "notes": "Standard 1:1 instant transfer. Avios can be freely combined with Iberia, Qatar, and Finnair.",
            },
        ],
        "sweet_spots": [
            "Short-haul flights on American or Alaska Airlines starting at 8,250 Avios",
            "Off-peak transatlantic flights on Iberia (e.g. JFK/BOS/ORD to Madrid from 34,000 Avios in Business)",
        ],
    },
    {
        "program": "Avianca LifeMiles",
        "alliances_and_partners": ["Star Alliance", "United", "Lufthansa", "ANA", "Swiss", "EVA Air"],
        "bank_partners": [
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "Instant",
                "current_bonus_pct": 15,
                "notes": "15% transfer bonus active (1,000 CapOne miles = 1,150 LifeMiles).",
            },
        ],
        "sweet_spots": [
            "No fuel surcharges on Star Alliance partners",
            "US to Europe Business Class for 63,000 LifeMiles",
        ],
    },
    {
        "program": "Singapore Airlines KrisFlyer",
        "alliances_and_partners": ["Star Alliance", "United", "Lufthansa", "Air New Zealand"],
        "bank_partners": [
            {
                "bank": "Chase Ultimate Rewards",
                "ratio": "1:1",
                "transfer_time": "12-24 hours",
                "current_bonus_pct": 0,
                "notes": "1:1 transfer, typically completes within 24 hours.",
            },
            {
                "bank": "Capital One Miles",
                "ratio": "1:1",
                "transfer_time": "12-24 hours",
                "current_bonus_pct": 0,
                "notes": "1:1 transfer, typically completes within 24 hours.",
            },
        ],
        "sweet_spots": [
            "Access to Singapore Airlines premium long-haul Suites and Business class inventory",
        ],
    },
]


def find_transfer_routes(
    program_or_airline: str,
    bank: Optional[str] = None,
) -> Dict[str, Any]:
    """Find bank point transfer routes, transfer times, ratios, and active bonuses for an airline or frequent flyer program.

    Args:
        program_or_airline: Name of the airline or loyalty program (e.g. 'Virgin Atlantic', 'Air France', 'Flying Blue', 'ANA', 'British Airways', 'Aeroplan').
        bank: Optional bank filter (e.g. 'Chase' or 'Capital One').

    Returns:
        A dictionary with matching loyalty programs, their eligible bank transfer partners, current bonuses, transfer speeds, and sweet spots.
    """
    query = program_or_airline.strip().lower()
    bank_filter = bank.strip().lower() if bank else None

    matched_routes = []
    for item in TRANSFER_PARTNERS_DB:
        name_match = (
            query in item["program"].lower()
            or any(query in partner.lower() for partner in item["alliances_and_partners"])
        )
        if not name_match:
            continue

        partners = item["bank_partners"]
        if bank_filter:
            partners = [p for p in partners if bank_filter in p["bank"].lower()]

        if partners:
            matched_routes.append({
                "loyalty_program": item["program"],
                "alliances_and_key_partners": item["alliances_and_partners"],
                "eligible_bank_partners": partners,
                "top_sweet_spots": item["sweet_spots"],
            })

    return {
        "query": program_or_airline,
        "bank_filter": bank,
        "count": len(matched_routes),
        "routes": matched_routes,
    }


def get_live_exchange_rate(
    amount: float,
    from_currency: str = "USD",
    to_currency: str = "EUR",
) -> Dict[str, Any]:
    """Get live foreign exchange rates and convert international flight taxes, copays, or local hotel prices using the Frankfurter public API.

    Args:
        amount: The monetary amount to convert.
        from_currency: 3-letter currency code to convert from (e.g., 'USD', 'EUR', 'GBP', 'JPY', 'CAD', 'AUD').
        to_currency: 3-letter currency code to convert to (e.g., 'EUR', 'GBP', 'JPY', 'AUD', 'USD').

    Returns:
        A dictionary with live conversion details, rate, date, and source currency.
    """
    base = from_currency.strip().upper()
    target = to_currency.strip().upper()

    # Frankfurter is an open, free public API listed in public-apis (rates published by European Central Bank)
    api_url = f"https://api.frankfurter.app/latest?amount={amount}&from={base}&to={target}"

    req = urllib.request.Request(
        api_url,
        headers={"User-Agent": "RoamPointConcierge/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
            converted_amount = payload.get("rates", {}).get(target)
            return {
                "source": "Frankfurter (European Central Bank)",
                "date": payload.get("date"),
                "base_currency": base,
                "target_currency": target,
                "original_amount": amount,
                "converted_amount": converted_amount,
                "rate": round(converted_amount / amount, 4) if amount > 0 and converted_amount else None,
            }
    except Exception as e:
        return {
            "error": f"Failed to fetch live exchange rate: {str(e)}",
            "base_currency": base,
            "target_currency": target,
            "original_amount": amount,
        }


AIRPORTS_COORDINATES: Dict[str, Dict[str, Any]] = {
    "JFK": {"name": "John F. Kennedy International Airport", "city": "New York", "country": "USA", "lat": 40.6413, "lon": -73.7781},
    "EWR": {"name": "Newark Liberty International Airport", "city": "New York / Newark", "country": "USA", "lat": 40.6895, "lon": -74.1745},
    "LGA": {"name": "LaGuardia Airport", "city": "New York", "country": "USA", "lat": 40.7769, "lon": -73.8740},
    "SFO": {"name": "San Francisco International Airport", "city": "San Francisco", "country": "USA", "lat": 37.6213, "lon": -122.3790},
    "LAX": {"name": "Los Angeles International Airport", "city": "Los Angeles", "country": "USA", "lat": 33.9416, "lon": -118.4085},
    "ORD": {"name": "O'Hare International Airport", "city": "Chicago", "country": "USA", "lat": 41.9742, "lon": -87.9073},
    "MIA": {"name": "Miami International Airport", "city": "Miami", "country": "USA", "lat": 25.7959, "lon": -80.2870},
    "BOS": {"name": "Logan International Airport", "city": "Boston", "country": "USA", "lat": 42.3656, "lon": -71.0096},
    "SEA": {"name": "Seattle-Tacoma International Airport", "city": "Seattle", "country": "USA", "lat": 47.4502, "lon": -122.3088},
    "DFW": {"name": "Dallas/Fort Worth International Airport", "city": "Dallas", "country": "USA", "lat": 32.8998, "lon": -97.0403},
    "CDG": {"name": "Paris Charles de Gaulle Airport", "city": "Paris", "country": "France", "lat": 49.0097, "lon": 2.5479},
    "LHR": {"name": "London Heathrow Airport", "city": "London", "country": "United Kingdom", "lat": 51.4700, "lon": -0.4543},
    "HND": {"name": "Tokyo Haneda Airport", "city": "Tokyo", "country": "Japan", "lat": 35.5494, "lon": 139.7798},
    "NRT": {"name": "Narita International Airport", "city": "Tokyo", "country": "Japan", "lat": 35.7720, "lon": 140.3929},
    "MAD": {"name": "Adolfo Suárez Madrid–Barajas Airport", "city": "Madrid", "country": "Spain", "lat": 40.4839, "lon": -3.5680},
    "SYD": {"name": "Sydney Kingsford Smith Airport", "city": "Sydney", "country": "Australia", "lat": -33.9399, "lon": 151.1753},
    "SIN": {"name": "Singapore Changi Airport", "city": "Singapore", "country": "Singapore", "lat": 1.3644, "lon": 103.9915},
    "DXB": {"name": "Dubai International Airport", "city": "Dubai", "country": "United Arab Emirates", "lat": 25.2532, "lon": 55.3657},
    "FRA": {"name": "Frankfurt Airport", "city": "Frankfurt", "country": "Germany", "lat": 50.0379, "lon": 8.5622},
    "AMS": {"name": "Amsterdam Airport Schiphol", "city": "Amsterdam", "country": "Netherlands", "lat": 52.3105, "lon": 4.7683},
}


CITY_TO_PRIMARY_AIRPORT = {
    "NEW YORK": "JFK",
    "NYC": "JFK",
    "SAN FRANCISCO": "SFO",
    "SF": "SFO",
    "BAY AREA": "SFO",
    "LOS ANGELES": "LAX",
    "LA": "LAX",
    "CHICAGO": "ORD",
    "MIAMI": "MIA",
    "BOSTON": "BOS",
    "SEATTLE": "SEA",
    "DALLAS": "DFW",
    "PARIS": "CDG",
    "LONDON": "LHR",
    "TOKYO": "HND",
    "MADRID": "MAD",
    "SYDNEY": "SYD",
    "SINGAPORE": "SIN",
    "DUBAI": "DXB",
    "FRANKFURT": "FRA",
    "AMSTERDAM": "AMS",
}


def resolve_airport_code(input_str: str) -> Optional[str]:
    """Resolve an input string (IATA code, city name, or nickname) to a 3-letter IATA airport code."""
    cleaned = input_str.strip().upper()
    if cleaned in AIRPORTS_COORDINATES:
        return cleaned

    # Check city to primary airport mapping
    if cleaned in CITY_TO_PRIMARY_AIRPORT:
        return CITY_TO_PRIMARY_AIRPORT[cleaned]

    # Partial city match
    for city_key, airport_code in CITY_TO_PRIMARY_AIRPORT.items():
        if city_key in cleaned or cleaned in city_key:
            return airport_code

    # Search through AIRPORTS_COORDINATES city field
    for code, info in AIRPORTS_COORDINATES.items():
        if cleaned in info["city"].upper():
            return code

    return None


def lookup_airport_and_distance(
    origin: str,
    destination: str,
) -> Dict[str, Any]:
    """Calculate the Great Circle flight distance between two airport codes or city names and determine award mileage distance tiers.

    If a city name is provided instead of a 3-letter IATA code, it makes a best-guess match to the primary international airport.

    Args:
        origin: 3-letter IATA airport code or city name for departure (e.g. 'JFK', 'SFO', 'New York', 'Tokyo').
        destination: 3-letter IATA airport code or city name for arrival (e.g. 'LHR', 'CDG', 'Paris', 'London').

    Returns:
        A dictionary with origin/destination airport details, distance in statute miles and kilometers,
        flight duration estimate, and applicable Avios / distance award tiers.
    """
    org_code = resolve_airport_code(origin) or origin.strip().upper()
    dst_code = resolve_airport_code(destination) or destination.strip().upper()

    org_info = AIRPORTS_COORDINATES.get(org_code)
    dst_info = AIRPORTS_COORDINATES.get(dst_code)

    if not org_info or not dst_info:
        missing = []
        if not org_info:
            missing.append(f"origin '{origin}' (resolved to '{org_code}')")
        if not dst_info:
            missing.append(f"destination '{destination}' (resolved to '{dst_code}')")
        return {
            "error": f"Airport code(s) or city not recognized in directory: {', '.join(missing)}",
            "supported_airports": list(AIRPORTS_COORDINATES.keys()),
        }

    # Haversine formula for Great Circle distance in statute miles
    lat1, lon1 = math.radians(org_info["lat"]), math.radians(org_info["lon"])
    lat2, lon2 = math.radians(dst_info["lat"]), math.radians(dst_info["lon"])
    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    radius_miles = 3958.8
    distance_miles = round(radius_miles * c)
    distance_km = round(distance_miles * 1.60934)

    # Estimate nonstop flight hours (~500 mph cruise speed + 30 min takeoff/landing)
    estimated_flight_hours = round((distance_miles / 500.0) + 0.5, 1)

    # Mileage band mapping for distance-based programs (e.g. British Airways Avios)
    if distance_miles <= 650:
        avios_zone = "Zone 1 (1 - 650 miles)"
        avios_economy_offpeak = 6000
        avios_business_offpeak = 12500
    elif distance_miles <= 1150:
        avios_zone = "Zone 2 (651 - 1,150 miles)"
        avios_economy_offpeak = 9000
        avios_business_offpeak = 16500
    elif distance_miles <= 2000:
        avios_zone = "Zone 3 (1,151 - 2,000 miles)"
        avios_economy_offpeak = 11000
        avios_business_offpeak = 22000
    elif distance_miles <= 3000:
        avios_zone = "Zone 4 (2,001 - 3,000 miles)"
        avios_economy_offpeak = 13000
        avios_business_offpeak = 38750
    elif distance_miles <= 4000:
        avios_zone = "Zone 5 (3,001 - 4,000 miles - Transatlantic)"
        avios_economy_offpeak = 13000
        avios_business_offpeak = 50000
    elif distance_miles <= 5500:
        avios_zone = "Zone 6 (4,001 - 5,500 miles)"
        avios_economy_offpeak = 20750
        avios_business_offpeak = 62000
    else:
        avios_zone = "Zone 7+ (5,501+ miles - Ultra Long Haul)"
        avios_economy_offpeak = 25750
        avios_business_offpeak = 80000

    return {
        "origin": {"code": org_code, **org_info},
        "destination": {"code": dst_code, **dst_info},
        "distance_miles": distance_miles,
        "distance_km": distance_km,
        "estimated_flight_time": f"{estimated_flight_hours} hours",
        "distance_award_tier": {
            "avios_zone": avios_zone,
            "typical_economy_avios": avios_economy_offpeak,
            "typical_business_avios": avios_business_offpeak,
            "notes": "Avios distance bands apply to British Airways, Iberia, and Qatar Airways award flights.",
        },
    }


async def generate_destination_image(
    prompt: str,
    tool_context: ToolContext,
) -> Dict[str, Any]:
    """Generate a destination travel visual or award cabin inspiration image.

    Uses the gemini-3.1-flash-lite-image model in the global region.
    Saves the generated image to session artifacts so it displays in the Playground Artifacts panel,
    and uploads the image bytes to public Cloud Storage, returning its public https URL.

    Args:
        prompt: Detailed description of the travel visual, destination landmark, skyline, or premium flight cabin experience to generate.
        tool_context: ADK ToolContext used to save the artifact for the session.

    Returns:
        A dictionary with the public image URL, artifact filename, and prompt details.
    """
    image_prompt = f"High quality cinematic travel photograph: {prompt.strip()}"

    response = genai_client.models.generate_content(
        model="gemini-3.1-flash-lite-image",
        contents=image_prompt,
    )

    image_bytes = None
    mime_type = "image/jpeg"

    if response.candidates and response.candidates[0].content:
        for part in response.candidates[0].content.parts:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                image_bytes = part.inline_data.data
                if part.inline_data.mime_type:
                    mime_type = part.inline_data.mime_type
                break

    if not image_bytes:
        return {"error": "No image data was generated by the model.", "prompt": prompt}

    file_extension = "png" if "png" in mime_type else "jpg"
    unique_id = uuid.uuid4().hex[:8]
    filename = f"destination-{unique_id}.{file_extension}"

    # (1) Save artifact for Playground Artifacts panel
    artifact_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    artifact_version = await tool_context.save_artifact(
        filename=filename,
        artifact=artifact_part,
        custom_metadata={"prompt": prompt, "model": "gemini-3.1-flash-lite-image"},
    )

    # (2) Upload image bytes to public Cloud Storage bucket
    bucket = storage_client.bucket(STORAGE_BUCKET_NAME)
    blob = bucket.blob(filename)
    blob.upload_from_string(image_bytes, content_type=mime_type)

    public_url = f"https://storage.googleapis.com/{STORAGE_BUCKET_NAME}/{filename}"

    return {
        "status": "success",
        "public_image_url": public_url,
        "artifact_filename": filename,
        "artifact_version": artifact_version,
        "mime_type": mime_type,
        "prompt": prompt,
    }


def get_weather(query: str) -> str:
    """Simulates a web search. Use it get information on weather.

    Args:
        query: A string containing the location to get weather information for.

    Returns:
        A string with the simulated weather information for the queried location.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        return "It's 60 degrees and foggy."
    return "It's 90 degrees and sunny."


def get_current_time(query: str) -> str:
    """Simulates getting the current time for a city.

    Args:
        query: The name of the city to get the current time for.

    Returns:
        A string with the current time information.
    """
    if "sf" in query.lower() or "san francisco" in query.lower():
        tz_identifier = "America/Los_Angeles"
    else:
        return f"Sorry, I don't have timezone information for query: {query}."

    tz = ZoneInfo(tz_identifier)
    now = datetime.datetime.now(tz)
    return f"The current time for query {query} is {now.strftime('%Y-%m-%d %H:%M:%S %Z%z')}"


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=A2UI_INSTRUCTION,
    tools=[
        search_flight_deals,
        save_flight_deal,
        lookup_airport_and_distance,
        find_transfer_routes,
        get_live_exchange_rate,
        generate_destination_image,
        get_weather,
        get_current_time,
    ],
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
