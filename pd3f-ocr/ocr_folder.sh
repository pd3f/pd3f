#!/usr/bin/env bash
shopt -s nullglob

mkdir -p /to-ocr

while sleep 1; do
    for f in /to-ocr/*.pdf; do
        # unlock PDF if needed
        if qpdf --is-encrypted "$f"; then
            qpdf --decrypt "$f" "$f".2 && mv "$f".2 "$f"
        fi

        echo "$f"
        tfn=$(basename "$f" .pdf)
        lang=${tfn##*.}
        if ocrmypdf -l "$lang" --output-type pdf --clean --skip-text --deskew "$f" "$f".done &>"$f".log; then
            rm "$f"
            echo 'success'
        else
            rm -f "$f".done
            mv "$f" "$f".failed
            echo 'failed'
        fi
    done
done
