# INFILE FEL — Odoo 17

Versión `17.0.1.1.1`, basada en la rama `17.0` de
[jeffrepo/infilefel](https://github.com/jeffrepo/infilefel/tree/17.0), revisión
`6cee663aedd9e692993d3572c55fce12f36657c2`.

Permite agregar frases FEL adicionales a cada factura mediante etiquetas.
El catálogo es independiente de las frases existentes del diario y de la compañía.

1. En **Contabilidad → Configuración → Frases FEL**, cree una frase indicando
   nombre, código de escenario, tipo de frase y compañía.
2. En una factura en borrador, seleccione una o varias etiquetas en
   **Frases FEL adicionales**, junto a los datos FEL de la cabecera.
3. Al certificar, el módulo agrega las etiquetas seleccionadas al nodo
   `dte:Frases` del XML. Conserva las frases generadas por el diario o la
   configuración general y omite las combinaciones repetidas de código y tipo.

Por ejemplo, si el diario genera escenario `1` / tipo `1` y escenario `1` /
tipo `2`, seleccionar una etiqueta escenario `1` / tipo `4` produce:

```xml
<dte:Frases xmlns:dte="http://www.sat.gob.gt/dte/fel/0.2.0">
    <dte:Frase CodigoEscenario="1" TipoFrase="1"/>
    <dte:Frase CodigoEscenario="1" TipoFrase="2"/>
    <dte:Frase CodigoEscenario="1" TipoFrase="4"/>
</dte:Frases>
```

El ejemplo muestra cómo se combinan los registros; la selección de códigos
aplicables a cada documento corresponde a la configuración de la empresa.
Las etiquetas se incorporan al XML de certificación; esta modificación no
agrega texto libre a los reportes PDF de Odoo.

| Perfil | Catálogo | Facturas |
| --- | --- | --- |
| Administrador de contabilidad | Crear, editar, archivar y eliminar | Seleccionar o quitar etiquetas en borrador |
| Usuario de facturación | Leer | Seleccionar o quitar etiquetas en borrador |
| Contabilidad de solo lectura | Leer | Consultar las etiquetas |

Los permisos del catálogo se aplican mediante ACL del servidor, además de
restringir el menú al grupo `account.group_account_manager`. Este es el grupo
Administrador definido en la
[seguridad de Contabilidad de Odoo 17](https://github.com/odoo/odoo/blob/17.0/addons/account/security/account_security.xml).
El menú usa el apartado de configuración de la
[estructura oficial de Contabilidad](https://github.com/odoo/odoo/blob/17.0/addons/account/views/account_menuitem.xml).

Cada compañía tiene su catálogo. Los códigos deben ser enteros mayores que
cero y la combinación escenario/tipo no puede repetirse en una compañía.
Las etiquetas de facturas contabilizadas o certificadas no se pueden cambiar.
Una frase ya asignada a una factura puede renombrarse o archivarse, pero sus
códigos y compañía no se pueden modificar ni se puede eliminar. Para usar
otros códigos, cree otra frase. Las frases archivadas dejan de ofrecerse en
nuevas selecciones y se conservan en las facturas que ya las tienen.

Para actualizar una instalación existente, sustituya la carpeta `infilefel`
por la incluida en el ZIP, reinicie Odoo y actualice **INFILE FEL** desde
Aplicaciones. También puede actualizar con el comando del servidor:

```bash
odoo-bin -d nombre_base -u infilefel --stop-after-init
```

La actualización crea la tabla `infilefel_frase_extra`, la relación con
`account.move`, las vistas, las reglas y los permisos. No requiere migrar
las frases que ya están configuradas en el diario o la compañía.

Esta versión corrige la carga de `views/report.xml` en Odoo 17: el ticket
se declara mediante `ir.actions.report`, conservando el identificador
`infilefel_ticket`, la plantilla, el formato de papel y la opción de impresión.

Se ejecutaron ocho pruebas locales de la lógica real de generación del XML,
incluyendo el código de ejemplo del diario, frases adicionales, deduplicación,
configuración de compañía, aislamiento entre facturas y orden de los nodos.
También se verificaron sintaxis Python/XML, archivos del manifiesto, permisos
declarados y el punto de inserción de las etiquetas en la vista oficial de Odoo 17.

Los siete XML cargados por el manifiesto también se validaron con el esquema
oficial `odoo/import_xml.rng` de Odoo 17. Puede repetir esta comprobación sin
una base de datos, indicando la ruta al esquema de su instalación:

```bash
python3 scripts/check_xml_schema.py --schema /home/odoo/src/odoo/odoo/import_xml.rng
```

Se incluyen pruebas de integración en `tests/test_fel_frases.py` para permisos,
selección por usuarios de facturación, compañías, bloqueo de facturas y archivo.
No se ejecutaron estas pruebas: el entorno de preparación no tiene Odoo ni
PostgreSQL. Tampoco se realizó una certificación con INFILE. Puede ejecutar
las pruebas de integración en una base de pruebas del servidor:

```bash
odoo-bin -d base_pruebas -u infilefel --test-enable --test-tags /infilefel --stop-after-init
```
