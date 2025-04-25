import time,os,json
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import undetected_chromedriver as uc
from openai import AzureOpenAI
import pandas as pd
from tqdm import tqdm

load_dotenv()

BRANDED_FILE = "data/branded_reels.json"
VIEWS_FILE = "reels_html/final_view_counts.json"
OUTPUT_FILE = "data/branded_reels_with_views.json"

USERNAME = os.getenv("IG_USERNAME")
PASSWORD = os.getenv("IG_PASSWORD")
TARGET_HANDLE = None 
AZURE_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")

client = AzureOpenAI(
    api_key=AZURE_API_KEY,
    api_version="2024-02-15-preview",
    azure_endpoint=AZURE_ENDPOINT
)

def login_instagram():
    options = uc.ChromeOptions()
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)

    driver.get("https://www.instagram.com/accounts/login/")
    time.sleep(5)

    driver.find_element(By.NAME, "username").send_keys(USERNAME)
    driver.find_element(By.NAME, "password").send_keys(PASSWORD + Keys.RETURN)
    time.sleep(6)

    return driver

def get_follower_count(driver):
    driver.get(f"https://www.instagram.com/{TARGET_HANDLE}/")
    time.sleep(5)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    try:
        spans = soup.find_all("span")
        for span in spans:
            text = span.get_text()
            if any(unit in text for unit in ["K", "M", "B"]) and "following" not in text.lower():
                return text
        return "Not found"
    except:
        return "Error"
    
def fetch_recent_reels_html(driver):
    driver.get(f"https://www.instagram.com/{TARGET_HANDLE}/reels/")
    time.sleep(6)

    reel_data = []
    seen = set()
    scroll_attempts = 0

    while len(reel_data) < 15 and scroll_attempts < 10:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        a_tags = soup.find_all("a", href=lambda x: x and "/reel/" in x)

        for tag in a_tags:
            href = tag.get("href", "")
            full_url = f"https://www.instagram.com{href}"
            tag_html = tag.prettify()
            if tag_html not in seen:
                reel_data.append({
                    "url": full_url,
                    "html": tag_html
                })
                seen.add(tag_html)
            if len(reel_data) >= 15:
                break

        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)
        scroll_attempts += 1

    os.makedirs("reels_html", exist_ok=True)
    with open("reels_html/all_reels.json", "w", encoding="utf-8") as f:
        json.dump(reel_data, f, indent=2)

def process_saved_htmls_with_gpt():
    with open("reels_html/all_reels.json", "r", encoding="utf-8") as f:
        reel_data = json.load(f)

    results = []
    numeric_views = []

    for item in tqdm(reel_data, desc="🔍 Extracting views with GPT"):
        url = item["url"]
        html = item["html"]
        view_count_text = extract_view_count_with_gpt(html)
        view_count = parse_view_count(view_count_text)

        results.append({
            "url": url,
            "views": view_count_text
        })

        if view_count is not None:
            numeric_views.append(view_count)

    with open("reels_html/final_view_counts.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    avg_view_count = sum(numeric_views) / len(numeric_views) if numeric_views else 0
    return int(avg_view_count)

def extract_view_count_with_gpt(html_block):
    prompt = f"""
You are an expert at extracting view counts from Instagram reel HTML.

Follow these steps strictly to identify the view count:
1. Look for a <title> tag with the text "View count icon".
2. Locate the nearest <span> tag that contains a number like 5, 60, 100, 1k, 9k, 200k, 1.3M, 10M, or 1B.
3. Return only the rendered number inside that <span> — no extra text.

HTML:
{html_block}

Return only the view count. If none is found, return: Not found
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "LLM Error"

def parse_view_count(view_text):
    try:
        text = view_text.lower().replace(",", "").strip()
        if text.endswith("k"):
            return float(text[:-1]) * 1_000
        elif text.endswith("m"):
            return float(text[:-1]) * 1_000_000
        elif text.endswith("b"):
            return float(text[:-1]) * 1_000_000_000
        return float(text)
    except:
        return None

def is_branded(desc_text):
    prompt = f"""
You are an expert at identifying branded content. Below is an Instagram reel description:

Description: {desc_text}

Reply with 'Yes' if this is a paid partnership, sponsored content, or brand collaboration. Otherwise, reply 'No'.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return response.choices[0].message.content.strip().lower() == "yes"
    except:
        return False

def extract_branded_reels(driver):
    driver.get(f"https://www.instagram.com/{TARGET_HANDLE}/reels/")
    time.sleep(5)

    branded_reels = []
    reel_links = []
    seen = set()

    while len(reel_links) < 30:
        soup = BeautifulSoup(driver.page_source, "html.parser")
        new_links = [
            "https://www.instagram.com" + a["href"]
            for a in soup.find_all("a", href=True)
            if "/reel/" in a["href"] and a["href"] not in seen
        ]
        for link in new_links:
            seen.add(link)
            reel_links.append(link)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(3)

    for index, link in enumerate(reel_links):
        driver.get(link)
        time.sleep(5)
        soup = BeautifulSoup(driver.page_source, "html.parser")
        desc_tag = soup.select_one("._ap3a")
        if not desc_tag:
            continue

        desc = desc_tag.text.strip()
        if is_branded(desc):
            branded_reels.append({
                "index": index,
                "id": link.rstrip("/").split("/")[-1],
                "url": link,
                "desc": desc
            })

        if len(branded_reels) >= 7:
            break

    with open("data/branded_reels.json", "w", encoding="utf-8") as f:
        json.dump(branded_reels, f, indent=2)

    return branded_reels

def calculate_avg_branded_views():
    with open("data/branded_reels.json", "r", encoding="utf-8") as f:
        branded_reels = json.load(f)

    with open("reels_html/final_view_counts.json", "r", encoding="utf-8") as f:
        view_data = json.load(f)

    view_lookup = {
        item["url"].rstrip("/").split("/")[-1]: item["views"]
        for item in view_data
    }

    numeric_views = []
    for reel in branded_reels:
        views = view_lookup.get(reel["id"], None)
        parsed = parse_view_count(views) if views else None
        if parsed is not None:
            numeric_views.append(parsed)

    avg = sum(numeric_views) / len(numeric_views) if numeric_views else 0
    return int(avg)

def analyze_instagram_handle(handle: str) -> dict:
    global TARGET_HANDLE
    TARGET_HANDLE = handle

    os.makedirs("data", exist_ok=True)
    os.makedirs("reels_html", exist_ok=True)

    result = {
        "instagram_handle": handle,
        "followers_count": None,
        "average_views_last_15_reels": None,
        "average_views_last_7_branded_reels": None
    }

    driver = login_instagram()

    try:
        result["followers_count"] = get_follower_count(driver)
        fetch_recent_reels_html(driver)
        result["average_views_last_15_reels"] = process_saved_htmls_with_gpt()
        extract_branded_reels(driver)
        result["average_views_last_7_branded_reels"] = calculate_avg_branded_views()
    except Exception as e:
        result["followers_count"] = "Error"
        result["average_views_last_15_reels"] = "Error"
        result["average_views_last_7_branded_reels"] = "Error"
        result["error"] = str(e)
    finally:
        driver.quit()

    return result

