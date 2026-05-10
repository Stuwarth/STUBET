import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        await page.goto('https://www.sofascore.com/paris-saint-germain-bayern-munchen/xOsYQ', wait_until='networkidle')
        
        # Get all page content
        content = await page.content()
        
        # Find all strings looking like URLs with h2h or team in them
        import re
        urls = set(re.findall(r'/[a-zA-Z0-9_/-]+/h2h[a-zA-Z0-9_/-]*', content))
        print("H2H related paths found in HTML:")
        for u in urls:
            print(u)
            
        urls_team = set(re.findall(r'/[a-zA-Z0-9_/-]+/team/[0-9]+/events/last[a-zA-Z0-9_/-]*', content))
        print("\nTeam last matches paths found in HTML:")
        for u in urls_team:
            print(u)
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
