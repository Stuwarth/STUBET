"""
Main Predictor Engine - Multi-model prediction system for sports betting.
Uses XGBoost, LightGBM, and Random Forest for different markets.
"""
import numpy as np
import pandas as pd
import joblib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from sklearn.model_selection import TimeSeriesSplit, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, classification_report, log_loss
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
import warnings
warnings.filterwarnings('ignore')

try:
    from xgboost import XGBClassifier, XGBRegressor
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    from lightgbm import LGBMClassifier, LGBMRegressor
    HAS_LIGHTGBM = True
except ImportError:
    HAS_LIGHTGBM = False

import sys
sys.path.append(str(Path(__file__).parent.parent))
from config import ML_CONFIG, MODELS_DIR, MARKETS
from ml.feature_engineering import FeatureEngineer
from data.database import DatabaseManager


class SportsPredictor:
    """Multi-market sports prediction engine using ensemble ML models."""
    
    # Feature columns (excluding targets and metadata)
    EXCLUDE_COLS = [
        'match_id', 'match_date',
        'target_result', 'target_total_goals', 'target_over_25',
        'target_btts', 'target_home_goals', 'target_away_goals'
    ]
    
    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager()
        self.fe = FeatureEngineer(self.db)
        self.models = {}
        self.scalers = {}
        self.feature_names = {}
        self.model_dir = MODELS_DIR
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.config = ML_CONFIG
        self.version = "v1.0"
    
    def train_all_models(self, league_id: int = None):
        """Train all market prediction models."""
        print("\n🧠 Starting model training pipeline...")
        print("=" * 60)
        
        # Build training data
        df = self.fe.build_training_dataset(league_id)
        
        if df.empty or len(df) < self.config["min_samples"]:
            print(f"❌ Insufficient data for training ({len(df)} samples)")
            return False
        
        # Get feature columns
        feature_cols = [c for c in df.columns if c not in self.EXCLUDE_COLS]
        self.feature_names["all"] = feature_cols
        
        # Handle missing values
        df[feature_cols] = df[feature_cols].fillna(0)
        
        # Train each market model
        results = {}
        
        # 1. Match Result (1X2)
        print("\n📊 Training: Match Result (1X2)")
        results["match_result"] = self._train_classifier(
            df, feature_cols, "target_result",
            model_name="match_result",
            n_classes=3
        )
        
        # 2. Over/Under 2.5
        print("\n📊 Training: Over/Under 2.5 Goals")
        results["over_under_25"] = self._train_classifier(
            df, feature_cols, "target_over_25",
            model_name="over_under_25",
            n_classes=2
        )
        
        # 3. BTTS
        print("\n📊 Training: Both Teams To Score")
        results["btts"] = self._train_classifier(
            df, feature_cols, "target_btts",
            model_name="btts",
            n_classes=2
        )
        
        # Results summary
        print("\n" + "=" * 60)
        print("📈 TRAINING RESULTS SUMMARY")
        print("=" * 60)
        for market, result in results.items():
            if result:
                print(f"  {market}: Accuracy={result['accuracy']:.1%}, "
                      f"CV={result['cv_mean']:.1%} ± {result['cv_std']:.1%}")
        
        # Save metadata
        self._save_training_metadata(results)
        
        return True
    
    def _train_classifier(self, df: pd.DataFrame, feature_cols: List[str],
                          target_col: str, model_name: str,
                          n_classes: int = 2) -> Optional[dict]:
        """Train a classifier for a specific market."""
        X = df[feature_cols].values
        y = df[target_col].values
        
        # Scale features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # Time-series aware split (don't randomly shuffle temporal data!)
        tscv = TimeSeriesSplit(n_splits=5)
        
        # Split into train/test (last 20% as test)
        split_idx = int(len(X) * 0.8)
        X_train, X_test = X_scaled[:split_idx], X_scaled[split_idx:]
        y_train, y_test = y[:split_idx], y[split_idx:]
        
        # Build ensemble of models
        models_to_try = []
        
        if HAS_XGBOOST:
            models_to_try.append((
                "XGBoost",
                XGBClassifier(
                    n_estimators=self.config["n_estimators"],
                    max_depth=self.config["max_depth"],
                    learning_rate=self.config["learning_rate"],
                    random_state=self.config["random_state"],
                    use_label_encoder=False,
                    eval_metric='mlogloss' if n_classes > 2 else 'logloss',
                    verbosity=0
                )
            ))
        
        if HAS_LIGHTGBM:
            models_to_try.append((
                "LightGBM",
                LGBMClassifier(
                    n_estimators=self.config["n_estimators"],
                    max_depth=self.config["max_depth"],
                    learning_rate=self.config["learning_rate"],
                    random_state=self.config["random_state"],
                    verbose=-1
                )
            ))
        
        models_to_try.append((
            "RandomForest",
            RandomForestClassifier(
                n_estimators=300,
                max_depth=self.config["max_depth"],
                random_state=self.config["random_state"],
                n_jobs=-1
            )
        ))
        
        models_to_try.append((
            "GradientBoosting",
            GradientBoostingClassifier(
                n_estimators=300,
                max_depth=self.config["max_depth"],
                learning_rate=self.config["learning_rate"],
                random_state=self.config["random_state"]
            )
        ))
        
        # Train and evaluate each model
        best_model = None
        best_name = None
        best_accuracy = 0
        best_cv_scores = None
        
        for name, model in models_to_try:
            try:
                model.fit(X_train, y_train)
                y_pred = model.predict(X_test)
                accuracy = accuracy_score(y_test, y_pred)
                
                # Cross-validation on training data
                cv_scores = cross_val_score(model, X_train, y_train, cv=tscv, scoring='accuracy')
                
                print(f"  {name}: Test Acc={accuracy:.3f}, CV={cv_scores.mean():.3f} ± {cv_scores.std():.3f}")
                
                if accuracy > best_accuracy:
                    best_accuracy = accuracy
                    best_model = model
                    best_name = name
                    best_cv_scores = cv_scores
                    
            except Exception as e:
                print(f"  ⚠️ {name} failed: {e}")
        
        if best_model is None:
            return None
        
        print(f"  ✅ Best: {best_name} ({best_accuracy:.3f})")
        
        # Save model and scaler
        self.models[model_name] = best_model
        self.scalers[model_name] = scaler
        self.feature_names[model_name] = feature_cols
        
        joblib.dump(best_model, self.model_dir / f"{model_name}_model.pkl")
        joblib.dump(scaler, self.model_dir / f"{model_name}_scaler.pkl")
        joblib.dump(feature_cols, self.model_dir / f"{model_name}_features.pkl")
        
        # Feature importance
        if hasattr(best_model, 'feature_importances_'):
            importances = best_model.feature_importances_
            top_features = sorted(zip(feature_cols, importances),
                                  key=lambda x: x[1], reverse=True)[:15]
            print(f"  📊 Top features:")
            for feat, imp in top_features[:5]:
                print(f"     {feat}: {imp:.4f}")
        
        return {
            "model_name": best_name,
            "accuracy": best_accuracy,
            "cv_mean": best_cv_scores.mean(),
            "cv_std": best_cv_scores.std(),
            "train_size": len(X_train),
            "test_size": len(X_test),
            "feature_count": len(feature_cols),
        }
    
    def predict_match(self, home_team_id: int, away_team_id: int,
                      league_id: int = None) -> Dict[str, dict]:
        """Generate predictions for all markets for a specific match.
        
        Returns:
            Dict with market predictions, each containing:
            - prediction: str (the predicted outcome)
            - probabilities: dict (probability for each class)
            - confidence: str (LOW/MEDIUM/HIGH)
            - details: dict (additional analysis)
        """
        # Build features
        features = self.fe.build_features_for_match(home_team_id, away_team_id, league_id)
        
        predictions = {}
        
        # Predict each market
        for market in ["match_result", "over_under_25", "btts"]:
            if market not in self.models:
                self._load_model(market)
            
            if market not in self.models:
                continue
            
            model = self.models[market]
            scaler = self.scalers[market]
            feat_names = self.feature_names.get(market, self.feature_names.get("all", []))
            
            # Prepare input
            X = np.array([[features.get(f, 0) for f in feat_names]])
            X = np.nan_to_num(X, nan=0.0)
            X_scaled = scaler.transform(X)
            
            # Predict probabilities
            proba = model.predict_proba(X_scaled)[0]
            pred_class = model.predict(X_scaled)[0]
            
            # Market-specific formatting
            if market == "match_result":
                labels = {0: "Home Win", 1: "Draw", 2: "Away Win"}
                pred_label = labels.get(pred_class, "Unknown")
                prob_dict = {labels[i]: round(float(p) * 100, 1) for i, p in enumerate(proba)}
            
            elif market == "over_under_25":
                labels = {0: "Under 2.5", 1: "Over 2.5"}
                pred_label = labels.get(pred_class, "Unknown")
                prob_dict = {labels[i]: round(float(p) * 100, 1) for i, p in enumerate(proba)}
            
            elif market == "btts":
                labels = {0: "No", 1: "Yes"}
                pred_label = f"BTTS {labels.get(pred_class, 'Unknown')}"
                prob_dict = {f"BTTS {labels[i]}": round(float(p) * 100, 1) for i, p in enumerate(proba)}
            
            # Confidence level
            max_prob = max(proba)
            if max_prob >= 0.65:
                confidence = "HIGH"
            elif max_prob >= 0.55:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"
            
            predictions[market] = {
                "prediction": pred_label,
                "probabilities": prob_dict,
                "confidence": confidence,
                "max_probability": round(float(max_prob) * 100, 1),
                "raw_probabilities": [round(float(p), 4) for p in proba],
            }
        
        # Add meta-analysis
        predictions["analysis"] = self._generate_analysis(features, predictions)
        
        return predictions
    
    def predict_upcoming(self, league_id: int = None, days_ahead: int = 7) -> List[dict]:
        """Predict all upcoming matches."""
        upcoming = self.db.get_upcoming_matches(league_id, days_ahead)
        
        if not upcoming:
            print("⚠️ No upcoming matches found")
            return []
        
        results = []
        for match in upcoming:
            try:
                preds = self.predict_match(
                    match["home_team_id"],
                    match["away_team_id"],
                    match.get("league_id")
                )
                
                result = {
                    "match_id": match["api_id"],
                    "match_date": match["match_date"],
                    "home_team": match.get("home_team_name", "Unknown"),
                    "away_team": match.get("away_team_name", "Unknown"),
                    "league": match.get("league_name", "Unknown"),
                    "home_logo": match.get("home_logo", ""),
                    "away_logo": match.get("away_logo", ""),
                    "predictions": preds,
                }
                
                # Save predictions to DB
                for market, pred in preds.items():
                    if market == "analysis":
                        continue
                    self.db.save_prediction({
                        "match_id": match["api_id"],
                        "market": market,
                        "prediction": pred["prediction"],
                        "probability": pred["max_probability"] / 100,
                        "confidence": pred["confidence"],
                        "model_version": self.version,
                    })
                
                results.append(result)
                
            except Exception as e:
                print(f"⚠️ Error predicting {match.get('home_team_name', '?')} vs "
                      f"{match.get('away_team_name', '?')}: {e}")
        
        return results
    
    def _generate_analysis(self, features: dict, predictions: dict) -> dict:
        """Generate a meta-analysis of the predictions."""
        analysis = {
            "home_strength": round(features.get("home_strength", 0) * 100, 1),
            "away_strength": round(features.get("away_strength", 0) * 100, 1),
            "strength_diff": round(features.get("strength_diff", 0) * 100, 1),
            "home_form": round(features.get("home_weighted_form", 0) * 100, 1),
            "away_form": round(features.get("away_weighted_form", 0) * 100, 1),
            "home_scoring_avg": round(features.get("home_goals_scored_avg", 0), 2),
            "away_scoring_avg": round(features.get("away_goals_scored_avg", 0), 2),
            "home_conceding_avg": round(features.get("home_goals_conceded_avg", 0), 2),
            "away_conceding_avg": round(features.get("away_goals_conceded_avg", 0), 2),
            "h2h_matches": features.get("h2h_total_matches", 0),
        }
        
        # Key insights
        insights = []
        
        if features.get("home_win_streak", 0) >= 3:
            insights.append(f"🔥 Home team on {features['home_win_streak']}-match winning streak")
        if features.get("away_win_streak", 0) >= 3:
            insights.append(f"🔥 Away team on {features['away_win_streak']}-match winning streak")
        if features.get("home_loss_streak", 0) >= 3:
            insights.append(f"⚠️ Home team lost last {features['home_loss_streak']} matches")
        if features.get("away_loss_streak", 0) >= 3:
            insights.append(f"⚠️ Away team lost last {features['away_loss_streak']} matches")
        
        if abs(features.get("strength_diff", 0)) > 0.2:
            stronger = "Home" if features.get("strength_diff", 0) > 0 else "Away"
            insights.append(f"💪 Significant strength advantage for {stronger} team")
        
        if features.get("home_over_25_rate", 0) > 0.7 and features.get("away_over_25_rate", 0) > 0.7:
            insights.append("⚽ Both teams involved in high-scoring games recently")
        
        if features.get("h2h_over_25_rate", 0) > 0.7:
            insights.append("📊 H2H history suggests Over 2.5 goals likely")
        
        analysis["insights"] = insights
        
        return analysis
    
    def _load_model(self, market: str):
        """Load a saved model from disk."""
        model_path = self.model_dir / f"{market}_model.pkl"
        scaler_path = self.model_dir / f"{market}_scaler.pkl"
        features_path = self.model_dir / f"{market}_features.pkl"
        
        if model_path.exists() and scaler_path.exists():
            self.models[market] = joblib.load(model_path)
            self.scalers[market] = joblib.load(scaler_path)
            if features_path.exists():
                self.feature_names[market] = joblib.load(features_path)
            print(f"✅ Loaded model: {market}")
        else:
            print(f"⚠️ No saved model found for {market}")
    
    def _save_training_metadata(self, results: dict):
        """Save training metadata."""
        import json
        meta = {
            "version": self.version,
            "trained_at": datetime.now().isoformat(),
            "models": results,
        }
        meta_path = self.model_dir / "training_metadata.json"
        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=2, default=str)
    
    def get_model_info(self) -> dict:
        """Get information about loaded models."""
        info = {
            "version": self.version,
            "loaded_models": list(self.models.keys()),
            "available_markets": MARKETS,
        }
        
        meta_path = self.model_dir / "training_metadata.json"
        if meta_path.exists():
            import json
            with open(meta_path) as f:
                info["training_metadata"] = json.load(f)
        
        return info
