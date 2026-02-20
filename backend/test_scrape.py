import requests
from bs4 import BeautifulSoup
import re

def sanitize_text(text: str) -> str:
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_from_url(url: str) -> str:
    try:
        jina_url = f"https://r.jina.ai/{url}"
        print(f"Trying Jina: {jina_url}")
        response = requests.get(jina_url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200 and len(response.text.strip()) > 200:
            print("Jina Success!")
            return sanitize_text(response.text)
        print(f"Jina Status: {response.status_code}, length: {len(response.text)}")
    except Exception as exc:
        print(f"Jina failed: {exc}")

    try:
        print(f"Trying Direct: {url}")
        response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        print(f"Direct Status Code: {response.status_code}")
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "svg", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        return sanitize_text(text)
    except Exception as exc:
        return f"Scraping fully failed: {str(exc)}"

import sys
url = sys.argv[1] if len(sys.argv) > 1 else "https://www.carwale.com/mahindra-cars/thar/"
print(extract_from_url(url))
