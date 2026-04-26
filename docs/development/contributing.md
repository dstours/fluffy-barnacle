# Contributing

## Development Setup

```bash
git clone https://github.com/dstours/fluffy-barnacle.git
cd fluffy-barnacle
python3 -m venv venv
source venv/bin/activate
pip install -e ".[dev]"
```

## Running Tests

```bash
python -m pytest tests/ -v
```

The test suite includes:

- **API contract tests** -- verify all public exports survive refactoring
- **Installation tests** -- verify imports, logging, configuration, and module structure

## Code Style

This project uses [Black](https://github.com/psf/black) for formatting:

```bash
black csproxy/
```

Lint with flake8:

```bash
flake8 csproxy/
```

Type check with mypy:

```bash
mypy csproxy/
```

## Project Structure

See the [Architecture](architecture.md) page for a detailed module breakdown.

## Making Changes

1. Create a feature branch from `main`
2. Make your changes
3. Run the test suite: `python -m pytest tests/ -v`
4. Format with Black: `black csproxy/`
5. Submit a pull request

## Adding a New Proxied Tool Wrapper

To add a wrapper for a new tool, add a function in `csproxy/tools.py`:

```python
def pnewtool(
    args: List[str],
    host: str = '127.0.0.1',
    port: Optional[int] = None,
    *,
    timeout: Optional[int] = 300,
) -> int:
    """Run newtool through the SOCKS5 proxy."""
    config = Config()
    port = port or _get_proxy_port(config)
    if not check_proxy(host, port):
        return 1
    return subprocess.run(
        ['newtool', '--proxy', f'socks5://{host}:{port}'] + args,
        timeout=timeout,
    ).returncode
```

Then add it to `TOOL_COMMANDS` and export it from `__init__.py`.

## Building Documentation

```bash
pip install -e ".[docs]"
mkdocs serve              # local preview at http://127.0.0.1:8000
mkdocs build --strict     # build for production
```

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
