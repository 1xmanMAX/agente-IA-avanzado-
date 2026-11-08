---
name: informe-diario
description: Reporte diario de obra a partir de fotos y notas del día
parametros: obra*, fecha, notas
---
Prepara el REPORTE DIARIO DE OBRA de la obra "{{obra}}" del día {{fecha}}.
Usa las fotos y archivos adjuntos y estas notas: {{notas}}.
Contenido: datos generales, trabajos ejecutados por frente (con fotos citadas), personal y equipos si
se mencionan, incidencias y observaciones de calidad y seguridad, actividades para mañana.
Entrega un PDF de 2-4 páginas en reports/ con un panel fotográfico al final (photo_panel o
create_pdf con rejilla de fotos). Si no hay fecha, usa la de hoy y dilo.
