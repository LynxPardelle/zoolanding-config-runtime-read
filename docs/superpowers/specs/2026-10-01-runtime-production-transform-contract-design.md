# Runtime Read: contrato del transform para producción

Estado: diseño aprobado para documentar; implementación y release pendientes.

## Problema comprobado

El artefacto protegido de TEST incluye `AWS::LanguageExtensions` y
`AWS::Serverless-2016-10-31` para publicar la versión y el alias `live`.
`tools/native_runtime_release.py` elimina las tres propiedades del alias al
preparar el candidato de producción, pero deja los dos transforms. El template
Original de la pila productiva usa únicamente `AWS::Serverless-2016-10-31`.
La política efectiva de su rol CloudFormation concede
`cloudformation:CreateChangeSet` sobre el transform Serverless y no sobre
LanguageExtensions. Aún no se ha lanzado un review productivo que pruebe si
CloudFormation rechaza ese candidato; se trata de un riesgo concreto detectado
antes de ejecutar Actions.

El paquete TEST verificado no contiene `Fn::ForEach`, `Fn::Length` ni
`Fn::ToJsonString`. La prueba de infraestructura existente exige
LanguageExtensions para TEST y el transform Serverless único para producción.

## Decisión

La operación productiva convertirá solo el *candidato de producción* al
contrato que ya usa la pila: `Transform: AWS::Serverless-2016-10-31`. El
artefacto sellado de TEST y la ruta de despliegue TEST conservarán su plantilla
original, versión y alias. Los bytes del ZIP no cambiarán. No se ampliará el
permiso del rol CloudFormation.

Antes de convertir, el operador exigirá el bloque exacto y único de ambos
transforms, las tres líneas TEST del alias y la ausencia de funciones exclusivas
de LanguageExtensions y macros anidadas. Cualquier forma desconocida abortará
antes de `s3:PutObject` o `cloudformation:CreateChangeSet`. La conversión
quitará las propiedades del alias y el primer transform; reemplazará solamente
`CodeUri` por el objeto S3 versionado que ya verifica el release. No cambiará
parámetros, condiciones, recursos, metadatos, outputs ni políticas.

## Comprobaciones y flujo

1. Añadir pruebas unitarias de la conversión: aceptar la plantilla TEST
   conocida; conservar TEST sin cambios; rechazar transforms extra o duplicados,
   intrinsics exclusivos, macros anidadas y diferencias en las líneas del alias.
2. Reproducir localmente el operador con el artefacto sellado y respuestas
   vigentes de AWS hasta una barrera anterior a toda escritura. Comparar el
   candidato con el template productivo Original y proyectarlo con las
   versiones fijadas de SAM. La proyección deberá preservar los seis recursos
   existentes salvo el puntero `ConfigRuntimeReadFunction.Code`.
3. Ejecutar las pruebas del repositorio, `sam validate` y `actionlint` si
   están disponibles. Verificar la procedencia, hashes, identidad del rol y
   permisos mediante AWS CLI antes del primer Action.
4. Integrar el operador por PR y los canales `dev → test → main`, con los
   selectores exactos y checks obligatorios. El workflow productivo requiere
   que el segundo padre de MAIN coincida con el SHA TEST y que el artefacto
   proceda de un `Deploy test` y `Verify immutable live alias` exitosos. Por
   ello se usará un artefacto elegible nuevo para ese SHA; no se reutilizará el
   artefacto actual de un SHA anterior. La expiración del artefacto se comprobará
   inmediatamente antes del review.
5. Solicitar autorización separada para configurar el selector productivo y
   ejecutar `review`. El review deberá mostrar exactamente un `Modify` sin
   reemplazo de `ConfigRuntimeReadFunction.Code`; si aparece otro cambio,
   abortar y diagnosticar sin ejecutar. Solicitar una nueva autorización del
   inventario y digest para `execute`. Antes y después de aplicar, comprobar
   ZIP, configuración, seis identidades físicas y ausencia de alias productivo.

## Alternativas descartadas

- Añadir al rol productivo `CreateChangeSet` sobre LanguageExtensions: evita
  modificar el operador, pero amplía IAM para un transform que el candidato
  productivo no necesita y obliga a otra revisión y ejecución de identidades.
- Sustituir todo el candidato por una plantilla nativa de código: exigiría más
  lógica de traducción y aumentaría las superficies que el guard debe probar.

## Criterio de aceptación

El replay local termina antes de escribir, con plantilla productiva de un solo
transform y proyección de un único cambio de código. Tras la promoción y un
review aprobado, el inventario real confirma ese mismo límite. Una ejecución
autorizada conserva la configuración y las identidades físicas, y Runtime Read
sirve la misma respuesta que TEST para una consulta de blog permitida. Cualquier
discrepancia detiene el flujo antes de un segundo Action de despliegue.
