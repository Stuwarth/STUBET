# 🏆 Sports AI Predictor

Sistema de Machine Learning para predicción deportiva y detección de value bets.

## 🚀 Inicio Rápido

### 1. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 2. Configurar API Keys (Opcional)
```bash
cp .env.example .env
# Editar .env con tus API keys
```

**APIs Gratuitas:**
- [API-Football](https://www.api-football.com/) — 100 requests/día gratis
- [The Odds API](https://the-odds-api.com/) — 500 requests/mes gratis

### 3. Iniciar el servidor
```bash
cd backend
python main.py
```

### 4. Abrir el dashboard
Visita: **http://localhost:8000**

### 5. Generar datos demo (para probar)
Click en el botón **"🎮 Generar Demo Data"** en la sección de Modelos ML.

## 📊 Características

### Machine Learning
- **Modelos**: XGBoost, LightGBM, Random Forest, Gradient Boosting
- **Feature Engineering**: 130+ features por partido
- **Mercados**: 1X2, Over/Under 2.5, BTTS, Corners, Tarjetas
- **Validación**: Time-Series Cross-Validation (sin data leakage)

### Value Bet Detection
- Comparación probabilidades del modelo vs cuotas del bookmaker
- Detección de errores de cuota
- Kelly Criterion para gestión de bankroll
- Clasificación: Value ✅ → Fuerte 🔥 → Premium ⚡

### Dashboard Premium
- UI moderna con glassmorphism y animaciones
- Gráficos de rendimiento en tiempo real
- Tracking de predicciones con auto-liquidación
- Panel de value bets con métricas detalladas

## 🏗️ Arquitectura

```
Data Layer → Feature Engineering → ML Models → Value Detection → Dashboard
     ↓              ↓                  ↓             ↓              ↓
  API-Football    130+ features    XGBoost+    Kelly Criterion   FastAPI
  The Odds API       form        LightGBM     Odds Analysis     + HTML5
  Web Scraping      H2H, stats   Ensemble     Error Detection   Canvas
```

## 📁 Estructura

```
sports-ai-predictor/
├── backend/
│   ├── api/server.py          ← FastAPI endpoints
│   ├── ml/predictor.py        ← Motor de predicción
│   ├── ml/feature_engineering.py ← 130+ features
│   ├── data/collectors/       ← Recolección de datos
│   ├── analysis/              ← Performance tracking
│   └── config.py              ← Configuración
├── frontend/
│   ├── index.html             ← Dashboard
│   ├── css/style.css          ← Estilos premium
│   └── js/app.js              ← Lógica del dashboard
└── data/                      ← Base de datos y modelos
```

## 🎯 API Endpoints

| Método | Endpoint | Descripción |
|--------|----------|-------------|
| GET | `/api/dashboard` | Datos del dashboard |
| GET | `/api/predictions` | Ver predicciones |
| POST | `/api/predict/match` | Predecir un partido |
| POST | `/api/predict/upcoming` | Predecir próximos partidos |
| GET | `/api/value-bets` | Value bets activos |
| GET | `/api/performance` | Métricas de rendimiento |
| POST | `/api/train` | Entrenar modelos |
| POST | `/api/demo/generate` | Generar datos demo |

## ⚠️ Disclaimer

Este sistema es una herramienta de análisis y NO garantiza ganancias. Las apuestas deportivas implican riesgo. Usa este sistema de manera responsable y nunca apuestes más de lo que puedes permitirte perder.
