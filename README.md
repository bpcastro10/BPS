# Lector de cheques

Lee las imágenes de una carpeta, extrae los datos de cada cheque y genera un Excel solo con los que tienen observaciones. Las reglas de esa revisión están en `reglas.json`.

## Qué necesitas

- Windows, con Python 3.10 o superior. Durante la instalación marca **Add Python to PATH**.
- La carpeta del modelo `glm_ocr_merged` junto a `iniciar.bat`. Dentro debe estar `config.json` y el archivo del modelo con el nombre `model.safetensors`. Si el archivo se llama `model-001.safetensors`, renómbralo.

La primera ejecución descarga las librerías y puede tardar varios minutos. Hace falta internet.

## Cómo ponerlo en marcha

1. Cierra el programa si ya hay una ventana negra abierta. Si no, sigue corriendo la versión anterior.
2. Haz doble clic en `iniciar.bat`.
3. Espera a que cargue el modelo. Se abre el navegador en `http://127.0.0.1:5000`. Si no se abre, entra a esa dirección a mano.
4. Para cerrarlo, cierra la ventana negra. No basta con cerrar el navegador.

Si falta alguna librería o la instalación quedó a medias, ejecuta `reparar.bat` y después otra vez `iniciar.bat`.

Con una GPU NVIDIA, el instalador deja PyTorch para CPU y cada lectura es lenta. Para usar la GPU hay que instalar la versión CUDA de PyTorch dentro de la carpeta `.venv`, desde [pytorch.org](https://pytorch.org).

## Cómo se lee un lote

1. Copia las fotos o los escaneos en la carpeta `entrada`. Sirven PNG, JPG, WEBP, BMP, TIFF y GIF. Las fotos HEIC del iPhone necesitan, además, la librería `pillow-heif`.
2. En la página pulsa **Leer carpeta y generar informe**.
3. El programa lee una imagen tras otra, aplica `reglas.json` y guarda el Excel en la carpeta `informes`.
4. También puedes descargarlo desde la página.

El Excel incluye únicamente los cheques con observaciones. Un cheque tiene una observación cuando alguna validación activa queda en **NO**. Si todos salen en **SI**, el archivo se genera igual, pero solo con el encabezado.

En la misma página sigue disponible la lectura de una sola imagen, para revisar un cheque suelto. Esa lectura no genera el Excel.

## Qué revisa

| Columna | Queda en SI cuando |
| --- | --- |
| Firma | El modelo detecta una firma. |
| Beneficiario | Leyó a quién va dirigido el cheque. |
| Coincide_valor | El valor en números y el valor en letras son el mismo monto. |
| Fecha_correcta | La fecha se reconoce y todavía no han pasado 13 meses. |
| Endoso | Hay endoso. |

La fecha se compara con el día de hoy. Si ya pasaron 13 meses o más, o si la fecha no se entiende, **Fecha_correcta** queda en **NO** y el cheque entra al informe. Un cheque del día en que se cumplen exactamente 13 meses también queda en **NO**.

Estas validaciones se encienden o se apagan en `reglas.json`, en el bloque `validaciones`, cambiando `activa` a `true` o `false`. La columna sigue apareciendo en el Excel. Si la regla está en `false`, un NO de esa columna no mete el cheque al informe.

Si las imágenes son solo el frente y no se ve el endoso, pon la validación `endoso` en `false`. Si la dejas activa, esos cheques saldrán con Endoso en NO.

El número de meses está en `fecha.meses_maximos`. Ahora vale `13`.

## Formatos de fecha que acepta

El texto puede traer la ciudad delante, como `Quito, 30 de mayo de 2026`. Se reconocen estos formatos:

- `AAAA/MM/DD`, por ejemplo `2026/05/30`
- `AAAA-MM-DD`, por ejemplo `2026-10-02` o `2026 - 10 - 2`
- `AAAA, MM, DD`, por ejemplo `2026, 05, 30`
- `AAAA, Mes, DD`, por ejemplo `2026, mayo, 30`
- `AAAA, Mes abreviado, DD`, por ejemplo `2026, may., 30`
- `AAAA, Mes romano, DD`, por ejemplo `2026, V, 30`
- `DD de Mes de AAAA`, por ejemplo `30 de mayo de 2026`
- `DD de Mes del AAAA`, por ejemplo `30 de mayo del 2026`
- `DD de Mes abreviado. De AAAA`, por ejemplo `30 de may. De 2026`
- `DD de Mes abreviado. del AAAA`, por ejemplo `30 de may. del 2026`
- `DD de Mes abreviado. de AAAA`, por ejemplo `30 de may. de 2026`
- `DD de Mes romano de AAAA`, por ejemplo `30 de V de 2026`
- `DD de Mes abreviado. AAAA`, por ejemplo `30 de may. 2026`
- `Mes DD, AAAA`, por ejemplo `mayo 30, 2026`
- `DD de Mes/ AAAA`, por ejemplo `30 de mayo/ 2026`
- `Mes abreviado. DD/AAAA`, por ejemplo `may. 30/2026`
- `AAAA Mes DD`, por ejemplo `2026 mayo 30`
- `DD Mes AAAA`, por ejemplo `30 mayo 2026`

Los meses en romano van de I a XII. Las abreviaturas son ene, feb, mar, abr, may, jun, jul, ago, sep, oct, nov y dic, con punto o sin él.

## Columnas del Excel

El archivo tiene una hoja llamada **Informe**. El encabezado es azul y cada NO va en rojo.

1. Nombre_archivo
2. Cuenta_No
3. Cheque_No
4. A_la_orden_de
5. Valor_numero
6. Valor_texto
7. Cliente
8. Fecha
9. Endoso, con el texto del endoso si se leyó
10. Firma
11. Beneficiario
12. Coincide_valor
13. Fecha_correcta
14. Endoso, en SI o NO

Las últimas cinco columnas son el resultado de la validación. Las anteriores son lo que se leyó en la imagen.

Si una imagen no se puede leer, igual entra al informe, con las validaciones en NO.

## Carpetas

| Carpeta o archivo | Para qué sirve |
| --- | --- |
| `entrada` | Imágenes que se van a leer. |
| `informes` | Excel generados. El nombre lleva la fecha y la hora. |
| `reglas.json` | Meses permitidos, formatos de fecha y validaciones activas. |
| `glm_ocr_merged` | Modelo que lee el cheque. No lo borres. |
| `iniciar.bat` | Arranca el programa en Windows. |
| `reparar.bat` | Vuelve a instalar las librerías si algo falla. |

Puedes cambiar la carpeta de entrada, la de informes, el archivo de reglas o el modelo con las variables de entorno `ENTRADA_DIR`, `INFORMES_DIR`, `REGLAS_PATH` y `MODEL_PATH`.
