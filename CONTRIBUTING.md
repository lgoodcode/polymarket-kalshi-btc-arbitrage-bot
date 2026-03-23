# Contributing to Polymarket-Kalshi BTC Arbitrage Bot

First off, thanks for taking the time to contribute! 🎉

The following is a set of guidelines for contributing to this project. These are mostly guidelines, not rules. Use your best judgment, and feel free to propose changes to this document in a pull request.

## 🚀 How Can I Contribute?

### Reporting Bugs
This section guides you through submitting a bug report.
-   **Use a clear and descriptive title** for the issue to identify the problem.
-   **Describe the exact steps to reproduce the problem** in as much detail as possible.
-   **Include screenshots** if possible.

### Suggesting Enhancements
This section guides you through submitting an enhancement suggestion, including completely new features and minor improvements to existing functionality.
-   **Use a clear and descriptive title** for the issue to identify the suggestion.
-   **Provide a step-by-step description of the suggested enhancement** in as much detail as possible.
-   **Explain why this enhancement would be useful** to most users.

### Pull Requests
1.  Fork the repo and create your branch from `main`.
2.  If you've added code that should be tested, add tests.
3.  Ensure the test suite passes.
4.  Make sure your code lints.
5.  Issue that pull request!

## 💻 Development Setup

1.  **Clone the repo**:
    ```bash
    git clone https://github.com/CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot.git
    ```

2.  **Backend Setup**:
    ```bash
    cd backend
    pip install -r requirements.txt
    python3 api.py
    ```

3.  **Frontend Setup**:
    ```bash
    cd frontend
    npm install
    npm run dev
    ```

## 🧪 Running Tests

Before submitting a pull request, ensure all tests pass:

```bash
cd backend
pip install -r requirements.txt

# Run all offline tests (unit + integration)
pytest tests/ -m "not live" -v

# Run only integration tests
pytest tests/ -m integration -v
```

Test markers are configured in `backend/pyproject.toml`:
- `integration` — full-pipeline tests with mocked HTTP
- `live` — tests that hit real external APIs (skip by default)

## 🎨 Styleguides

### Python
-   Follow [PEP 8](https://www.python.org/dev/peps/pep-0008/).
-   Use descriptive variable names.

### TypeScript / React
-   Use functional components.
-   Use Tailwind CSS for styling.
-   Follow the existing directory structure.

## 📝 License
By contributing, you agree that your contributions will be licensed under its MIT License.
