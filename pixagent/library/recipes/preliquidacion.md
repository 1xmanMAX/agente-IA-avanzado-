---
name: preliquidacion
description: Liquidación parcial (pre-liquidación) técnica y financiera según el numeral 7.3.10 de la Directiva 017-2023-CG/GMPL
parametros: numero*, periodo*, notas
---
Prepara la LIQUIDACIÓN PARCIAL N.º {{numero}} del periodo {{periodo}} de la obra activa, con los contenidos
a) a m) del numeral 7.3.10 de la Directiva 017-2023-CG/GMPL. Notas: {{notas}}.
1. Comprueba con obra action=plazos que corresponde una liquidación parcial (≤ 4 meses de plazo: solo total)
   y avisa del plazo de 30 días.
2. Pide lo que falte: valorización final y metrados, cuadro analítico de gastos por clasificador, ejecución
   presupuestal por específica, relación valorizada de insumos y balance (CSV/Excel o PDF escaneado), y la
   conformidad de gastos de Contabilidad.
3. report_builder create template_id=preliquidacion-obra (fields numero, periodo), generate, build.
4. Revisa el PDF con revisar_informe tipo=preliquidacion y corrige antes de entregar.
