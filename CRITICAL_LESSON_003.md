# CRITICAL LESSON 003: EL FRACASO DEL "JUICIO DEL BERNABÉU" Y LA TRAMPA DEL SCRIPT

## Fecha: 14 de Mayo 2026
**Contexto del Fracaso:** 
Fallo catastrófico de dos recomendaciones principales tras el error de Al-Nassr. Pérdidas económicas significativas y daño a la reputación de STUBET con sus clientes.

## Errores Identificados:

### 1. Falla Crítica en el Algoritmo de Extracción (Bug Técnico)
El script Python cometió un error de mapeo fatal:
- **El Error:** Al leer la estadística de "Yellow cards" en la 1ra mitad, el script sumó las tarjetas de ambos equipos (`ly + ry`) y asignó ese total a la variable `madrid_yellows`.
- **La Consecuencia:** El algoritmo arrojó un falso "100% de acierto" para la tarjeta de la primera mitad del Madrid. 
- **La Lección:** **CERO TOLERANCIA A BUGS EN SCRIPTS.** Antes de dar un Stake, el analista de IA debe obligatoriamente cruzar el "100%" del script con una revisión visual de los datos crudos para validar que el código no haya sumado variables incorrectas.

### 2. La Falacia de la "Defensa Suplente" (Error Psicológico/Táctico)
- **El Error:** Se recomendó "Real Oviedo Más de 2.5 Tiros a Puerta" basándose en que el Madrid jugaba con una defensa inédita y dejaría espacios.
- **La Consecuencia:** Oviedo solo remató 1 vez al arco. 
- **La Lección:** Una defensa suplente en un equipo Top no siempre significa "espacios abiertos". Al contrario, los suplentes suelen jugar conservadoramente para no cometer errores. Además, un equipo pequeño visitando el Bernabéu (Oviedo) tiende a atrincherarse y renunciar al ataque por completo ante el abrumador dominio de posesión.
- **Regla Añadida:** NUNCA apostar "Más de X Remates" a favor de un Underdog extremo jugando de visitante en un estadio Top, sin importar las bajas en la defensa local.

### 3. Ceguera Ante H2H Inexistente
- Fallamos en rechazar un partido donde el historial H2H era de solo 1 partido. Un solo encuentro no forma una tendencia, y menos si se jugó con las localías invertidas.

## PROTOCOLO INMEDIATO:
Cualquier predicción futura requerirá una auditoría manual exhaustiva de la extracción de datos y jamás forzaremos análisis en partidos sin un H2H maduro de 10 partidos.
