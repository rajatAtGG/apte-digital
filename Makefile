.PHONY: all data build test clean

all: build

data:            ## sparse-checkout the Apte XML from samsaadhanii/scl (pinned commit)
	./scripts/fetch_data.sh

build: data      ## parse XML -> build/apte.sqlite, build/apte.json, build/report.txt
	python3 pipeline/build.py

test:            ## parser + normalisation tests (the full-build test needs `make data`)
	python3 -m pytest -q tests

clean:
	rm -rf build
