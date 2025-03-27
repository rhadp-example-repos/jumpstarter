PKG_TARGETS = $(subst packages/,,$(wildcard packages/*))

RELEASE_TAG = v0.1.3
RELEASE_BRANCH = develop

default: build

test-%: packages/%
	uv run --isolated --directory $< pytest

test-packages: $(addprefix test-,$(PKG_TARGETS))

test: test-packages

mypy-%: packages/%
	uv run --isolated --directory $< mypy .

mypy-packages: $(addprefix mypy-,$(PKG_TARGETS))

mypy: mypy-packages

clean-venv:
	-rm -rf ./.venv
	-find . -type d -name __pycache__ -exec rm -r {} \+

clean-build:
	-rm -rf dist

clean-test:
	-rm .coverage
	-rm coverage.xml
	-rm -rf htmlcov

clean: clean-venv clean-build clean-test

generate:
	buf generate

build:
	uv build --all --out-dir dist

build-sync:
	uv sync --all-packages --all-extras

build-container: clean
	podman build -t rhadp-example-repos/jumpstarter -f Dockerfile.ubi9 .

release:
	git tag $(RELEASE_TAG) $(RELEASE_BRANCH)
	git push origin $(RELEASE_BRANCH)
	git push origin tag $(RELEASE_TAG)