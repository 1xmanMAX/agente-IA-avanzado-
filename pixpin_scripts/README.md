# Scripts de PixPin para PixAgent

PixPin permite ejecutar JavaScript con su API `pixpin.*` (Configuración → Script, o
`PixPin.exe -f script.js`). PixAgent usa esa API en las dos direcciones:

| Dirección | Cómo |
|---|---|
| **PixPin → agente** | Scripts que guardan la captura en `<workspace>/inbox` (`directScreenShotAndSaveTo`) o lanzan `python -m pixagent send-clipboard` (`runSystem`). La interfaz web vigila `inbox` y añade la captura como adjunto al instante. |
| **Agente → PixPin** | El agente genera un `.js` temporal con `pixpin.pinFromFiles([...])` y lo envía con `PixPin.exe -f`. HTML y PDF se convierten antes a PNG. |

Los scripts dependen de las rutas de tu equipo, así que **se generan automáticamente**:

```
python -m pixagent install-pixpin
```

(o el botón *Generar scripts para PixPin* en la interfaz). Se crean en `<workspace>/pixpin_scripts/`:

- `01_enviar_ultima_captura.js` — vuelve a capturar la última zona seleccionada y la envía.
- `02_enviar_ventana_activa.js` — captura y envía la ventana activa.
- `03_enviar_portapapeles.js` — envía lo que hayas copiado (Ctrl+C sobre una captura de PixPin).
- `04_abrir_agente.js` — abre la interfaz avanzada.
- `05_enviar_pantalla.js` — captura y envía la pantalla bajo el ratón.

Cada mini app creada por el agente trae su propio `apps/<nombre>/abrir_en_pixpin.js` para abrirla
con un atajo de PixPin.

Ejemplo (lo que genera el script 01):

```js
(function () {
  var rect = pixpin.getSpRect(PixConst.SpRectLastShotRect);
  pixpin.directScreenShotAndSaveTo(rect, "C:/Users/TU_USUARIO/PixAgent/inbox/captura_$yyyy-MM-dd_HH-mm-ss$.png");
})();
```

Limitaciones del motor de scripts de PixPin (según su documentación): sin `async/await`, `?.`,
`require`, `fetch` ni `setTimeout`; los comandos vuelven antes de que termine la captura, por eso el
agente vigila la carpeta en lugar de esperar una respuesta.
