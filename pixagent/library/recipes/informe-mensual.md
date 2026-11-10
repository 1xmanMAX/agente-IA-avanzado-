---
name: informe-mensual
description: Informe mensual del residente según el Anexo 2 de la Directiva 017-2023-CG/GMPL (PDF)
parametros: periodo*, notas
---
Prepara el INFORME MENSUAL DEL RESIDENTE del periodo {{periodo}} (formato AAAA-MM) según el Anexo 2 de la
Directiva 017-2023-CG/GMPL. Notas del residente: {{notas}}.
1. Revisa la obra activa (obra action=ver). Si no hay, créala preguntando los datos. Si la categoría no
   está determinada, PREGÚNTALA (obra action=categoria; con ejemplos si no la sabe).
2. Muestra el tablero del periodo y lista los cuadros pendientes con su responsable; pregunta si generar
   igual (quedan marcados como pendientes) o esperar.
3. Usa las fotos y archivos adjuntos; crea el informe con report_builder (template_id=informe-mensual-residente,
   periodo={{periodo}}), genera y construye el PDF.
4. Revisa el PDF con revisar_informe y corrige los errores antes de entregarlo. Entrega el PDF y el resumen.
