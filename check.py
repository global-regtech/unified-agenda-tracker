import requests, time

url = "https://www.reginfo.gov/public/do/XMLViewFileAction?f=REGINFO_RIN_DATA_202504.xml"
headers = {
    "User-Agent": "regulatory-transparency-tracker/0.1 (github.com/abulix/unified-agenda-tracker)",
    "Accept": "application/xml,*/*"
}

resp = requests.get(url, headers=headers, timeout=60)
print(f"Status: {resp.status_code}, Size: {len(resp.content):,} bytes")

with open("data/agenda_content_raw.xml", "wb") as f:
    f.write(resp.content)
print("Saved.")