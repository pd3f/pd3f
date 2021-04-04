import json
import time

import requests

files = {
    "pdf": (
        "test.pdf",
        open(
            "../pd3f-core/tests/test_data/00020/00020_08112014_Stellungnahme_RAK_Koeln_RefE_Bekaempfung_Korruption.pdf",
            "rb",
        ),
    )
}
response = requests.post(
    "http://localhost:1616",
    files=files,
    data={
        "lang": "de",
        "parsr_adjust_cleaner_config": json.dumps(
            [["reading-order-detection", {"minVerticalGapWidth": 20}]]
        ),
    },
)
id = response.json()["id"]

while True:
    r = requests.get(f"http://localhost:1616/update/{id}")
    j = r.json()
    if "text" in j:
        break
    print("waiting...")
    time.sleep(1)
print(j["text"])
