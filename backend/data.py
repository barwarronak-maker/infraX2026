# data.py

#  MASTER EMERGENCY DATABASE (Twilio-safe numbers + fallback logic)

EMERGENCY_CONTACTS = [

    #  AMBULANCE (FIRST PRIORITY)
    {
        "id": 301,
        "name": "Private Ambulance Service",
        "type": "ambulance",
        "priority": 0,
        "lat": 18.5204,
        "lng": 73.8567,
        "phone": "+919876543210",  
        "city": "Pune"
    },

    #  HOSPITALS
    {
        "id": 1,
        "name": "Sassoon General Hospital",
        "type": "hospital",
        "priority": 1,
        "lat": 18.5178,
        "lng": 73.8543,
        "phone": "+912026120009",
        "city": "Pune"
    },
    {
        "id": 2,
        "name": "KEM Hospital Pune",
        "type": "hospital",
        "priority": 1,
        "lat": 18.5120,
        "lng": 73.8553,
        "phone": "+912026128000",
        "city": "Pune"
    },
    {
        "id": 3,
        "name": "Ruby Hall Clinic",
        "type": "hospital",
        "priority": 1,
        "lat": 18.5320,
        "lng": 73.8820,
        "phone": "+912026163391",
        "city": "Pune"
    },

    #  POLICE (REAL LANDLINE)
    {
        "id": 101,
        "name": "Pune Police Control Room",
        "type": "police",
        "priority": 2,
        "lat": 18.5204,
        "lng": 73.8567,
        "phone": "+912026130000", 
        "city": "Pune"
    },

    # FIRE (REAL NUMBER)
    {
        "id": 201,
        "name": "Fire Control Room Pune",
        "type": "fire",
        "priority": 3,
        "lat": 18.5204,
        "lng": 73.8567,
        "phone": "+912026130101",  
        "city": "Pune"
    }
]
