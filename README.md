# DDD-flair

A Flask micro-service to calculate the [perplexity](https://en.wikipedia.org/wiki/Perplexity#Perplexity_per_word) of texts, using [flair](https://github.com/flairNLP/flair)'s language models.

# Development

```bash
pipenv run bash dev.sh
```

## Deployment

Link to persistence storage.

```bash
dokku storage:mount APP /mnt/data/ddd/flair_cache:/flair_cache
```

## Usage

```bash
curl --header "Content-Type: application/json" \
    --request POST \
    --data '{"texts":["Ich lebe in Berlin", "Ich lebe in Auto"]}' \
    http://localhost:5000/score
```

## License

GPlv3.