"""Actual Chromium frontend smoke for the owner-only Streamlit dashboard.

GitHub's Streamlit AppTest exercises Python widgets but cannot verify
WebSocket / static JS delivery or browser rendering. This tests those
paths locally on Python 3.14 without broker or Supabase credentials.
"""
import os
import sys

from playwright.sync_api import sync_playwright


def main():
    password=os.environ["APP_ACCESS_PASSWORD"]
    failures=[]
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=["--no-sandbox"])
        page=browser.new_page(viewport={"width":1366,"height":900})
        page.on("pageerror",lambda err:failures.append(str(err)[:350]))
        try:
            response=page.goto("http://127.0.0.1:8501/",
                               wait_until="domcontentloaded",timeout=60000)
            assert response is not None and response.status==200, (
                "Local Streamlit returned unexpected HTTP response")
            page.get_by_text(
                "FOKU$ THE BEST TRADER — dostęp właściciela",
                exact=False).wait_for(state="visible",timeout=45000)
            page.get_by_label("Hasło właściciela").fill(password)
            page.get_by_role("button",name="Otwórz terminal").click()
            page.locator('[data-testid="stTabs"]').wait_for(
                state="visible",timeout=60000)
            tabs=page.get_by_role("tab").count()
            assert tabs>=10, f"Expected 10 owner tabs, got {tabs}"
            # Verify the REAL browser can start the bundled Polish MP3
            # with one click, rather than just passing Python/unit tests.
            player=None
            for _ in range(35):
                for frame in page.frames:
                    try:
                        if frame.locator("#fokus-voice-play").count():
                            player=frame
                            break
                    except Exception:
                        pass  # Streamlit might replace a frame mid-rerun.
                if player is not None:
                    break
                page.wait_for_timeout(300)
            assert player is not None, "No direct-click browser MP3 player"
            player.locator("#fokus-voice-play").click(timeout=15000)
            player.locator("#fokus-voice-status").get_by_text(
                "Odtwarzanie rozpoczęte",exact=False).wait_for(
                state="visible",timeout=20000)
            print("BROWSER_VOICE=OK / MP3_BUTTON_CLICK_PLAYED / PYTHON="+
                  sys.version.split()[0],flush=True)
            print("BROWSER_SMOKE=OK / PYTHON="+sys.version.split()[0]+
                  " / STREAMLIT_OWNER_TABS="+str(tabs),flush=True)
            if failures:
                print("NON_FATAL_BROWSER_PAGEERRORS="+
                      str(failures[:5]),flush=True)
        except Exception:
            print("BROWSER_SMOKE=FAIL / page_body_sample="+
                  page.locator("body").inner_text(timeout=10000)[:1800],
                  flush=True)
            print("PAGE_ERRORS="+str(failures[:10]),flush=True)
            raise
        finally:
            browser.close()


if __name__=="__main__":
    main()
