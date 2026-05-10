import asyncio
import json
import os
from playwright.async_api import async_playwright

async def get_sofa_data():
    os.makedirs('scratch', exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print('Navigating to sofascore to get cookies...')
        await page.goto('https://www.sofascore.com/', wait_until='domcontentloaded')
        
        print('Fetching Everton events...')
        await page.goto('https://api.sofascore.com/api/v1/team/48/events/last/0')
        everton_events = json.loads(await page.evaluate('document.body.innerText'))
        
        print('Fetching Man City events...')
        await page.goto('https://api.sofascore.com/api/v1/team/17/events/last/0')
        city_events = json.loads(await page.evaluate('document.body.innerText'))
        
        print('Fetching H2H events...')
        await page.goto('https://api.sofascore.com/api/v1/custom-api/team/17/48/h2h/events')
        h2h_events = json.loads(await page.evaluate('document.body.innerText'))
        
        e_events = everton_events.get('events', [])[:10]
        c_events = city_events.get('events', [])[:10]
        h_events = h2h_events.get('events', [])[:10]
        
        results = {'EVE': [], 'MCI': [], 'H2H': []}
        
        for ev in e_events:
            event_id = ev['id']
            try:
                await page.goto(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics')
                stats = json.loads(await page.evaluate('document.body.innerText'))
                results['EVE'].append({'match': f"{ev.get('homeTeam', {}).get('shortName')} vs {ev.get('awayTeam', {}).get('shortName')}", 'stats': stats})
            except Exception as e:
                print(f"Error fetching stats for EVE event {event_id}: {e}")

        for ev in c_events:
            event_id = ev['id']
            try:
                await page.goto(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics')
                stats = json.loads(await page.evaluate('document.body.innerText'))
                results['MCI'].append({'match': f"{ev.get('homeTeam', {}).get('shortName')} vs {ev.get('awayTeam', {}).get('shortName')}", 'stats': stats})
            except Exception as e:
                print(f"Error fetching stats for MCI event {event_id}: {e}")

        for ev in h_events:
            event_id = ev['id']
            try:
                await page.goto(f'https://api.sofascore.com/api/v1/event/{event_id}/statistics')
                stats = json.loads(await page.evaluate('document.body.innerText'))
                results['H2H'].append({'match': f"{ev.get('homeTeam', {}).get('shortName')} vs {ev.get('awayTeam', {}).get('shortName')}", 'stats': stats})
            except Exception as e:
                print(f"Error fetching stats for H2H event {event_id}: {e}")

        with open('scratch/sofa_stats.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False)
            
        await browser.close()
        print('DONE scraping 30 matches!')

if __name__ == '__main__':
    asyncio.run(get_sofa_data())
