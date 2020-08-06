# `pdddf-service`

Flask Micro Service + GUI for [pdddf](https://github.com/jfilter/pdddf).


## Installation

You need to setup [Docker](https://docs.docker.com/get-docker/).

You need the `docker-compose.yml` file of this repo. You can download it separately or just `git clone https://github.com/jfilter/pdddf-service`.

You need to have ~4 GB of space to store all the software / data to run this.

## Usage

You need the `docker-compose.yml` and then run

```
docker-compose up
```

### GUI

This will download the images, this may take a while. After it's finished upload files to <http://localhost:1616>.


You will see two folders:

- `pdddf-uploads`: input & output data
- `pdddf-cache`: storing data so you don't have to re

You can also run more worker with this:


```bash
docker-compose up --scale worker=3
```

To increase the frontend threads, change this line in `docker-compose.yml`:

```yml
command: gunicorn app:app --workers=5 --bind=0.0.0.0:5000
```

### API

```python



```

## License

GPLv3