import json
import sys
import time

import requests

pdf_path = "../pd3f-core/tests/test_data/00020/00020_08112014_Stellungnahme_RAK_Koeln_RefE_Bekaempfung_Korruption.pdf"

with open(pdf_path, "rb") as f:
    response = requests.post(
        "http://localhost:1616",
        files={"pdf": ("test.pdf", f)},
        data={
            "lang": "de",
            "parsr_adjust_cleaner_config": json.dumps(
                [["reading-order-detection", {"minVerticalGapWidth": 20}]]
            ),
        },
    )
response.raise_for_status()
job_id = response.json()["id"]

while True:
    j = requests.get(f"http://localhost:1616/update/{job_id}").json()
    if "text" in j:
        break
    if "failed" in j:
        sys.exit(f"pd3f failed to process the PDF:\n{j['log']}")
    print("waiting...")
    time.sleep(1)
print(j["text"])
