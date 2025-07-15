import os
import time
import logging
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("whatsapp_debug")

def send_whatsapp_message(profile_path, chat_name, message):
    options = Options()
    options.add_argument(f"--user-data-dir={profile_path}")
    options.add_argument("--window-size=1200,800")
    options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    options.add_argument("--disable-blink-features=AutomationControlled")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://web.whatsapp.com")

    try:
        logger.info("🔄 Waiting for WhatsApp Web to load...")
        WebDriverWait(driver, 60).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='chat-list']"))
        )
        logger.info("✅ WhatsApp Web loaded.")
        driver.save_screenshot("step1_whatsapp_loaded.png")

        # Click the search box
        logger.info("🔍 Clicking search box...")
        search_box = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.XPATH, "//div[@contenteditable='true'][@data-tab='3']"))
        )
        search_box.click()
        time.sleep(1)

        # Type the chat name
        logger.info(f"⌨ Typing chat name: {chat_name}")
        search_box.send_keys(chat_name)
        time.sleep(3)  # Give it time to load results
        driver.save_screenshot("step2_after_typing_chat_name.png")

        # Wait for search results and click the correct chat
        logger.info("🖱️ Looking for chat in search results...")
        chat_xpath = f"//span[contains(@title,'{chat_name}')]"
        chat_element = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, chat_xpath))
        )
        chat_element.click()
        logger.info("✅ Chat selected.")
        driver.save_screenshot("step3_chat_clicked.png")

        # Wait for chat to open and type the message
        logger.info(f"💬 Typing message: {message}")
        msg_box = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true'][@data-tab='10']"))
        )
        msg_box.click()
        msg_box.clear()
        msg_box.send_keys(message)
        driver.save_screenshot("step4_message_typed.png")

        # Press send
        logger.info("📤 Clicking send button...")
        send_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//button[@aria-label='Send']"))
        )
        send_btn.click()
        time.sleep(2)
        driver.save_screenshot("step5_message_sent.png")
        logger.info("✅ Message sent successfully.")

    except Exception as e:
        logger.error(f"❌ Error: {e}")
        driver.save_screenshot("error_screenshot.png")
        raise  # Re-raise the exception to see the full traceback

    finally:
        time.sleep(5)
        driver.quit()

# Test Run
send_whatsapp_message(
    profile_path=r"C:\WhatsAppBotProfile",
    chat_name="Test group",
    message="Hello bro! This is a test message 🚀"
)  