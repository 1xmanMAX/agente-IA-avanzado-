---
name: informe-fotografico
description: Estructura y buenas prácticas de informes y paneles fotográficos de obra o inspección
keywords: panel fotografico, informe fotografico, registro fotografico, fotos de obra, reporte fotografico
---
# Informe / panel fotográfico de obra

Estructura recomendada:
1. Cabecera: proyecto/obra, ubicación, cliente o promotor, autor, fecha, objeto y alcance.
2. Por cada foto (ficha): número, fecha/hora si se conoce (EXIF), ubicación en plano (eje, nivel,
   ambiente), orientación o vista, pie descriptivo técnico, partida/elemento y estado
   (Conforme / Observación / No conforme / Pendiente).
3. Orden: por recorrido lógico (de exterior a interior, por nivel) o por partida; agrupa por zona.
4. Pies de foto: qué se ve + dónde + por qué importa, en una línea ("Fisura diagonal en muro M-3,
   eje B, nivel 2; apertura estimada 2 mm"). No inventes medidas: si no hay escala, dilo.
5. Cierre: resumen de observaciones y acciones (responsable, plazo, verificación).
Herramientas: photo_panel para la maqueta PDF; si hay plano, compose_plan con las fotos ubicadas;
para muchas fotos, local_ai(caption) si hay IA local y luego revisa tú los pies.
