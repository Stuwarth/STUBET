import asyncio
from playwright.async_api import async_playwright
import json

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        await page.goto("https://www.sofascore.com/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(1.5)

        url = "https://www.sofascore.com/api/v1/event/15632634"
        js_script = f'fetch("{url}", {{headers: {{"accept":"*/*"}} }}).then(r => r.text()).catch(e => e.message)'
        
        text = await page.evaluate(js_script)
        
        try:
            data = json.loads(text)
            event = data.get('event', {})
            customId = event.get('customId')
            print(f"Custom ID: {customId}")
            
            if customId:
                url_custom = f"https://www.sofascore.com/api/v1/event/{customId}/h2h/events"
                js_script2 = f'fetch("{url_custom}", {{headers: {{"accept":"*/*"}} }}).then(r => r.text()).catch(e => e.message)'
                text2 = await page.evaluate(js_script2)
                print("Custom H2H Response:", text2[:200])
        except Exception as e:
            print("Error parsing event:", e)
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
