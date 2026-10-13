# INFILE FEL para Vitec — Odoo 17

Rama `17.0vitec`, basada en `17.0`. El módulo técnico sigue llamándose `infilefel`;
esta variante está destinada a una instalación nueva sobre la localización de
Vitec. No es una migración del módulo `infilefel` original ya instalado en otra
base: los modelos, vistas y reportes de aquella variante no se cargan aquí.

## Comportamiento

El botón existente **Timbrar DTE** prepara el documento con
`changing_generate_json_l10n_gtm`, convierte sus datos a XML y utiliza el protocolo
directo del módulo original de INFILE: firma y luego certificación por HTTPS.
No publica solicitudes de certificación/anulación en MQTT ni llama a Xmarts.
Las dependencias de Xmarts siguen instaladas para conservar los campos, tipos de
documento, impuestos y reportes de Vitec; sus otros servicios no se desinstalan.
No se incorpora el timbrado automático del `_post` ni la anulación automática al
volver a borrador del módulo original.

Se incluyen los botones de pagos y el asistente de anulación de facturas. La
anulación conserva el UUID y cambia el estado solo si INFILE confirma éxito.
Para documentos emitidos con este adaptador se guarda la fecha, NIT emisor y
receptor exactos enviados. Para anular facturas históricas de Xmarts se requiere
su XML certificado en `l10n_xma_xml_ar` (Invoice Xml), validando que su UUID coincida.
No se reconstruye la fecha original usando la hora actual.

## Configuración

En **Compañías → INFILE directo** se reutilizan los campos de Vitec:

| Campo existente | Uso |
| --- | --- |
| `xma_infile_user` | Alias del firmador / usuario API |
| `xma_token_signer` | Llave de firma |
| `xma_api_key` | Llave de certificación y anulación |
| `l10n_xma_phrase_ids` | Frases de la compañía |

Se usan las credenciales de la compañía de la factura o pago. Las tres URL son
configurables y requieren HTTPS:

| Operación | Valor inicial |
| --- | --- |
| Firma | `https://signer-emisores.feel.com.gt/sign_solicitud_firmas/firma_xml` |
| Certificación | `https://certificador.feel.com.gt/fel/certificacion/v2/dte/` |
| Anulación | `https://certificador.feel.com.gt/fel/anulacion/v2/dte/` |

La antigua `xma_api_url` de proceso unificado permanece en la base y deja de
mostrarse en esta vista: este adaptador usa los tres endpoints anteriores.
No se deben reutilizar credenciales productivas al hacer pruebas que emitan DTE.

## Frases y adendas

Se ejecuta el generador de Vitec; no se cargan `fel_frase_ids`, `frase_py` ni
`adenda_extra` del módulo original de INFILE. Las reglas encontradas en Vitec son:

| Caso | TipoFrase / CodigoEscenario |
| --- | --- |
| FACT y NCRE de exportación | Catálogo: tipos 1 y 4, escenario 1 |
| FACT local en USD | Catálogo: tipo 4, escenario 19; además las frases de compañía |
| RANT | Tipo 9, escenario 6 |
| FESP y NABN | Se omite el nodo Frases |
| Otros casos, incluida FCAM local | Frases seleccionadas en la compañía |

La selección concreta depende de los registros existentes en la base. En
particular, el catálogo incluido en el repositorio Vitec no crea el escenario
4/19: debe existir en la base si se utiliza esa regla. Esta rama no inventa
frases ni modifica la configuración fiscal de la compañía.

**No se agregan adendas**, conforme a la indicación del usuario. El generador
actual contiene ejemplos comentados y no produce un nodo Adenda. Tampoco se
agrega el `NInt` del módulo original. Si otra extensión del generador incorpora
una adenda en el futuro, el conversor conserva los nodos recibidos.

El XML de la solicitud y el diagnóstico muestran las frases efectivamente
enviadas y si había una adenda. Los impuestos, descripciones y complemento FCAM
siguen procediendo del generador de Vitec. Este cambio no revisa ni sustituye sus
reglas de cálculo; durante la validación en staging deben compararse importes,
descuentos e impuestos del XML con las facturas de la base.

## Campos existentes

Se conserva el almacenamiento observado en la factura FACT001218:

| Respuesta INFILE | Campo Vitec | Etiqueta existente |
| --- | --- | --- |
| `serie` | `l10n_xma_uuid_invoice` | Folio Fiscal |
| `numero` | `l10n_xma_einvoice_serie` | Serie DTE |
| `uuid` | `l10n_xma_einvoice_numero` | Numero Autorizacion |

Las notas de crédito y débito corrigen la referencia al origen usando ese
mapeo: la serie real va a `SerieDocumentoOrigen` y el número real a
`NumeroDocumentoOrigen`. No se migran ni alteran facturas históricas.

## Respuestas y solicitudes inciertas

La pestaña **INFILE directo**, el chatter y el log guardan etapa, URL, HTTP,
identificador enviado en `IDENTIFICADOR`, códigos y descripción devueltos por
INFILE. Llaves y contenido XML de respuestas se omiten del diagnóstico. El XML
de la solicitud se conserva por separado, sin las credenciales de transporte.
Si INFILE entrega `xml_certificado` válido, también queda disponible para descargar.

`INFILE_*` son códigos locales del adaptador; los códigos del certificador están
en `response`. HTTP 200 no significa certificación: se exige `resultado: true`
y, al certificar, UUID, serie y número válidos.

Se guarda la intención antes de hacer HTTP y se bloquean envíos simultáneos del
mismo documento. No hay reintentos automáticos. Un rechazo explícito permite
corregir y volver a enviar. Un timeout del certificador, respuesta incompleta,
error HTTP o aviso de duplicidad deja el resultado **por confirmar** y bloquea
otro timbrado/anulación. Un proceso interrumpido queda como **solicitud iniciada**.

En esos casos, soporte debe consultar a INFILE con el identificador antes de
habilitar cualquier reenvío. Si INFILE confirma emisión, corresponde recuperar
su XML y registrar el resultado; si confirma que no emitió, soporte puede liberar
el estado tras documentar esa confirmación. No se ofrece un botón de reenvío que
ignore esa incertidumbre ni se presume que el header evita duplicados por sí solo.
Antes de cambiar del transporte Xmarts, también deben conciliarse las solicitudes
antiguas pendientes, que no tienen estado de seguimiento de este adaptador.

## Instalación y validación

1. Agregar este repositorio en la rama `17.0vitec` como addon `infilefel` en una
   rama/base de staging de Odoo 17 con los addons Vitec disponibles.
2. Actualizar la lista de aplicaciones e instalar **INFILE FEL Vitec**. Requiere
   `l10n_xma_einvoice_gtm` y `changing_generate_json_l10n_gtm`.
3. Revisar compañía, credenciales, tres URL y frases. La instalación activa los
   overrides del botón existente para esta base; no hay fallback a MQTT.
4. Verificar primero con transporte simulado o credenciales de pruebas del
   certificador: FACT, FCAM, NCRE, NDEB, rechazos, timeout y anulación. Comparar
   XML, importes, fechas, frases y reportes con documentos de referencia de Vitec.
5. Pasar a producción después de validar la instalación real y conciliar las
   solicitudes pendientes del proveedor anterior.

Pruebas aisladas (sin Odoo, PostgreSQL ni llamadas a INFILE):

```sh
python -m pip install requests lxml MarkupSafe psycopg2-binary
VITEC_SOURCE_DIR='/ruta/al/repositorio/Vitec' python -m unittest discover -s tests -v
```

Las pruebas ejercitan el generador real de Vitec con datos sintéticos y simulan
las respuestas HTTP. Las pruebas de métodos usan una fachada de Odoo; no validan
la instalación del módulo, la concurrencia real de PostgreSQL ni la aceptación
del XML por SAT/INFILE. Se requiere la validación de staging indicada arriba.

Los archivos del módulo original que no se importan se mantienen en la rama
para facilitar la comparación con `17.0`; solamente se carga el código listado
en `models/__init__.py` y las vistas del manifiesto actual.
