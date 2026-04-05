# FILE: tests/test_gui.py
# MODULE: GUI Tests (Headless Browser Tests)
# Testet Streamlit UI Komponenten mit Selenium

import subprocess
import time

import pytest
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


@pytest.fixture(scope="session")
def streamlit_app():
    """Startet Streamlit App für Tests"""
    process = subprocess.Popen(
        ["streamlit", "run", "streamlit_app.py", "--server.port=8502", "--server.headless=true"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    time.sleep(5)  # Warte auf Start
    yield
    process.terminate()


@pytest.fixture
def driver():
    """Selenium WebDriver"""
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    driver = webdriver.Chrome(options=options)
    yield driver
    driver.quit()


def test_login_page(driver, streamlit_app):
    """Test Login Page Rendering"""
    driver.get("http://localhost:8502")

    # Prüfe Titel
    assert "TrueAngels" in driver.title

    # Prüfe Login Form
    email_input = driver.find_element(By.CSS_SELECTOR, "input[type='text']")
    password_input = driver.find_element(By.CSS_SELECTOR, "input[type='password']")
    submit_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Anmelden')]")

    assert email_input.is_displayed()
    assert password_input.is_displayed()
    assert submit_button.is_displayed()


def test_dark_mode_toggle(driver, streamlit_app):
    """Test Dark Mode Toggle"""
    driver.get("http://localhost:8502")

    # Find Dark Mode Toggle
    toggle = driver.find_element(By.CSS_SELECTOR, ".stToggle")
    initial_theme = driver.execute_script(
        "return document.documentElement.getAttribute('data-theme')"
    )

    # Toggle
    toggle.click()
    time.sleep(1)

    new_theme = driver.execute_script(
        "return document.documentElement.getAttribute('data-theme')"
    )

    assert new_theme != initial_theme


def test_navigation(driver, streamlit_app):
    """Test Sidebar Navigation"""
    driver.get("http://localhost:8502")

    # Login first
    driver.find_element(By.CSS_SELECTOR, "input[type='text']").send_keys("admin@trueangels.de")
    driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys("admin123")
    driver.find_element(By.XPATH, "//button[contains(text(), 'Anmelden')]").click()

    time.sleep(2)

    # Navigate to different pages
    nav_items = ["Dashboard", "Spenden", "Projekte", "Einstellungen"]

    for item in nav_items:
        nav_link = driver.find_element(By.XPATH, f"//div[contains(text(), '{item}')]")
        nav_link.click()
        time.sleep(1)

        # Prüfe Page Header
        header = driver.find_element(By.TAG_NAME, "h1")
        assert item.lower() in header.text.lower() or "willkommen" in header.text.lower()


def test_donation_form(driver, streamlit_app):
    """Test Donation Form Submission"""
    driver.get("http://localhost:8502")

    # Login
    driver.find_element(By.CSS_SELECTOR, "input[type='text']").send_keys("admin@trueangels.de")
    driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys("admin123")
    driver.find_element(By.XPATH, "//button[contains(text(), 'Anmelden')]").click()

    time.sleep(2)

    # Navigate to Donations
    driver.find_element(By.XPATH, "//div[contains(text(), 'Spenden')]").click()
    time.sleep(1)

    # Go to "Neue Spende" tab
    new_donation_tab = driver.find_element(By.XPATH, "//button[contains(text(), 'Neue Spende')]")
    new_donation_tab.click()
    time.sleep(1)

    # Fill form
    amount_input = driver.find_element(By.CSS_SELECTOR, "input[aria-label='Betrag (€)']")
    amount_input.clear()
    amount_input.send_keys("100")

    name_input = driver.find_element(By.CSS_SELECTOR, "input[aria-label='Spender Name']")
    name_input.send_keys("Test User")

    email_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
    email_input = email_inputs[-1]  # Letztes Textfeld ist E-Mail
    email_input.send_keys("test@example.com")

    # Submit
    submit_button = driver.find_element(By.XPATH, "//button[contains(text(), 'Spende erfassen')]")
    submit_button.click()

    # Prüfe Success Message
    wait = WebDriverWait(driver, 5)
    success_message = wait.until(
        EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'wurde erfasst')]"))
    )

    assert success_message is not None


# ==================== Performance Tests ====================

@pytest.mark.benchmark
def test_page_load_time(benchmark, driver, streamlit_app):
    """Benchmark: Page Load Time"""

    def load_dashboard():
        driver.get("http://localhost:8502")
        # Login
        driver.find_element(By.CSS_SELECTOR, "input[type='text']").send_keys("admin@trueangels.de")
        driver.find_element(By.CSS_SELECTOR, "input[type='password']").send_keys("admin123")
        driver.find_element(By.XPATH, "//button[contains(text(), 'Anmelden')]").click()
        time.sleep(2)
        return True

    result = benchmark(load_dashboard)
    assert result is True
