FROM jbarlow83/ocrmypdf:v17.13.0

# root: Docker creates the shared /to-ocr volume as root
USER root

# qpdf decrypts PDFs, Italian is not part of the base image
RUN apt-get update \
    && apt-get install --no-install-recommends -y qpdf tesseract-ocr-ita \
    && rm -rf /var/lib/apt/lists/*

COPY --chmod=755 ocr_folder.sh /usr/local/bin/ocr_folder.sh

ENTRYPOINT ["ocr_folder.sh"]
