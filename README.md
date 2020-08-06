# `pdddf-service`

Flask Micro Service + GUI for pdddf


```docker-compose up --scale worker=2
```

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

GPLv3