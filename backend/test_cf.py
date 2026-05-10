import asyncio
from playwright.async_api import async_playwright

async def test_cloudflare_bypass_iframe():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
        )
        page = await context.new_page()
        
        print('Loading LasPlatas...')
        await page.goto('https://www.lasplatas.com', wait_until='networkidle', timeout=60000)
        
        # Wait for the iframe
        frame_element = await page.wait_for_selector('iframe[src*="altenar"]', timeout=15000)
        frame = await frame_element.content_frame()
        
        if not frame:
            print('Iframe not found!')
            return
            
        url_reserve = 'https://sb2commongateway-altenar2.biahosted.com/api/Betslip/FindReservedBet?culture=es-ES&timezoneOffset=240&integration=lasplatas&deviceType=1&numFormat=en-GB&reservationCode=VONDK'
        
        print('Executing fetch inside Altenar iframe...')
        script = f'''
        async () => {{
            const resp = await fetch('{url_reserve}', {{
                headers: {{
                    'Accept': 'application/json, text/plain, */*'
                }}
            }});
            return {{ status: resp.status, text: await resp.text() }};
        }}
        '''
        
        res = await frame.evaluate(script)
        print('Result:', res['status'])
        print(res['text'][:1000])
        
        await browser.close()

asyncio.run(test_cloudflare_bypass_iframe())
