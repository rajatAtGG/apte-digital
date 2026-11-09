.PHONY: all data build app serve test clean

all: app

data:            ## sparse-checkout the Apte XML from samsaadhanii/scl (pinned commit)
	./scripts/fetch_data.sh

build: data      ## parse XML -> build/apte.sqlite, build/apte.json, build/report.txt
	python3 pipeline/build.py

app: build       ## assemble the PWA in dist/
	npm install --no-audit --no-fund
	node scripts/build-app.mjs

serve:           ## serve dist/ on http://localhost:8080/
	node scripts/serve.mjs dist 8080

test:            ## all tests (data-dependent ones are skipped until `make build`)
	python3 -m pytest -q tests
	npm test

clean:
	rm -rf build dist
