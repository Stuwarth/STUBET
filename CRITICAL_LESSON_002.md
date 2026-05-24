# 🚨 LECCIÓN CRÍTICA DE APUESTAS 002: ERROR EN MERCADOS COMBINADOS (FALSOS POSITIVOS)

**Fecha:** 12 Mayo 2026
**Partido:** Al-Nassr vs Al-Hilal (Saudi Pro League)
**Pick Fallido:** Doble Oportunidad (12) + Más de 1.5 goles + Tarjetas Menos de 8.5
**Motivo de Pérdida:** El partido terminó en empate 1-1 (Fallo en la pata de Doble Oportunidad 12).

## 🐛 EL ERROR ALGORÍTMICO (PUNTO CIEGO DE LA IA)
El script de análisis masivo (`fase3_definitivo.py`) cometió un error letal de lógica de programación al evaluar mercados del tipo "Combinación" o "Crear Apuesta". 
Cuando analizó la cadena de texto `"Doble oportunidad y total 1.5 de goles | Al Nassr FC/Al Hilal y más de 1.5"`, el código solo detectó la palabra clave `"goles"` y le asignó la métrica global de `total_goals > 1.5`. 
**Ignoró por completo evaluar la condición de la Doble Oportunidad (12).**

Esto provocó que el algoritmo arrojara un **falso 100% de Probabilidad Real (PR)** en el H2H, porque efectivamente en los últimos 10 partidos directos siempre hubo más de 1.5 goles, pero **NO** siempre hubo un ganador (hubo empates 1-1 que el script no restó como derrotas).

## 🧠 LA LECCIÓN DE ORO
1. **Nunca evaluar mercados combinados con una sola métrica:** Si un mercado incluye Resultado + Goles (Ej. "1X y +1.5 goles"), el código DEBE exigir una doble validación booleana: `(resultado_empate_o_local == True) AND (goles > 1.5)`. Si no se puede programar esa doble validación, el mercado debe descartarse del análisis automático.
2. **Respetar la intuición humana (Fase 1):** El usuario detectó el peligro del empate ("algo me decía poner gana o empate"). La IA se cegó por su propio falso 100%. Cuando el instinto del apostador choca con un "100% estadístico" en un Clásico o Final, el instinto humano y el contexto suelen tener la razón.

## 🛡️ PROTOCOLO A FUTURO
A partir de ahora, **TODO mercado de combinación** sugerido por la IA debe ser desglosado y verificado manualmente pata por pata en el historial H2H antes de ser etiquetado como "Stake 10". No se confiará ciegamente en el output del script para apuestas combinadas complejas.
