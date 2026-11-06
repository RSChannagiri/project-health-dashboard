.PHONY: setup run test lint format sample

setup:
	python3 -m venv .venv
	.venv/bin/pip install -r requirements.txt
	.venv/bin/pip install -e .

run:
	.venv/bin/streamlit run app.py

test:
	.venv/bin/pytest

lint:
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .

format:
	.venv/bin/ruff format .
	.venv/bin/ruff check --fix .

sample:
	.venv/bin/python -m project_health.sample_data --out data
