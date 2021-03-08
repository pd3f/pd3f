FROM jbarlow83/ocrmypdf:v11.6.2

RUN apt-get update && apt-get upgrade -y

ADD ocr_folder.sh ocr_folder.sh

ENTRYPOINT [ "./ocr_folder.sh" ]:
