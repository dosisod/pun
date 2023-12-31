.PHONY: install ruff mypy black isort typos test

all: ruff mypy black isort typos test

install:
	pip install -e .
	pip install -r requirements.txt -r dev-requirements.txt

ruff:
	ruff pun test

mypy:
	mypy -p pun
	mypy -p test --exclude test/data

black:
	black pun test --check --diff

isort:
	isort . --diff --check

typos:
	typos --format brief

test:
	pytest

fmt:
	ruff pun test --fix
	isort .
	black pun test

clean:
	rm -rf .mypy_cache .ruff_cache dist build pun/build pun/dist
