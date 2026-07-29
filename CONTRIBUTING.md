# Contributing to H.A.T.S.

Thank you for your interest in contributing to H.A.T.S!

## Development Setup

1. **Clone & Install**:
   ```bash
   git clone https://github.com/Alokkr00/HATS-Trading-Engine.git
   cd HATS-Trading-Engine
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```

2. **Run Tests**:
   ```bash
   pytest
   ```

3. **Adding a New Strategy**:
   * Inherit from `BaseStrategy` in `src/strategy/base.py`.
   * Implement `generate_signals(self, df: pd.DataFrame) -> pd.DataFrame`.
   * Ensure `DatetimeIndex` is timezone-aware (`America/New_York`).
   * Add unit tests in `tests/test_strategy/`.
