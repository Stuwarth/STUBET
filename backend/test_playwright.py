import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://lasplatas.com/betting#/overview")
        print("Page loaded")
        
        # Look for the fast code input
        await page.wait_for_selector("input[placeholder='Código Rápido']", timeout=10000)
        await page.fill("input[placeholder='Código Rápido']", "9YYH2")
        await page.keyboard.press("Enter")
        
        await page.wait_for_timeout(3000)
        content = await page.content()
        print(len(content))
        await browser.close()

asyncio.run(run())
