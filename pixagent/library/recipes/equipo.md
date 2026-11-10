---
name: equipo
description: Reparte las órdenes de trabajo del mes al equipo técnico y muestra el tablero de entregables
parametros: periodo
---
Para la obra activa y el periodo {{periodo}} (si está vacío, el mes que toca informar):
1. Si la categoría no está determinada, pregúntala (obra action=categoria).
2. Muestra el personal clave exigido y quién falta registrar (obra action=personal).
3. Genera las órdenes de todo el equipo (obra action=ordenes) en un PDF breve, una página por rol, para
   enviarlas, y muestra el tablero (obra action=tablero).
4. Recuerda al residente que cada integrante puede escribir aquí («soy el almacenero…») para recibir su orden
   y entregar sus cuadros.
