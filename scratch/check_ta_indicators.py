import pandas as pd
import numpy as np
import pandas_ta as ta

# Create dummy OHLCV data
dates = pd.date_range("2026-01-01", periods=100, freq="D", tz="UTC")
df = pd.DataFrame({
    "open": np.random.uniform(100, 110, 100),
    "high": np.random.uniform(110, 120, 100),
    "low": np.random.uniform(90, 100, 100),
    "close": np.random.uniform(100, 110, 100),
    "volume": np.random.uniform(1000, 5000, 100)
}, index=dates)

print("--- ADX ---")
adx = df.ta.adx(length=14)
print(type(adx))
if adx is not None:
    print(adx.columns)

print("--- STOCH ---")
stoch = df.ta.stoch(k=14, d=3)
print(type(stoch))
if stoch is not None:
    print(stoch.columns)

print("--- CCI ---")
cci = df.ta.cci(length=14)
print(type(cci))
if cci is not None:
    print(cci.name if hasattr(cci, "name") else cci.columns)

print("--- OBV ---")
obv = df.ta.obv()
print(type(obv))
if obv is not None:
    print(obv.name if hasattr(obv, "name") else obv.columns)

print("--- ROC ---")
roc = df.ta.roc(length=10)
print(type(roc))
if roc is not None:
    print(roc.name if hasattr(roc, "name") else roc.columns)

print("--- WILLR ---")
willr = df.ta.willr(length=14)
print(type(willr))
if willr is not None:
    print(willr.name if hasattr(willr, "name") else willr.columns)

print("--- MFI ---")
mfi = df.ta.mfi(length=14)
print(type(mfi))
if mfi is not None:
    print(mfi.name if hasattr(mfi, "name") else mfi.columns)
