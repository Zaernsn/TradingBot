"""Chronological training, calibration and validation with horizon gaps."""
import os
import pickle
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import brier_score_loss
from app.ml.features import build_features, make_target

MODEL_DIR = Path(os.environ.get('MODEL_DIR', './models'))
MODEL_DIR.mkdir(exist_ok=True)
MODEL_VERSION = 2


def apply_buy_threshold(prediction, threshold):
    """Adjust entry policy only after model validation and current-data checks."""
    if prediction is None or prediction.get('status') != 'ready' or not prediction.get('entry_qualified'):
        return prediction
    probability = prediction['probability']
    prediction['action'] = 'BUY' if probability > threshold else 'SELL' if probability < .4 else 'HOLD'
    prediction['diagnostics'] = {**prediction.get('diagnostics', {}),
                                 'entry_threshold': threshold}
    prediction['explanation'] = (prediction.get('explanation', '') +
                                f' Configured BUY threshold: above {threshold:.1%}.')
    return prediction


class SignalModel:
    def __init__(self, name='ensemble', persist=True, feature_schema='legacy'):
        if feature_schema not in {'legacy', 'normalized-v1'}:
            raise ValueError('Unknown feature schema')
        self.feature_schema = feature_schema
        self.name = name
        self.persist = persist
        self.scaler = StandardScaler()
        self.lr = LogisticRegression(max_iter=1000)
        self.rf = RandomForestClassifier(n_estimators=80, max_depth=5, min_samples_leaf=5, random_state=42)
        self.calibrator = LogisticRegression()
        self.feature_cols = []
        self.is_fitted = False
        self.trained_at = None
        self.training_end = None
        self.training_start = None
        self.fit_window_end = None
        self.signature = None
        self.validation = {}
        self.failure_reason = 'Not trained'
        self.train_mean = None
        self.train_std = None

    def _feature_cols(self, df):
        return [c for c in df.columns if c not in {'open', 'high', 'low', 'close', 'volume'}]

    def needs_retrain(self, horizon, fee_pct, slippage_pct, now=None):
        now = now or datetime.now(timezone.utc)
        return (not self.is_fitted or self.signature != (horizon, fee_pct, slippage_pct)
                or self.trained_at is None or now - self.trained_at >= timedelta(days=1))

    def _raw(self, X):
        return (self.lr.predict_proba(self.scaler.transform(X))[:, 1]
                + self.rf.predict_proba(X)[:, 1]) / 2

    def fit(self, candles, horizon=12, fee_pct=.0026, slippage_pct=.001):
        self.is_fitted = False
        self.validation = {}
        df = self._features(candles)
        if df.empty:
            self.failure_reason = 'No usable completed candles'
            return self
        y = make_target(df, horizon, fee_pct, slippage_pct)
        valid = y.notna()
        df, y = df.loc[valid], y.loc[valid].astype(int)
        n = len(df)
        train_end = int(n * .6)
        calibration_end = int(n * .8)
        calibration_start = train_end + horizon
        validation_start = calibration_end + horizon
        if train_end < 120 or calibration_end - calibration_start < 30 or n - validation_start < 30:
            self.failure_reason = 'Insufficient history for training, calibration and purged validation'
            return self
        splits = {'training': (0, train_end), 'calibration': (calibration_start, calibration_end),
                  'validation': (validation_start, n)}
        outcomes = {name: {'cost_covering': int(y.iloc[a:b].sum()),
                           'not_cost_covering': int(len(y.iloc[a:b]) - y.iloc[a:b].sum())}
                    for name, (a, b) in splits.items()}
        self.validation = {'class_counts': outcomes, 'total_labeled_rows': n, 'horizon_gap': horizon}
        missing = [f'{name}: {counts["cost_covering"]} cost-covering rises, '
                   f'{counts["not_cost_covering"]} other outcomes'
                   for name, counts in outcomes.items() if 0 in counts.values()]
        if missing:
            self.failure_reason = 'Insufficient outcome diversity (' + '; '.join(missing) + '). Waiting for more varied completed history.'
            return self
        self.feature_cols = self._feature_cols(df)
        X = df[self.feature_cols]
        train = X.iloc[:train_end]
        self.lr.fit(self.scaler.fit_transform(train), y.iloc[:train_end])
        self.rf.fit(train, y.iloc[:train_end])
        self.calibrator.fit(self._raw(X.iloc[calibration_start:calibration_end]).reshape(-1,1),
                            y.iloc[calibration_start:calibration_end])
        predictions = self.calibrator.predict_proba(self._raw(X.iloc[validation_start:]).reshape(-1,1))[:,1]
        truth = y.iloc[validation_start:]
        self.validation = {
            'class_counts': outcomes,
            'brier_score': float(brier_score_loss(truth, predictions)),
            'baseline_brier': float(brier_score_loss(truth, np.full(len(truth), y.iloc[:train_end].mean()))),
            'validation_rows': len(truth), 'training_rows': train_end,
            'calibration_rows': calibration_end-calibration_start,
            'horizon_gap': horizon, 'total_labeled_rows': n,
            'thresholds': {'buy': .6, 'sell': .4},
        }
        self.train_mean = train.mean()
        self.train_std = train.std().clip(lower=1e-8)
        self.trained_at = datetime.now(timezone.utc)
        self.training_end = candles[-1].timestamp
        self.training_start = candles[int(df.index[0])].timestamp
        self.fit_window_end = candles[int(df.index[train_end-1])].timestamp
        self.signature = (horizon, fee_pct, slippage_pct)
        self.failure_reason = ''
        self.is_fitted = True
        if self.persist:
            self._save()
        return self

    def entry_qualified(self):
        """Minimum predictive check, not evidence of profitable trading."""
        try:
            score = float(self.validation['brier_score'])
            baseline = float(self.validation['baseline_brier'])
            rows = float(self.validation['validation_rows'])
            return bool(self.is_fitted and np.isfinite(rows) and rows >= 30
                        and np.isfinite(score) and np.isfinite(baseline)
                        and 0 <= score < baseline <= 1)
        except (KeyError, TypeError, ValueError):
            return False

    def _features(self, candles):
        return build_features(candles, normalized=True) if self.feature_schema == 'normalized-v1' else build_features(candles)

    def diagnostics(self, candles):
        def stamp(value):
            return value.isoformat() if value is not None else None
        return {'feature_schema':self.feature_schema, 'trained_at':stamp(self.trained_at),
                'training_start':stamp(self.training_start), 'training_end':stamp(self.training_end),
                'fit_window_end':stamp(self.fit_window_end), 'history_rows':len(candles),
                'latest_candle':stamp(candles[-1].timestamp) if candles else None,
                'validation':self.validation, 'drift_threshold':8.}

    def predict(self, candles):
        df = self._features(candles)
        details = self.diagnostics(candles)
        hold = {'action':'HOLD','probability':.5,'confidence':0.,'entry_qualified':False,
                'status':'model_unavailable', 'diagnostics':details,
                'explanation':self.failure_reason or 'Model unavailable'}
        if df.empty or not self.is_fitted:
            return hold
        if candles and df.index[-1] != len(candles)-1:
            return {**hold, 'status':'data_unavailable', 'explanation':'Latest candle has unusable features; waiting for valid data.'}
        X = df[self.feature_cols].iloc[[-1]]
        deviations = ((X.iloc[0]-self.train_mean).abs()/self.train_std)
        drift = float(deviations.max())
        details['drift_features'] = [
            {'feature':col, 'value':float(X[col].iloc[0]), 'training_mean':float(self.train_mean[col]),
             'training_scale':float(self.train_std[col]), 'deviation':float(deviation)}
            for col,deviation in deviations.sort_values(ascending=False).items() if deviation > 8][:5]
        if drift > 8:
            feature=details['drift_features'][0]
            return {**hold, 'status':'drift', 'drift_detected': True,
                    'explanation':f'Unfamiliar market data: {feature["feature"]} is {feature["deviation"]:.1f} training standard deviations from its average (limit 8). Entry withheld; recovery will be evaluated.'}
        prob = float(self.calibrator.predict_proba(self._raw(X).reshape(-1,1))[0,1])
        action = 'BUY' if prob > .6 else 'SELL' if prob < .4 else 'HOLD'
        qualified = self.entry_qualified()
        blocked = action == 'BUY' and not qualified
        if blocked:
            action = 'HOLD'
        return {'action':action, 'probability':round(prob,4), 'confidence':round(abs(prob-.5)*2,4),
                'entry_qualified': qualified,
                'status':'ready' if qualified else 'validation_failed', 'diagnostics':details,
                'features': {col:float(X[col].iloc[0]) for col in self.feature_cols},
                'explanation': f'Calibrated probability of return exceeding costs: {prob:.1%}. '
                               f'Validation Brier: {self.validation.get("brier_score", "unavailable")}. '
                               + ('Entry withheld: insufficient validation or no improvement over baseline. ' if blocked else '') +
                               'Signal strength is distance from neutral, not a profit guarantee.'}

    def _save(self):
        payload = {k:v for k,v in self.__dict__.items() if k != 'persist'}
        payload['version'] = MODEL_VERSION
        handle, temporary = tempfile.mkstemp(dir=MODEL_DIR, suffix='.tmp')
        try:
            with os.fdopen(handle, 'wb') as stream:
                pickle.dump(payload, stream)
            os.replace(temporary, MODEL_DIR / f'{self.name}.pkl')
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def load_active(self):
        """Runtime resumes the automatically selected, schema-tagged artifact."""
        self.load(allow_schema_switch=True)

    def load(self, allow_schema_switch=False):
        path = MODEL_DIR / f'{self.name}.pkl'
        if not path.exists(): return
        try:
            with path.open('rb') as stream: data = pickle.load(stream)
            if data.pop('version', None) != MODEL_VERSION: return
            schema=data.get('feature_schema','legacy')
            if schema not in {'legacy','normalized-v1'}: return
            if schema != self.feature_schema and not allow_schema_switch: return
            self.__dict__.update(data)
        except (OSError, ValueError, EOFError, pickle.UnpicklingError):
            self.is_fitted = False
