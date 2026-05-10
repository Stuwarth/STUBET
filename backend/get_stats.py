import sys, json, asyncio
sys.path.append('c:/Users/stuwa/Desktop/SportsAI-Predictor/backend')
from data.database import DatabaseManager
from data.collectors.news_scraper import NewsInjuryScraper

async def main():
    db = DatabaseManager()
    scraper = NewsInjuryScraper(db)
    
    # 1. Fetch real Madrid injuries
    try:
        rma_injuries = await scraper.get_team_injuries("Real Madrid")
        print("REAL MADRID INJURIES:")
        print(json.dumps(rma_injuries, indent=2))
    except Exception as e:
        print("Error RMA injuries:", e)
        
    # 2. Fetch Espanyol injuries
    try:
        esp_injuries = await scraper.get_team_injuries("Espanyol")
        print("\nESPANYOL INJURIES:")
        print(json.dumps(esp_injuries, indent=2))
    except Exception as e:
        print("Error ESP injuries:", e)

    # 3. Query DB for Last 10 matches for Real Madrid
    try:
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT home_team_name, away_team_name, home_score, away_score, status_type
            FROM sofascore_matches 
            WHERE (home_team_name LIKE '%Real Madrid%' OR away_team_name LIKE '%Real Madrid%')
              AND LOWER(status_type) = 'finished'
            ORDER BY start_timestamp DESC LIMIT 10
        """).fetchall()
        print("\nRM LAST 10:")
        for r in rows:
            print(dict(r))
        conn.close()
    except Exception as e:
        print("Error RM matches:", e)

    # 4. H2H
    try:
        conn = db.get_connection()
        rows = conn.execute("""
            SELECT home_team_name, away_team_name, home_score, away_score, start_timestamp
            FROM sofascore_matches 
            WHERE (home_team_name LIKE '%Real Madrid%' AND away_team_name LIKE '%Espanyol%')
               OR (home_team_name LIKE '%Espanyol%' AND away_team_name LIKE '%Real Madrid%')
            ORDER BY start_timestamp DESC LIMIT 5
        """).fetchall()
        print("\nH2H:")
        for r in rows:
            print(dict(r))
        conn.close()
    except Exception as e:
        print("Error H2H:", e)

if __name__ == '__main__':
    asyncio.run(main())
