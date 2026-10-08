# Copyright 2026 Google LLC
# Seed script for RoamPoint Concierge Firestore database

from google.cloud import firestore

GCP_PROJECT_ID = "qwiklabs-gcp-03-b7b4fdff7b64"

SEEDED_FLIGHT_DEALS = [
    {
        "id": "deal-jfk-cdg-af-biz",
        "origin": "JFK",
        "origin_city": "New York",
        "destination": "CDG",
        "destination_city": "Paris",
        "airline": "Air France",
        "program": "Flying Blue",
        "transfer_sources": ["Chase", "Capital One"],
        "cabin_class": "business",
        "points_cost": 50000,
        "cash_copay_usd": 210.0,
        "cash_fare_usd": 2850.0,
        "cpp": 5.28,
        "available_seats": 4,
        "flight_duration": "7h 20m",
        "stops": 0,
        "description": "Direct lie-flat business class on the A350 from JFK to Paris.",
    },
    {
        "id": "deal-sfo-hnd-ana-biz",
        "origin": "SFO",
        "origin_city": "San Francisco",
        "destination": "HND",
        "destination_city": "Tokyo",
        "airline": "ANA",
        "program": "Virgin Atlantic",
        "transfer_sources": ["Chase", "Capital One"],
        "cabin_class": "business",
        "points_cost": 47500,
        "cash_copay_usd": 265.0,
        "cash_fare_usd": 3900.0,
        "cpp": 7.65,
        "available_seats": 2,
        "flight_duration": "11h 15m",
        "stops": 0,
        "description": "ANA The Room business class booked via Virgin Atlantic Flying Club.",
    },
    {
        "id": "deal-ord-lhr-ba-econ",
        "origin": "ORD",
        "origin_city": "Chicago",
        "destination": "LHR",
        "destination_city": "London",
        "airline": "British Airways",
        "program": "British Airways Executive Club",
        "transfer_sources": ["Chase", "Capital One"],
        "cabin_class": "economy",
        "points_cost": 15000,
        "cash_copay_usd": 120.0,
        "cash_fare_usd": 680.0,
        "cpp": 3.73,
        "available_seats": 9,
        "flight_duration": "8h 05m",
        "stops": 0,
        "description": "Off-peak economy award from Chicago to London Heathrow.",
    },
    {
        "id": "deal-mia-mad-ib-biz",
        "origin": "MIA",
        "origin_city": "Miami",
        "destination": "MAD",
        "destination_city": "Madrid",
        "airline": "Iberia",
        "program": "British Airways Executive Club",
        "transfer_sources": ["Chase"],
        "cabin_class": "business",
        "points_cost": 34000,
        "cash_copay_usd": 140.0,
        "cash_fare_usd": 2200.0,
        "cpp": 6.06,
        "available_seats": 3,
        "flight_duration": "8h 45m",
        "stops": 0,
        "description": "High-value sweet spot business class nonstop from Miami to Madrid.",
    },
    {
        "id": "deal-lax-syd-qf-biz",
        "origin": "LAX",
        "origin_city": "Los Angeles",
        "destination": "SYD",
        "destination_city": "Sydney",
        "airline": "Qantas",
        "program": "Air Canada Aeroplan",
        "transfer_sources": ["Chase", "Capital One"],
        "cabin_class": "business",
        "points_cost": 75000,
        "cash_copay_usd": 90.0,
        "cash_fare_usd": 4800.0,
        "cpp": 6.28,
        "available_seats": 2,
        "flight_duration": "15h 00m",
        "stops": 0,
        "description": "Transpacific direct business class booked via Aeroplan with low taxes.",
    },
]


def seed_firestore():
    db = firestore.Client(project=GCP_PROJECT_ID)
    print(f"Connecting to Firestore for project: {GCP_PROJECT_ID}...")
    collection_ref = db.collection("flight_deals")
    
    count = 0
    for deal in SEEDED_FLIGHT_DEALS:
        doc_id = deal["id"]
        collection_ref.document(doc_id).set(deal)
        print(f"Seeded deal: {doc_id} ({deal['origin']} -> {deal['destination']} [{deal['cabin_class']}])")
        count += 1

    print(f"Successfully seeded {count} flight deals into 'flight_deals' collection!")


if __name__ == "__main__":
    seed_firestore()
