---
name: revisar-informe
description: Revisa un informe de obra (PDF escaneado o digital) por inconsistencias y entrega un reporte rápido en PDF
parametros: tipo, paginas
---
Revisa por inconsistencias los archivos adjuntos con revisar_informe (tipo: {{tipo}}; si está vacío, deduce
mensual_residente, preliquidacion, supervision o cuadro por el contenido; páginas: {{paginas}}).
Si no hay archivos adjuntos, pídelos. Responde con: resultado (presentable o no), los 5 hallazgos más
graves con su página y cómo corregirlos, y el PDF del reporte. Recuerda que las filas «REVISAR» son
lecturas de la IA que hay que confirmar en la página indicada.
