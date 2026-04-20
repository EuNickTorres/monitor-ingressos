"""
Login manual para o Arena Kids (Ingresse).

Execute este script LOCALMENTE (não no Docker) quando a sessão expirar.
Salva os cookies em ingresse_state.json (JSON puro, funciona no Linux/Docker).

Uso:
    python login_arenakids.py
"""

import asyncio
import os
from playwright.async_api import async_playwright

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ingresse_state.json")


async def main():
    print(f"Arquivo de sessão: {STATE_FILE}")
    print("Abrindo browser — faça o login no cart.ingresse.com e feche a janela quando terminar.\n")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
        )
        await ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined}); window.chrome={runtime:{}};"
        )
        page = await ctx.new_page()
        await page.goto("https://arenakidscorinthians.com.br", wait_until="domcontentloaded", timeout=30000)

        print("Browser aberto no site do Arena Kids.")
        print("Clique em qualquer jogo -> vai abrir o carrinho -> clique em 'Acessar conta' -> faça o login.")
        print("Após logar e ver o carrinho com os ingressos, feche a janela do browser.")

        try:
            await page.wait_for_event("close", timeout=0)
        except Exception:
            pass

        # Salva cookies e localStorage em JSON puro (cross-platform)
        await ctx.storage_state(path=STATE_FILE)
        await browser.close()

    print(f"\nSessão salva em: {STATE_FILE}")
    print("Agora reinicie o scraper: docker compose restart scraper")


if __name__ == "__main__":
    asyncio.run(main())
