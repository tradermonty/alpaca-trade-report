# Contributing to Alpaca Trade Report Generator

Thank you for your interest in contributing to the Alpaca Trade Report Generator! We welcome contributions from the community.

## Getting Started

1. Fork the repository
2. Clone your fork locally
3. Create a new branch for your feature or bugfix
4. Make your changes
5. Test your changes
6. Submit a pull request

## Development Setup

1. Follow the installation instructions in the README
2. Install development dependencies:
   ```bash
   pip install black isort flake8 mypy pytest
   ```

## Code Style

We use the following tools to maintain code quality:

- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **mypy**: Type checking

Run these commands before submitting:

```bash
black src/
isort src/
flake8 src/
mypy src/
```

## Testing

Currently, the test suite is minimal. We welcome contributions to improve test coverage:

```bash
pytest
pytest -v  # Verbose output
```

## Submitting Changes

1. **Commit Messages**: Use clear, descriptive commit messages
2. **Pull Requests**: 
   - Provide a clear description of what your changes do
   - Reference any related issues
   - Include tests for new functionality
   - Ensure all existing tests pass

## Code Guidelines

- Follow PEP 8 style guidelines
- Add type hints to new functions
- Include docstrings for new modules, classes, and functions
- Keep functions focused and modular
- Handle errors gracefully

## Areas for Contribution

We particularly welcome contributions in these areas:

- **Test Coverage**: Expand the test suite
- **Documentation**: Improve code documentation and user guides
- **Performance**: Optimize data processing and API calls
- **Features**: Add new analysis metrics or visualization options
- **Bug Fixes**: Identify and fix bugs

## API Integration Guidelines

When working with external APIs:

- Implement proper error handling
- Add rate limiting where appropriate
- Follow the graceful degradation pattern (optional APIs should not break core functionality)
- Log meaningful error messages

## Reporting Issues

When reporting bugs, please include:

- Python version
- Operating system
- Steps to reproduce the issue
- Expected vs actual behavior
- Error messages or logs

## Questions?

Feel free to open an issue for questions about:
- How to implement a feature
- Code architecture decisions
- API integration approaches

## License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.