import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        requests_urls = []
        page.on('request', lambda request: requests_urls.append(request.url) if 'api/v1' in request.url else None)
        
        await page.goto('https://www.sofascore.com/paris-saint-germain-bayern-munchen/xOsYQ', wait_until='networkidle')
        
        print('API Requests captured:')
        for url in requests_urls:
            if 'h2h' in url:
                print('H2H URL:', url)
            elif 'event' in url:
                print('Event URL:', url)
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
