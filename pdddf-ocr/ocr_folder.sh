#!/usr/bin/env bash
set -x

mkdir -p /to-ocr

while sleep 1; do
    # cant check with *.pdf because it matches *.pdf.done
    for f in $(find /to-ocr -name "*.pdf" -type f); do
        # unlock PDF is needed
        if qpdf --is-encrypted "$f"; then
            qpdf --decrypt "$f" "$f".2 && mv "$f".2 "$f"
        fi

        echo "$f"
        tfn=$(basename "$f" .pdf)
        lang=${tfn##*.}
        if ocrmypdf -l $lang --pdf-renderer hocr --output-type pdf --clean --skip-text --deskew "$f" "$f".done &>"$f".log; then
            rm "$f"
            echo 'success'
        else
            rm "$f".done
            mv "$f" "$f".failed
            echo 'failed'
        fi
    done
done
