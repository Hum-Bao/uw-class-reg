import time
import os
import sys
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from selenium import webdriver
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

path_userdata = os.getenv("APPDATA") + "\\HumBao\\ChromeDriver"
COMPLETE = False
USERNAME = ""
PASSWORD = ""
CLASS_IDS = []
DATE = []


def create_browser():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--user-data-dir=" + path_userdata)
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--log-level=3")

    driver = webdriver.Chrome(chrome_options)
    # Access UW register page
    driver.get("http://tinyurl.com/uwreg")
    # Sleep to allow page to load
    time.sleep(1)
    # Find and enter username and password
    element = driver.find_element(By.NAME, "j_username")
    element.send_keys(USERNAME)
    element = driver.find_element(By.NAME, "j_password")
    element.send_keys(PASSWORD)
    element = driver.find_element(By.NAME, "_eventId_proceed")
    element.click()
    # Sleep to allow page to load
    time.sleep(3)
    if len(driver.find_elements(By.ID, "trust-browser-button")) > 0:
        WebDriverWait(driver, 120).until(
            EC.element_to_be_clickable((By.ID, "trust-browser-button"))
        ).click()
        print("CLICKED")
        WebDriverWait(driver, 180).until(
            EC.url_changes("https://sdb.admin.uw.edu/students/uwnetid/register.asp")
        )
    return driver


def register_class(driver: webdriver.Chrome):
    try:
        start_index = 4
        # for class_id in class_id_list:
        for class_id in CLASS_IDS:
            element = WebDriverWait(driver, 120).until(
                EC.element_to_be_clickable((By.NAME, "sln" + str(start_index)))
            )
            element.send_keys(class_id)
            start_index += 1
    except Exception as e:
        print(f"Error occurred: {e}")

    element = driver.find_element(By.CSS_SELECTOR, "input[type='submit']")
    element.click()

    if EC.alert_is_present():
        alert = driver.switch_to.alert
        alert_text = alert.text
        alert.accept()
        print("ERROR: ", alert_text)
        global COMPLETE
        COMPLETE = True
        return

    class_status = (
        WebDriverWait(driver, 10)
        .until(
            EC.visibility_of_element_located(
                (By.XPATH, "//*[@id='regform']/p[2]/table/tbody/tr[2]/td[5]")
            )
        )
        .get_attribute("textContent")
    )
    print(class_status)


def __main__():
    driver = create_browser()
    # class_id_list = ["00000", "00001"]
    scheduler = BackgroundScheduler()
    scheduler.start()
    execute_date = datetime(DATE[0], DATE[1], DATE[2], DATE[3], DATE[4])
    scheduler.add_job(
        register_class,
        misfire_grace_time=5 * 60,
        run_date=execute_date,
        args=[driver],
    )
    # register_class(driver, class_id_list)
    print("Job scheduled. Waiting for execution...")

    try:
        while not COMPLETE:
            time.sleep(1)
    # pass  # Keep the script running
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
    scheduler.shutdown()
    driver.close()


if __name__ == "__main__":
    print("Script name:", sys.argv[0])
    for count in range(len(sys.argv)):
        match sys.argv[count]:
            case "--creds":
                creds = sys.argv[count + 1].split(":")
                USERNAME = creds[0]
                PASSWORD = creds[1]
                count += 2
            case "--date":
                DATE = sys.argv[count + 1].split(":")
                DATE = list(map(int, DATE))
                count += 2
            case "--ids":
                CLASS_IDS = sys.argv[count + 1 :]
                break

    print("Registering for classes: ", CLASS_IDS, " at time: ", DATE)
    __main__()
