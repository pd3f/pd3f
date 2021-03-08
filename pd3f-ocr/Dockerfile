
FROM jbarlow83/ocrmypdf:v11.6.2

# upgrade packages
RUN apt-get update && apt-get upgrade -y

# remove not supported languages
RUN apt-get remove --purge -y tesseract-ocr-chi-sim tesseract-ocr-por

# install supported languages (only Italian for now)
RUN apt-get install --no-install-recommends -y \
    tesseract-ocr-ita

ADD ocr_folder.sh ocr_folder.sh

ENTRYPOINT [ "./ocr_folder.sh" ]:
