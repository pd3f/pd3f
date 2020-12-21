FROM jbarlow83/ocrmypdf:v11.4.0

RUN apt-get install --no-install-recommends -y \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    tesseract-ocr-ita \
    tesseract-ocr-spa

ADD ocr_folder.sh ocr_folder.sh

ENTRYPOINT [ "./ocr_folder.sh" ]:
