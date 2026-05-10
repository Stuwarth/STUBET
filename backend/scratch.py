import sys, json, asyncio
sys.path.append('c:/Users/stuwa/Desktop/SportsAI-Predictor/backend')
from data.database import DatabaseManager
from data.collectors.sofascore_collector import SofaScoreCollector

async def main():
    db = DatabaseManager()
    col = SofaScoreCollector(db)
    evs = await col.search_events('Real Madrid')
    esp_rma = [e for e in evs if 'Espanyol' in e.get('name', '')]
    print("MATCHES:", json.dumps(esp_rma, indent=2))

if __name__ == '__main__':
    asyncio.run(main())
