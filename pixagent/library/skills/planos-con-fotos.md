---
name: planos-con-fotos
description: Procedimiento preciso para ubicar fotos en un plano con flechas y conos de visión
keywords: plano, planos, ubicar fotos, ubicacion de fotos, croquis
---
# Ubicar fotos en un plano (procedimiento)

1. view_image(plano, cells=true): identifica ambientes, puertas, ventanas, escaleras y textos.
2. Hoja de contactos de las fotos (image_tools contact_sheet) y mira las dudosas individualmente.
3. Para cada foto deduce: ambiente, elementos visibles (puertas, ventanas, columnas, mobiliario),
   desde dónde se tomó y hacia dónde mira (view_angle: 0=derecha, 90=abajo, 180=izquierda,
   270=arriba en el plano).
4. Coordenada exacta: view_image(region=celda, grid=true).
5. compose_plan con todas las fotos (posición automática en márgenes), caption breve y
   approximate=true en las dudosas. Revisa el render y corrige solapes o flechas.
6. En la respuesta, lista las fotos dudosas y por qué.
