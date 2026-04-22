"""
Run this ONCE to log into X inside the automation Chrome profile.
After you log in and see your home feed, press Enter here to close.
"""
import time
import undetected_chromedriver as uc

options = uc.ChromeOptions()
options.add_argument(r"--user-data-dir=C:\Users\resoa\Videos\X_Post\chrome_profile")
options.add_argument("--no-first-run")
options.add_argument("--no-default-browser-check")
options.add_argument("--start-maximized")

driver = uc.Chrome(
    options=options,
    browser_executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    driver_executable_path=r"C:\Users\resoa\AppData\Local\Temp\chromedriver\chromedriver-win64\chromedriver.exe",
    headless=False,
    use_subprocess=True,
)

driver.get("https://x.com/login")
print("\nLog into X in the browser window, then come back here and press Enter.")
input()
driver.quit()
print("Done. Your session is saved in chrome_profile/")
