---
name: revisar-informe
description: Revisa un informe de obra (PDF escaneado o digital) por inconsistencias y entrega un reporte rápido en PDF
parametros: tipo, paginas
---
Revisa por inconsistencias el informe que adjunto (tipo: {{tipo}}; páginas: {{paginas}}).
Usa guia action=iniciar objetivo=revision: si no adjunté nada, pídemelo; si no dije el tipo, dedúcelo o
pregúntamelo. Luego revisar_informe y responde con: resultado (presentable o no), los 5 hallazgos más graves
con su página y cómo corregirlos, y el PDF. Las filas «REVISAR» son lecturas de la IA que hay que confirmar.
Al terminar, guia action=aportar paso=archivos y marca el paso de revisión con guia action=estado.
